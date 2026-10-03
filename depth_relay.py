"""
Depth relay: stream depth frames to DuneBox (C++) over TCP.

DuneBox only talks to Kinect v1 and v2 natively. With the relay on, it can
use any sensor sandcam supports (Orbbec Femto, RealSense, ...) by setting
kinectVersion=4 in its settings: sandcam owns the sensor and DuneBox reads
the frames from here.

Protocol (little-endian), one message per frame:
    header  "DBD1", uint16 width, uint16 height, uint32 frame number,
            float32 sx, ax, sy, ay, uint32 flags
    payload width * height uint16 depth in millimetres (0 = no reading)
    then, if flags & 1, width * height * 3 bytes of RGB colour

(sx, ax, sy, ay) map a pixel to camera space: x_world = (sx * px + ax) * depth,
matching the affine world matrix DuneBox builds for the Kinect.

Colour is only sent while a client asks for it with the line "C1\n" (and
stopped with "C0\n"); DuneBox needs it for calibration only.

The sender always transmits the newest frame, so a slow client skips frames
rather than falling behind.
"""

from __future__ import annotations

import logging
import math
import select
import socket
import struct
import threading

import numpy as np

log = logging.getLogger(__name__)

MAGIC = b"DBD1"
HEADER = struct.Struct("<4sHHIffffI")
FLAG_COLOR = 1
RELAY_SIZE = (640, 480)
DEFAULT_PORT = 9877
MAX_CLIENTS = 2

# Depth field of view (horizontal, vertical) in degrees.
SENSOR_FOV = {
    "kinect_v1": (58.5, 45.6),
    "kinect_v2": (70.6, 60.0),
    "kinect_v2_sdk": (70.6, 60.0),
    "orbbec": (75.0, 65.0),
    "realsense": (87.0, 58.0),
}
DEFAULT_FOV = (70.0, 55.0)


def _resample(image: np.ndarray, size: tuple[int, int]) -> np.ndarray:
    w, h = size
    src_h, src_w = image.shape[:2]
    rows = (np.arange(h) * src_h // h).clip(0, src_h - 1)
    cols = (np.arange(w) * src_w // w).clip(0, src_w - 1)
    return image[rows[:, None], cols[None, :]]


def to_millimetres(
    frame: np.ndarray, min_mm: float, max_mm: float, size: tuple[int, int] = RELAY_SIZE
) -> np.ndarray:
    """Turn sandcam's normalized height map (1 = near) back into depth in mm."""
    sampled = _resample(frame, size)
    mm = max_mm - np.clip(sampled, 0.0, 1.0) * (max_mm - min_mm)
    return np.ascontiguousarray(np.rint(mm), dtype="<u2")


def to_rgb(color: np.ndarray, size: tuple[int, int] = RELAY_SIZE) -> np.ndarray:
    rgb = _resample(color, size)[:, :, :3]
    return np.ascontiguousarray(rgb, dtype=np.uint8)


def intrinsics(fov_deg: tuple[float, float], size: tuple[int, int] = RELAY_SIZE) -> tuple[float, float, float, float]:
    w, h = size
    tx = math.tan(math.radians(fov_deg[0]) / 2)
    ty = math.tan(math.radians(fov_deg[1]) / 2)
    return 2 * tx / w, -tx, 2 * ty / h, -ty


def encode(
    mm: np.ndarray,
    frame_no: int,
    intr: tuple[float, float, float, float],
    rgb: np.ndarray | None = None,
) -> bytes:
    h, w = mm.shape
    flags = FLAG_COLOR if rgb is not None else 0
    parts = [HEADER.pack(MAGIC, w, h, frame_no & 0xFFFFFFFF, *intr, flags),
             mm.astype("<u2", copy=False).tobytes()]
    if rgb is not None:
        parts.append(rgb.tobytes())
    return b"".join(parts)


class DepthRelay:
    """TCP server that hands the latest depth frame to connected clients."""

    def __init__(self, host: str = "127.0.0.1", port: int = DEFAULT_PORT) -> None:
        self.host = host
        self.port = port
        self._server: socket.socket | None = None
        self._clients: dict[socket.socket, bool] = {}  # socket -> wants colour
        self._lock = threading.Lock()
        self._wake = threading.Condition(self._lock)
        self._latest: bytes | None = None
        self._running = False
        self._threads: list[threading.Thread] = []
        self.frames_sent = 0
        self._frame_no = 0
        self.error = ""

    @property
    def running(self) -> bool:
        return self._running

    @property
    def client_count(self) -> int:
        with self._lock:
            return len(self._clients)

    @property
    def wants_color(self) -> bool:
        with self._lock:
            return any(self._clients.values())

    def start(self) -> bool:
        if self._running:
            return True
        try:
            server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            server.bind((self.host, self.port))
            server.listen(MAX_CLIENTS)
        except OSError as exc:
            self.error = f"Couldn't open port {self.port}: {exc.strerror or exc}"
            log.warning("Depth relay could not start: %s", exc)
            return False
        self.error = ""
        self.port = server.getsockname()[1]
        self._server = server
        self._running = True
        self._threads = [
            threading.Thread(target=self._listen_loop, name="depth-relay-listen", daemon=True),
            threading.Thread(target=self._send_loop, name="depth-relay-send", daemon=True),
        ]
        for t in self._threads:
            t.start()
        log.info("Depth relay listening on %s:%d", self.host, self.port)
        return True

    def stop(self) -> None:
        if not self._running:
            return
        with self._wake:
            self._running = False
            self._wake.notify_all()
        for t in self._threads:
            t.join(timeout=2)
        if self._server is not None:
            try:
                self._server.close()
            except OSError:
                pass
        with self._lock:
            for c in self._clients:
                try:
                    c.close()
                except OSError:
                    pass
            self._clients.clear()
            self._latest = None
        self._server = None

    def publish(
        self,
        frame: np.ndarray | None,
        min_mm: float,
        max_mm: float,
        sensor_type: str,
        color: np.ndarray | None = None,
    ) -> None:
        """Queue a frame for clients. Cheap when nobody is connected."""
        if not self._running or frame is None or self.client_count == 0:
            return
        mm = to_millimetres(frame, min_mm, max_mm)
        rgb = to_rgb(color) if color is not None and color.ndim == 3 else None
        self._frame_no += 1
        msg = encode(mm, self._frame_no, intrinsics(SENSOR_FOV.get(sensor_type, DEFAULT_FOV)), rgb)
        with self._wake:
            self._latest = msg
            self._wake.notify()

    def status(self) -> dict:
        return {
            "enabled": self._running,
            "port": self.port,
            "clients": self.client_count,
            "frames": self.frames_sent,
            "error": self.error,
        }

    def _drop(self, conn: socket.socket) -> None:
        with self._lock:
            known = self._clients.pop(conn, None) is not None
        try:
            conn.close()
        except OSError:
            pass
        if known:
            log.info("Depth relay client disconnected")

    def _listen_loop(self) -> None:
        """Accept clients and read their colour requests."""
        pending: dict[socket.socket, bytes] = {}
        while self._running:
            with self._lock:
                watched = [self._server, *self._clients]
            try:
                readable, _, _ = select.select(watched, [], [], 0.25)
            except (OSError, ValueError):
                continue
            for sock in readable:
                if sock is self._server:
                    try:
                        conn, addr = self._server.accept()
                    except OSError:
                        continue
                    with self._lock:
                        if len(self._clients) >= MAX_CLIENTS:
                            conn.close()
                            continue
                        conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                        conn.settimeout(2.0)
                        self._clients[conn] = False
                    log.info("Depth relay client connected from %s", addr[0])
                    continue
                try:
                    data = sock.recv(256)
                except OSError:
                    data = b""
                if not data:
                    pending.pop(sock, None)
                    self._drop(sock)
                    continue
                buf = pending.get(sock, b"") + data
                *lines, rest = buf.split(b"\n")
                pending[sock] = rest[-64:]
                for line in lines:
                    if line.strip() in (b"C1", b"C0"):
                        with self._lock:
                            if sock in self._clients:
                                self._clients[sock] = line.strip() == b"C1"

    def _send_loop(self) -> None:
        while True:
            with self._wake:
                while self._running and self._latest is None:
                    self._wake.wait(0.5)
                if not self._running:
                    return
                msg, self._latest = self._latest, None
                clients = list(self._clients)
            for conn in clients:
                try:
                    conn.sendall(msg)
                except OSError:
                    self._drop(conn)
            self.frames_sent += 1
