"""
Inter-app communication bridge.

Connects DuneBox-sandcam (Python) to DuneBox (C++) via TCP socket.
Runs as a background thread, non-blocking to the main pygame loop.

Protocol: newline-delimited JSON (NDJSON) — one JSON object per line.
The Python side acts as **server** (listens on port); the C++ side
connects as a client.
"""

from __future__ import annotations

import json
import logging
import queue
import select
import socket
import threading
import time
from typing import Any

log = logging.getLogger(__name__)

# Safety cap on a single NDJSON line. A well-formed message is a few hundred
# bytes; anything larger means a malformed or hostile peer sending an
# unterminated stream, so we drop the connection instead of buffering forever.
MAX_LINE_BYTES = 64 * 1024


class AppBridge:
    """TCP bridge between DuneBox-sandcam (Python/server) and DuneBox (C++/client)."""

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 9876,
        role: str = "server",
    ) -> None:
        self._host = host
        self._port = port
        self._role = role  # 'server' or 'client'

        self._running = False
        self._connected_event = threading.Event()
        self._thread: threading.Thread | None = None

        # Thread-safe queues for send / receive
        self._send_q: queue.Queue[dict[str, Any]] = queue.Queue()
        self._recv_q: queue.Queue[dict[str, Any]] = queue.Queue()

        # Socket state (managed by background thread only)
        self._server_sock: socket.socket | None = None
        self._conn_sock: socket.socket | None = None

    # ── public API ────────────────────────────────────────────────────

    def start(self) -> None:
        """Start the bridge in a background daemon thread."""
        if self._running:
            return
        # Refuse to spawn a second worker while a prior thread is still winding
        # down (e.g. after a stop() whose join() timed out). Mirrors
        # DepthStreamServer.start() so a quick stop()/start() can't leave two
        # threads fighting over the same sockets.
        if self._thread is not None and self._thread.is_alive():
            log.warning("Bridge start() ignored: previous thread still alive")
            return
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        log.info("Bridge started (%s on %s:%d)", self._role, self._host, self._port)

    def stop(self) -> None:
        """Cleanly shut down the bridge."""
        self._running = False
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=3.0)
            if thread.is_alive():
                # Join timed out; leave _thread set so a later start() can detect
                # the still-alive worker instead of spawning a duplicate.
                log.warning("Bridge thread did not stop within timeout")
            else:
                self._thread = None
        self._close_all()
        log.info("Bridge stopped")

    def send(self, msg: dict[str, Any]) -> None:
        """Enqueue a JSON message for sending (thread-safe, non-blocking)."""
        if self._running:
            self._send_q.put(msg)

    def poll(self) -> list[dict[str, Any]]:
        """Return all messages received since the last poll."""
        msgs: list[dict[str, Any]] = []
        while True:
            try:
                msgs.append(self._recv_q.get_nowait())
            except queue.Empty:
                break
        return msgs

    def is_connected(self) -> bool:
        return self._connected_event.is_set()

    # ── background thread ─────────────────────────────────────────────

    def _run(self) -> None:
        """Main loop for the background thread."""
        try:
            while self._running:
                try:
                    if self._role == "server":
                        self._run_server()
                    else:
                        self._run_client()
                except Exception:
                    log.exception("Bridge thread error")
                    self._connected_event.clear()
                    self._close_conn()
                    if self._running:
                        time.sleep(2.0)
        finally:
            # Clear our own handle if stop() left it set (e.g. a timed-out join),
            # so a subsequent start() is not blocked by this finished thread.
            if self._thread is threading.current_thread():
                self._thread = None

    def _run_server(self) -> None:
        """Listen for a single client, then service the connection."""
        self._server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server_sock.settimeout(1.0)
        self._server_sock.bind((self._host, self._port))
        self._server_sock.listen(1)
        log.info("Bridge server listening on %s:%d", self._host, self._port)

        while self._running:
            try:
                conn, addr = self._server_sock.accept()
                log.info("Bridge client connected from %s", addr)
                conn.setblocking(False)
                self._conn_sock = conn
                self._connected_event.set()
                self._service_connection()
            except socket.timeout:
                continue
            except OSError:
                if self._running:
                    raise
                break

        self._close_all()

    def _run_client(self) -> None:
        """Connect to the server and service the connection."""
        while self._running:
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(2.0)
                sock.connect((self._host, self._port))
                sock.setblocking(False)
                self._conn_sock = sock
                self._connected_event.set()
                log.info("Bridge connected to %s:%d", self._host, self._port)
                self._service_connection()
            except (ConnectionRefusedError, OSError):
                self._connected_event.clear()
                self._close_conn()
                if self._running:
                    time.sleep(2.0)

    def _service_connection(self) -> None:
        """Read/write loop on an established connection."""
        buf = b""
        sock = self._conn_sock
        assert sock is not None

        while self._running and self._connected_event.is_set():
            # ── send queued messages ──
            while not self._send_q.empty():
                try:
                    msg = self._send_q.get_nowait()
                    line = json.dumps(msg, separators=(",", ":")) + "\n"
                    self._send_all(sock, line.encode("utf-8"))
                except (BrokenPipeError, ConnectionResetError, OSError):
                    self._connected_event.clear()
                    return
                except queue.Empty:
                    break

            # ── receive ──
            try:
                readable, _, _ = select.select([sock], [], [], 0.05)
                if readable:
                    data = sock.recv(4096)
                    if not data:
                        log.info("Bridge peer disconnected")
                        self._connected_event.clear()
                        return
                    buf += data
                    if b"\n" not in buf and len(buf) > MAX_LINE_BYTES:
                        log.warning(
                            "Bridge: line exceeded %d bytes with no newline; "
                            "dropping connection",
                            MAX_LINE_BYTES,
                        )
                        self._connected_event.clear()
                        return
                    while b"\n" in buf:
                        line, buf = buf.split(b"\n", 1)
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            obj = json.loads(line)
                            # Auto-reply to ping
                            if obj.get("type") == "ping":
                                self.send({"type": "pong"})
                            else:
                                self._recv_q.put(obj)
                        except json.JSONDecodeError:
                            log.warning("Bridge: invalid JSON: %s", line[:120])
            except (ConnectionResetError, OSError):
                self._connected_event.clear()
                return

    def _send_all(self, sock: socket.socket, data: bytes) -> None:
        """Send all bytes on a non-blocking socket, tolerating transient
        back-pressure (BlockingIOError) instead of dropping the connection.

        On a non-blocking socket a full send buffer raises BlockingIOError
        (a subclass of OSError); the messages here are tiny and infrequent, so
        we wait briefly for writability and retry rather than tearing down the
        link. A real error (BrokenPipe/ConnectionReset) still propagates, and a
        persistently un-writable socket times out and raises OSError so the
        caller reconnects."""
        view = memoryview(data)
        sent_total = 0
        deadline = time.monotonic() + 5.0
        while sent_total < len(data):
            try:
                sent = sock.send(view[sent_total:])
                if sent == 0:
                    raise OSError("Bridge: socket send returned 0")
                sent_total += sent
            except BlockingIOError:
                if time.monotonic() > deadline:
                    raise OSError("Bridge: send timed out (socket not writable)")
                select.select([], [sock], [], 1.0)

    def _close_conn(self) -> None:
        if self._conn_sock is not None:
            try:
                self._conn_sock.close()
            except OSError:
                pass
            self._conn_sock = None
        self._connected_event.clear()

    def _close_all(self) -> None:
        self._close_conn()
        if self._server_sock is not None:
            try:
                self._server_sock.close()
            except OSError:
                pass
            self._server_sock = None
