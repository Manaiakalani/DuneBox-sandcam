"""
Dashboard server: serves the web dashboard and streams depth frames + app state.

One port (default 8765) carries everything:

    GET  /                 web/index.html
    GET  /assets/<file>    static files under web/assets/
    GET  /api/palettes     256-entry colour LUTs for every theme (JSON)
    GET  /api/session      {"pin_required": bool}
    GET  /api/auth?pin=    200 if the PIN is right, 401/429 otherwise
    GET  /qr.svg           QR code of the dashboard URL (requires `segno`)
    GET  /snapshots/<terrain_YYYYMMDD_HHMMSS>.<npy|asc|png>   saved terrain download
    GET  /healthz          plain "ok"
    WS   /ws               state (JSON text), depth frames (binary), commands

Binding to a non-loopback host (e.g. "0.0.0.0") exposes the dashboard to the
local network. In that case a PIN is required on the WebSocket; if none is
configured, a random 6-digit PIN is generated for the session.
"""

from __future__ import annotations

import asyncio
import hmac
import json
import logging
import mimetypes
import pathlib
import secrets
import socket
import struct
import threading
import time
from http import HTTPStatus
from typing import Any
from urllib.parse import parse_qs, urlsplit

import cv2
import numpy as np

from dem_loader import snapshot_path

log = logging.getLogger(__name__)

WEB_ROOT = pathlib.Path(__file__).resolve().parent / "web"

_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}
_MAX_PIN_FAILURES = 5
_PIN_LOCKOUT_SECONDS = 60.0


def is_loopback(host: str) -> bool:
    return host.strip().lower() in _LOOPBACK_HOSTS


def lan_ip() -> str:
    """Best-effort primary LAN address (no packets are sent)."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("10.255.255.255", 1))
        return sock.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        sock.close()


class DepthStreamServer:
    """Serve the dashboard and broadcast depth frames and app state."""

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 8765,
        max_fps: int = 10,
        pin: str = "",
    ) -> None:
        self._host = host
        self._port = port
        self._max_fps = max(1, max_fps)
        self._min_interval = 1.0 / self._max_fps

        pin = "".join(ch for ch in str(pin) if ch.isdigit())
        if not is_loopback(host) and not pin:
            pin = f"{secrets.randbelow(1_000_000):06d}"
        self._pin = pin if not is_loopback(host) else ""

        self._running = False
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None

        self._clients: set[Any] = set()
        self._lock = threading.Lock()

        self._pending_frame: bytes | None = None
        self._pending_state: str | None = None
        self._pending_events: list[str] = []
        self._last_frame_time: float = 0.0
        self._command_queue: list[dict[str, Any]] = []
        self._pin_failures: dict[str, tuple[int, float]] = {}

    # ── public API (called from main thread) ──────────────────────────

    @property
    def pin(self) -> str:
        """PIN required by LAN clients ("" when bound to loopback)."""
        return self._pin

    @property
    def lan_enabled(self) -> bool:
        return not is_loopback(self._host)

    def dashboard_url(self) -> str:
        """URL an operator should open; includes the PIN when one is required."""
        host = lan_ip() if self._host in ("0.0.0.0", "") else self._host
        url = f"http://{host}:{self._port}/"
        if self._pin:
            url += f"?pin={self._pin}"
        return url

    def start(self) -> None:
        """Start the server in a background daemon thread."""
        if self._running:
            return
        # A previous stop() may have timed out, leaving the old thread alive.
        # Don't spawn a second thread on top of it: its finally block would later
        # clobber the new thread's refs. Refuse to start until it has exited.
        if self._thread is not None and self._thread.is_alive():
            log.warning(
                "DepthStreamServer: previous background thread still alive; "
                "not starting a new one"
            )
            return
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        log.info("Dashboard starting at %s", self.dashboard_url())

    def stop(self) -> None:
        """Cleanly shut down the server."""
        self._running = False
        # Let the _serve() while-loop exit naturally when it sees _running=False,
        # which then closes the server gracefully. Calling loop.stop() here would
        # abort run_until_complete() and skip server.close()/wait_closed().
        thread = self._thread
        if thread is not None:
            thread.join(timeout=3.0)
            if thread.is_alive():
                # Thread still running (slow client cleanup); leave attributes intact
                # so _run()'s finally block can still reference them safely.
                log.warning(
                    "DepthStreamServer: background thread did not exit within timeout; "
                    "cleanup deferred to thread"
                )
            else:
                self._thread = None
                self._loop = None
        with self._lock:
            self._clients.clear()
        log.info("DepthStreamServer stopped")

    def push_frame(self, height_data: np.ndarray) -> None:
        """Queue a depth frame for broadcast (throttled to max_fps)."""
        now = time.monotonic()
        if now - self._last_frame_time < self._min_interval:
            return

        # Skip expensive PNG encoding when no clients are connected
        with self._lock:
            if not self._clients:
                return

        self._last_frame_time = now

        try:
            img_u8 = (np.clip(height_data, 0.0, 1.0) * 255).astype(np.uint8)
            h, w = img_u8.shape[:2]
            ok, buf = cv2.imencode(".png", img_u8, [cv2.IMWRITE_PNG_COMPRESSION, 3])
            if not ok:
                return
            # 4-byte header: width(u16) + height(u16), then PNG payload
            payload = struct.pack(">HH", w, h) + buf.tobytes()
            with self._lock:
                self._pending_frame = payload
        except Exception:
            log.debug("DepthStreamServer: frame encode failed", exc_info=True)

        self._wake()

    def push_state(self, state: dict[str, Any]) -> None:
        """Queue a JSON state update for broadcast (latest wins)."""
        try:
            msg = json.dumps({"type": "state", **state}, separators=(",", ":"))
            with self._lock:
                self._pending_state = msg
        except Exception:
            log.debug("DepthStreamServer: state encode failed", exc_info=True)
        self._wake()

    def push_event(self, event: dict[str, Any]) -> None:
        """Queue a one-off message (e.g. a command acknowledgement). Never dropped
        in favour of a newer one, unlike state."""
        try:
            msg = json.dumps(event, separators=(",", ":"))
        except (TypeError, ValueError):
            return
        with self._lock:
            if len(self._pending_events) < 64:
                self._pending_events.append(msg)
        self._wake()

    def get_client_count(self) -> int:
        with self._lock:
            return len(self._clients)

    def poll_commands(self) -> list[dict[str, Any]]:
        """Return and clear any queued commands from dashboard clients."""
        with self._lock:
            cmds = self._command_queue
            self._command_queue = []
        return cmds

    # ── background thread ─────────────────────────────────────────────

    def _wake(self) -> None:
        with self._lock:
            has_clients = bool(self._clients)
        loop = self._loop
        if loop is not None and has_clients:
            try:
                loop.call_soon_threadsafe(self._schedule_broadcast)
            except RuntimeError:
                pass  # loop closed between check and call

    def _run(self) -> None:
        try:
            import websockets.asyncio.server  # noqa: F401
        except ImportError:
            log.error("DepthStreamServer: 'websockets>=13' package not installed")
            self._running = False
            return

        loop = asyncio.new_event_loop()
        self._loop = loop
        asyncio.set_event_loop(loop)

        try:
            loop.run_until_complete(self._serve())
        except Exception:
            log.exception("DepthStreamServer thread error")
        finally:
            try:
                loop.run_until_complete(loop.shutdown_asyncgens())
            except Exception:
                pass
            loop.close()
            # Clear instance refs only if they still point to THIS thread/loop.
            if self._loop is loop:
                self._loop = None
            if self._thread is threading.current_thread():
                self._thread = None
                self._running = False

    async def _serve(self) -> None:
        from websockets.asyncio.server import serve

        async with serve(
            self._handler,
            self._host,
            self._port,
            process_request=self._process_request,
            ping_interval=20,
            ping_timeout=20,
            max_size=2**16,
        ) as server:
            log.info("Dashboard listening at %s", self.dashboard_url())
            while self._running:
                await asyncio.sleep(0.5)
            server.close()
            await server.wait_closed()

    # ── HTTP ──────────────────────────────────────────────────────────

    def _process_request(self, connection: Any, request: Any) -> Any:
        """Serve plain HTTP routes; return None to continue a WebSocket upgrade."""
        url = urlsplit(request.path)
        path = url.path
        is_upgrade = "websocket" in request.headers.get("Upgrade", "").lower()

        if is_upgrade:
            if path not in ("/ws", "/"):
                return self._response(connection, HTTPStatus.NOT_FOUND, b"not found")
            return self._check_pin(connection, url.query)

        if path in ("/", "/index.html"):
            return self._file(connection, WEB_ROOT / "index.html")
        if path.startswith("/assets/"):
            return self._file(connection, WEB_ROOT / path.lstrip("/"))
        if path == "/api/palettes":
            return self._json(connection, _palettes())
        if path == "/api/session":
            return self._json(connection, {"pin_required": bool(self._pin)})
        if path == "/api/auth":
            rejected = self._check_pin(connection, url.query)
            return rejected or self._response(connection, HTTPStatus.OK, b"ok", "text/plain")
        if path == "/qr.svg":
            # The QR encodes the PIN, so it is guarded like the socket itself.
            return self._check_pin(connection, url.query) or self._qr(connection)
        if path == "/healthz":
            return self._response(connection, HTTPStatus.OK, b"ok", "text/plain")
        if path.startswith("/snapshots/"):
            return self._check_pin(connection, url.query) or self._snapshot(connection, path)
        return self._response(connection, HTTPStatus.NOT_FOUND, b"not found", "text/plain")

    def _check_pin(self, connection: Any, query: str) -> Any:
        if not self._pin:
            return None
        remote = str((connection.remote_address or ("?",))[0])
        now = time.monotonic()
        failures, since = self._pin_failures.get(remote, (0, now))
        if failures >= _MAX_PIN_FAILURES and now - since < _PIN_LOCKOUT_SECONDS:
            return self._response(
                connection, HTTPStatus.TOO_MANY_REQUESTS, b"too many attempts", "text/plain"
            )
        supplied = parse_qs(query).get("pin", [""])[0]
        if hmac.compare_digest(supplied.encode(), self._pin.encode()):
            self._pin_failures.pop(remote, None)
            return None
        if now - since >= _PIN_LOCKOUT_SECONDS:
            failures, since = 0, now
        self._pin_failures[remote] = (failures + 1, since)
        return self._response(connection, HTTPStatus.UNAUTHORIZED, b"pin required", "text/plain")

    def _file(self, connection: Any, path: pathlib.Path) -> Any:
        try:
            resolved = path.resolve()
            resolved.relative_to(WEB_ROOT)
            body = resolved.read_bytes()
        except (OSError, ValueError):
            return self._response(connection, HTTPStatus.NOT_FOUND, b"not found", "text/plain")
        ctype = mimetypes.guess_type(resolved.name)[0] or "application/octet-stream"
        if resolved.suffix == ".woff2":
            ctype = "font/woff2"
        if ctype.startswith("text/") or ctype in ("application/javascript", "image/svg+xml"):
            ctype += "; charset=utf-8"
        return self._response(connection, HTTPStatus.OK, body, ctype)

    def _snapshot(self, connection: Any, path: str) -> Any:
        filename = path.rsplit("/", 1)[-1]
        stem, dot, ext = filename.rpartition(".")
        resolved = snapshot_path(stem, f".{ext}") if dot else None
        if resolved is None:
            return self._response(connection, HTTPStatus.NOT_FOUND, b"not found", "text/plain")
        try:
            body = resolved.read_bytes()
        except OSError:
            return self._response(connection, HTTPStatus.NOT_FOUND, b"not found", "text/plain")
        ctype = {"png": "image/png", "asc": "text/plain; charset=us-ascii"}.get(
            ext, "application/octet-stream"
        )
        response = self._response(connection, HTTPStatus.OK, body, ctype)
        response.headers["Content-Disposition"] = f'attachment; filename="{resolved.name}"'
        return response

    def _json(self, connection: Any, payload: Any) -> Any:
        body = json.dumps(payload, separators=(",", ":")).encode()
        return self._response(connection, HTTPStatus.OK, body, "application/json")

    def _qr(self, connection: Any) -> Any:
        try:
            import segno
        except ImportError:
            return self._response(
                connection, HTTPStatus.NOT_IMPLEMENTED, b"install segno for QR codes", "text/plain"
            )
        svg = segno.make(self.dashboard_url(), error="m").svg_inline(
            scale=6, border=2, dark="#ededed", light=None
        )
        return self._response(connection, HTTPStatus.OK, svg.encode(), "image/svg+xml; charset=utf-8")

    @staticmethod
    def _response(connection: Any, status: HTTPStatus, body: bytes, ctype: str = "text/html") -> Any:
        response = connection.respond(status, "")
        response.body = body
        del response.headers["Content-Type"]
        del response.headers["Content-Length"]
        response.headers["Content-Type"] = ctype
        response.headers["Content-Length"] = str(len(body))
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    # ── WebSocket ─────────────────────────────────────────────────────

    async def _handler(self, websocket: Any) -> None:
        remote = websocket.remote_address
        log.info("DepthStreamServer: client connected from %s", remote)
        with self._lock:
            self._clients.add(websocket)
        try:
            async for message in websocket:
                if not isinstance(message, str):
                    continue
                try:
                    data = json.loads(message)
                except json.JSONDecodeError:
                    continue
                if isinstance(data, dict) and data.get("type") == "command":
                    with self._lock:
                        if len(self._command_queue) < 32:
                            self._command_queue.append(data)
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
        """Send pending events, state and frame to all connected clients."""
        from websockets.exceptions import ConnectionClosed

        with self._lock:
            events = self._pending_events
            frame_data = self._pending_frame
            state_data = self._pending_state
            self._pending_events = []
            self._pending_frame = None
            self._pending_state = None
            clients = list(self._clients)

        if not clients:
            return

        for ws in clients:
            try:
                for event in events:
                    await ws.send(event)
                if state_data is not None:
                    await ws.send(state_data)
                if frame_data is not None:
                    await ws.send(frame_data)
            except (ConnectionClosed, OSError):
                with self._lock:
                    self._clients.discard(ws)


def _palettes() -> dict[str, list[str]]:
    """Every renderer theme as 256 hex colours, so the dashboard's live view
    matches the projection."""
    from renderer import _LUTS

    return {
        name: [f"{r:02x}{g:02x}{b:02x}" for r, g, b in lut.tolist()]
        for name, lut in _LUTS.items()
    }
