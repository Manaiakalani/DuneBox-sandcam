"""
WebSocket server for streaming depth frames and app state.

Runs in a background thread, serves depth data as binary frames
and state updates as JSON to connected web clients.
"""

from __future__ import annotations

import asyncio
import json
import logging
import struct
import threading
import time
from typing import Any

import cv2
import numpy as np

log = logging.getLogger(__name__)


class DepthStreamServer:
    """Broadcast depth frames and app state over WebSocket."""

    def __init__(self, host: str = "0.0.0.0", port: int = 8765, max_fps: int = 10) -> None:
        self._host = host
        self._port = port
        self._max_fps = max(1, max_fps)
        self._min_interval = 1.0 / self._max_fps

        self._running = False
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None

        self._clients: set[Any] = set()
        self._lock = threading.Lock()

        self._pending_frame: bytes | None = None
        self._pending_state: str | None = None
        self._last_frame_time: float = 0.0

    # ── public API (called from main thread) ──────────────────────────

    def start(self) -> None:
        """Start the WebSocket server in a background daemon thread."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        log.info("DepthStreamServer starting on ws://%s:%d", self._host, self._port)

    def stop(self) -> None:
        """Cleanly shut down the server."""
        self._running = False
        if self._loop is not None:
            self._loop.call_soon_threadsafe(self._loop.stop)
        if self._thread is not None:
            self._thread.join(timeout=3.0)
            self._thread = None
        with self._lock:
            self._clients.clear()
        self._loop = None
        log.info("DepthStreamServer stopped")

    def push_frame(self, height_data: np.ndarray) -> None:
        """Queue a depth frame for broadcast (throttled to max_fps)."""
        now = time.monotonic()
        if now - self._last_frame_time < self._min_interval:
            return
        self._last_frame_time = now

        try:
            # Convert normalized float32 (0-1) to uint8 greyscale
            img_u8 = (np.clip(height_data, 0.0, 1.0) * 255).astype(np.uint8)
            h, w = img_u8.shape[:2]

            # PNG compress
            ok, buf = cv2.imencode(".png", img_u8, [cv2.IMWRITE_PNG_COMPRESSION, 3])
            if not ok:
                return

            # 4-byte header: width(u16) + height(u16), then PNG payload
            header = struct.pack(">HH", w, h)
            payload = header + buf.tobytes()

            with self._lock:
                self._pending_frame = payload
        except Exception:
            log.debug("DepthStreamServer: frame encode failed", exc_info=True)

        if self._loop is not None and self._clients:
            self._loop.call_soon_threadsafe(self._schedule_broadcast)

    def push_state(self, state: dict[str, Any]) -> None:
        """Queue a JSON state update for broadcast."""
        try:
            msg = json.dumps({"type": "state", **state}, separators=(",", ":"))
            with self._lock:
                self._pending_state = msg
        except Exception:
            log.debug("DepthStreamServer: state encode failed", exc_info=True)

        if self._loop is not None and self._clients:
            self._loop.call_soon_threadsafe(self._schedule_broadcast)

    def get_client_count(self) -> int:
        with self._lock:
            return len(self._clients)

    # ── background thread ─────────────────────────────────────────────

    def _run(self) -> None:
        """Entry point for the background thread."""
        try:
            import websockets  # noqa: F811
            import websockets.server
        except ImportError:
            log.error("DepthStreamServer: 'websockets' package not installed")
            self._running = False
            return

        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)

        try:
            self._loop.run_until_complete(self._serve())
        except Exception:
            log.exception("DepthStreamServer thread error")
        finally:
            try:
                self._loop.run_until_complete(self._loop.shutdown_asyncgens())
            except Exception:
                pass
            self._loop.close()
            self._loop = None
            self._running = False

    async def _serve(self) -> None:
        import websockets.server

        async with websockets.server.serve(
            self._handler,
            self._host,
            self._port,
            ping_interval=20,
            ping_timeout=20,
            max_size=2**20,
        ) as server:
            log.info("DepthStreamServer listening on ws://%s:%d", self._host, self._port)
            while self._running:
                await asyncio.sleep(0.5)
            server.close()
            await server.wait_closed()

    async def _handler(self, websocket: Any) -> None:
        """Handle a single WebSocket client connection."""
        remote = websocket.remote_address
        log.info("DepthStreamServer: client connected from %s", remote)
        with self._lock:
            self._clients.add(websocket)
        try:
            # Keep connection alive; we only send, but drain incoming pongs
            async for _ in websocket:
                pass
        except Exception:
            pass
        finally:
            with self._lock:
                self._clients.discard(websocket)
            log.info("DepthStreamServer: client disconnected from %s", remote)

    def _schedule_broadcast(self) -> None:
        """Schedule a broadcast coroutine on the event loop (thread-safe)."""
        if self._loop is not None and self._loop.is_running():
            self._loop.create_task(self._broadcast())

    async def _broadcast(self) -> None:
        """Send pending frame / state to all connected clients."""
        import websockets.exceptions

        with self._lock:
            frame_data = self._pending_frame
            state_data = self._pending_state
            self._pending_frame = None
            self._pending_state = None
            clients = list(self._clients)

        if not clients:
            return

        for ws in clients:
            try:
                if state_data is not None:
                    await ws.send(state_data)
                if frame_data is not None:
                    await ws.send(frame_data)
            except (websockets.exceptions.ConnectionClosed, OSError):
                with self._lock:
                    self._clients.discard(ws)
