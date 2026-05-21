"""
Pluggable depth sensor abstraction.

Supports multiple backends: KinectV1, KinectV2, Orbbec, RealSense, MouseSimulator.
Configure via sandcam-settings.json: {"sensor_type": "kinect_v1"}
"""

from __future__ import annotations

import logging
import math
import time
from abc import ABC, abstractmethod

import numpy as np

logger = logging.getLogger(__name__)

# ── Sensor type registry ─────────────────────────────────────────────────────

SENSOR_TYPES: dict[str, type[DepthSensor]] = {}


def _register(name: str):
    """Class decorator that adds a sensor to the type registry."""

    def _wrap(cls: type[DepthSensor]) -> type[DepthSensor]:
        SENSOR_TYPES[name] = cls
        return cls

    return _wrap


# ── Abstract base ─────────────────────────────────────────────────────────────


class DepthSensor(ABC):
    """Abstract depth sensor that all backends must implement."""

    # ── abstract interface ────────────────────────────────────────────────

    @abstractmethod
    def connect(self) -> bool:
        """Initialise the sensor. Return True on success."""
        ...

    @abstractmethod
    def disconnect(self) -> None:
        """Release hardware resources."""
        ...

    @abstractmethod
    def get_depth_frame(self) -> np.ndarray | None:
        """Return a normalised float32 height map (0.0–1.0), or None."""
        ...

    @abstractmethod
    def get_color_frame(self) -> np.ndarray | None:
        """Return an RGB frame if the sensor supports it, else None."""
        ...

    @abstractmethod
    def is_connected(self) -> bool:
        ...

    @abstractmethod
    def get_resolution(self) -> tuple[int, int]:
        """Return (width, height)."""
        ...

    @abstractmethod
    def get_sensor_name(self) -> str:
        ...

    @abstractmethod
    def get_sensor_info(self) -> dict:
        """Return diagnostics dict (name, resolution, status, …)."""
        ...

    # ── optional helpers (safe defaults) ──────────────────────────────────

    def get_frame(self) -> np.ndarray:
        """Backward-compatible alias for get_depth_frame()."""
        frame = self.get_depth_frame()
        if frame is None:
            w, h = self.get_resolution()
            return np.full((h, w), 0.5, dtype=np.float32)
        return frame

    def sculpt(self, cx: int, cy: int, radius: int, delta: float) -> None:
        """Brush-paint the depth map.  No-op for hardware sources."""

    def resize(self, width: int, height: int) -> None:
        """Resize the output frame dimensions.  No-op by default."""

    def reset(self) -> None:
        """Reset terrain to default.  No-op by default."""

    def set_depth_range(self, min_mm: int, max_mm: int) -> None:
        """Update depth calibration.  No-op by default."""

    def set_filter_params(
        self,
        *,
        temporal_alpha: float,
        change_threshold_mm: int,
        persistence_frames: int,
        foreground_reject_mm: int,
    ) -> None:
        """Update temporal filtering settings.  No-op by default."""

    def close(self) -> None:
        """Convenience wrapper around disconnect()."""
        self.disconnect()

    def __enter__(self) -> DepthSensor:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


# ── Kinect V1 ─────────────────────────────────────────────────────────────────


@_register("kinect_v1")
class KinectV1Sensor(DepthSensor):
    """
    Kinect v1 depth sensor via libfreenect (ctypes).

    Loads freenect from a DLL next to this file (Windows) or the system
    linker (Linux / macOS).  Runs the freenect event loop in a background
    daemon thread.
    """

    _RESOLUTION_MEDIUM = 1
    _DEPTH_11BIT = 0
    _DEPTH_RAW_NO_DATA = 2047
    _DEVICE_CAMERA = 0x02
    _LOG_FATAL = 0
    _LOG_ERROR = 1

    def __init__(
        self,
        width: int = 640,
        height: int = 480,
        min_depth_mm: int = 400,
        max_depth_mm: int = 1100,
        device_index: int = 0,
        temporal_alpha: float = 0.35,
        change_threshold_mm: int = 35,
        persistence_frames: int = 4,
        foreground_reject_mm: int = 120,
        quiet_native_logs: bool = True,
    ) -> None:
        self._out_width = width
        self._out_height = height
        self._min = float(min_depth_mm)
        self._max = float(max_depth_mm)
        self._device_index = device_index
        self._temporal_alpha = float(np.clip(temporal_alpha, 0.01, 1.0))
        self._change_threshold_mm = float(max(1, change_threshold_mm))
        self._persistence_frames = max(1, int(persistence_frames))
        self._foreground_reject_mm = float(max(0, foreground_reject_mm))
        self._quiet_native_logs = quiet_native_logs

        self._connected = False
        self._running = False
        self._closed = False

        import threading

        self._lock = threading.Lock()
        self._latest = np.full((height, width), 0.5, dtype=np.float32)
        self._stable_raw: np.ndarray | None = None
        self._candidate_raw: np.ndarray | None = None
        self._candidate_age: np.ndarray | None = None

        # Populated by connect()
        self._lib = None
        self._ctx = None
        self._dev = None
        self._cb = None
        self._log_cb = None
        self._thread = None

    # ── DepthSensor interface ─────────────────────────────────────────────

    def connect(self) -> bool:
        if self._connected:
            return True

        import ctypes
        import ctypes.util
        import os
        import pathlib
        import sys
        import threading

        dll_dir = pathlib.Path(__file__).parent

        if sys.platform == "win32":
            os.add_dll_directory(str(dll_dir))
            lib_path = str(dll_dir / "freenect.dll")
        else:
            found = ctypes.util.find_library("freenect")
            if not found:
                raise RuntimeError(
                    "libfreenect not found. "
                    "On Debian/Ubuntu: apt install libfreenect-dev"
                )
            lib_path = found

        try:
            lib = ctypes.CDLL(lib_path)
        except OSError as exc:
            raise RuntimeError(
                f"Cannot load libfreenect from {lib_path}.\n"
                "Windows: ensure freenect.dll + libusb-1.0.dll are next to this file.\n"
                "Linux:   apt install libfreenect-dev\n"
                f"Original error: {exc}"
            ) from exc

        # ── struct ────────────────────────────────────────────────────────
        class _FrameMode(ctypes.Structure):
            _fields_ = [
                ("reserved", ctypes.c_uint32),
                ("resolution", ctypes.c_int32),
                ("format", ctypes.c_int32),
                ("bytes", ctypes.c_int32),
                ("width", ctypes.c_int16),
                ("height", ctypes.c_int16),
                ("data_bpp", ctypes.c_int8),
                ("pad_bpp", ctypes.c_int8),
                ("framerate", ctypes.c_int8),
                ("is_valid", ctypes.c_int8),
            ]

        # ── API signatures ────────────────────────────────────────────────
        lib.freenect_init.restype = ctypes.c_int
        lib.freenect_init.argtypes = [
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.c_void_p,
        ]
        lib.freenect_shutdown.restype = ctypes.c_int
        lib.freenect_shutdown.argtypes = [ctypes.c_void_p]
        lib.freenect_set_log_level.restype = None
        lib.freenect_set_log_level.argtypes = [ctypes.c_void_p, ctypes.c_int]
        _LogCB = ctypes.CFUNCTYPE(
            None, ctypes.c_void_p, ctypes.c_int, ctypes.c_char_p
        )
        lib.freenect_set_log_callback.restype = None
        lib.freenect_set_log_callback.argtypes = [ctypes.c_void_p, _LogCB]
        lib.freenect_select_subdevices.restype = None
        lib.freenect_select_subdevices.argtypes = [
            ctypes.c_void_p,
            ctypes.c_int,
        ]
        lib.freenect_open_device.restype = ctypes.c_int
        lib.freenect_open_device.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.c_int,
        ]
        lib.freenect_close_device.restype = ctypes.c_int
        lib.freenect_close_device.argtypes = [ctypes.c_void_p]
        lib.freenect_find_depth_mode.restype = _FrameMode
        lib.freenect_find_depth_mode.argtypes = [ctypes.c_int, ctypes.c_int]
        lib.freenect_set_depth_mode.restype = ctypes.c_int
        lib.freenect_set_depth_mode.argtypes = [ctypes.c_void_p, _FrameMode]
        _DepthCB = ctypes.CFUNCTYPE(
            None, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint32
        )
        lib.freenect_set_depth_callback.restype = None
        lib.freenect_set_depth_callback.argtypes = [ctypes.c_void_p, _DepthCB]
        lib.freenect_start_depth.restype = ctypes.c_int
        lib.freenect_start_depth.argtypes = [ctypes.c_void_p]
        lib.freenect_stop_depth.restype = ctypes.c_int
        lib.freenect_stop_depth.argtypes = [ctypes.c_void_p]
        lib.freenect_process_events.restype = ctypes.c_int
        lib.freenect_process_events.argtypes = [ctypes.c_void_p]

        # ── init ──────────────────────────────────────────────────────────
        ctx = ctypes.c_void_p()
        if lib.freenect_init(ctypes.byref(ctx), None) != 0:
            raise RuntimeError("freenect_init failed")

        lib.freenect_select_subdevices(ctx, self._DEVICE_CAMERA)

        dev = ctypes.c_void_p()
        if (
            lib.freenect_open_device(
                ctx, ctypes.byref(dev), self._device_index
            )
            != 0
        ):
            lib.freenect_shutdown(ctx)
            raise RuntimeError(
                f"freenect_open_device({self._device_index}) failed — "
                "is the Kinect plugged in and using the WinUSB driver (Zadig)?"
            )

        mode = lib.freenect_find_depth_mode(
            self._RESOLUTION_MEDIUM, self._DEPTH_11BIT
        )
        if not mode.is_valid:
            raise RuntimeError("Could not find 640×480 11-bit depth mode")
        lib.freenect_set_depth_mode(dev, mode)

        self._lib = lib
        self._ctx = ctx
        self._dev = dev
        self._running = True

        if self._quiet_native_logs:
            self._log_cb = _LogCB(lambda _d, _l, _m: None)
            lib.freenect_set_log_level(ctx, self._LOG_FATAL)
            lib.freenect_set_log_callback(ctx, self._log_cb)
        else:
            lib.freenect_set_log_level(ctx, self._LOG_ERROR)

        self._cb = _DepthCB(self._on_depth)
        lib.freenect_set_depth_callback(dev, self._cb)
        lib.freenect_start_depth(dev)

        self._thread = threading.Thread(target=self._event_loop, daemon=True)
        self._thread.start()
        self._connected = True
        logger.info("Kinect V1 connected (device %d)", self._device_index)
        return True

    def disconnect(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._running = False
        self._connected = False
        try:
            if self._dev:
                self._lib.freenect_stop_depth(self._dev)
        except Exception:
            pass
        try:
            if self._dev:
                self._lib.freenect_close_device(self._dev)
        except Exception:
            pass
        try:
            if self._ctx:
                self._lib.freenect_shutdown(self._ctx)
        except Exception:
            pass
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=1.0)
        self._dev = None
        self._ctx = None
        logger.info("Kinect V1 disconnected")

    def get_depth_frame(self) -> np.ndarray | None:
        with self._lock:
            return self._latest.copy()

    def get_color_frame(self) -> np.ndarray | None:
        return None  # Kinect V1 colour not wired up yet

    def is_connected(self) -> bool:
        return self._connected

    def get_resolution(self) -> tuple[int, int]:
        return (self._out_width, self._out_height)

    def get_sensor_name(self) -> str:
        return "Kinect V1 (libfreenect)"

    def get_sensor_info(self) -> dict:
        return {
            "name": self.get_sensor_name(),
            "resolution": self.get_resolution(),
            "connected": self.is_connected(),
            "device_index": self._device_index,
            "depth_range_mm": (int(self._min), int(self._max)),
        }

    # ── extended methods used by main.py ──────────────────────────────────

    def set_depth_range(self, min_mm: int, max_mm: int) -> None:
        with self._lock:
            self._min = float(min_mm)
            self._max = float(max_mm)

    def set_filter_params(
        self,
        *,
        temporal_alpha: float,
        change_threshold_mm: int,
        persistence_frames: int,
        foreground_reject_mm: int,
    ) -> None:
        with self._lock:
            self._temporal_alpha = float(np.clip(temporal_alpha, 0.01, 1.0))
            self._change_threshold_mm = float(max(1, change_threshold_mm))
            self._persistence_frames = max(1, int(persistence_frames))
            self._foreground_reject_mm = float(max(0, foreground_reject_mm))

    def resize(self, width: int, height: int) -> None:
        with self._lock:
            self._out_width = width
            self._out_height = height
            self._latest = np.full((height, width), 0.5, dtype=np.float32)

    # ── internals ─────────────────────────────────────────────────────────

    def _on_depth(self, _dev, data_ptr: int, _timestamp: int) -> None:
        if not data_ptr:
            return

        with self._lock:
            out_h = self._out_height
            out_w = self._out_width
            min_ = self._min
            max_ = self._max
            alpha = self._temporal_alpha
            threshold = self._change_threshold_mm
            persistence = self._persistence_frames
            reject_margin = self._foreground_reject_mm

        import ctypes

        raw = (
            np.frombuffer(
                (ctypes.c_uint16 * (480 * 640)).from_address(data_ptr),
                dtype=np.uint16,
            )
            .reshape(480, 640)
            .copy()
            .astype(np.float32)
        )

        if (
            self._stable_raw is None
            or self._candidate_raw is None
            or self._candidate_age is None
        ):
            baseline = raw.copy()
            baseline[
                (baseline == 0) | (baseline >= self._DEPTH_RAW_NO_DATA)
            ] = max_
            self._stable_raw = baseline
            self._candidate_raw = baseline.copy()
            self._candidate_age = np.zeros_like(baseline, dtype=np.uint8)

        stable_raw = self._stable_raw
        candidate_raw = self._candidate_raw
        candidate_age = self._candidate_age

        invalid = (raw == 0) | (raw >= self._DEPTH_RAW_NO_DATA)
        foreground = raw < max(1.0, min_ - reject_margin)
        raw[invalid | foreground] = stable_raw[invalid | foreground]

        delta = np.abs(raw - stable_raw)
        settled = delta <= threshold
        changed = ~settled

        if np.any(settled):
            stable_raw[settled] = (
                stable_raw[settled] * (1.0 - alpha) + raw[settled] * alpha
            )
            candidate_age[settled] = 0

        if np.any(changed):
            same_candidate = np.abs(raw - candidate_raw) <= threshold
            refresh = changed & ~same_candidate
            if np.any(refresh):
                candidate_raw[refresh] = raw[refresh]
                candidate_age[refresh] = 1

            persist = changed & same_candidate
            if np.any(persist):
                candidate_age[persist] = np.minimum(
                    candidate_age[persist] + 1, 255
                )

            confirmed = changed & (candidate_age >= persistence)
            if np.any(confirmed):
                stable_raw[confirmed] = (
                    stable_raw[confirmed] * (1.0 - alpha)
                    + candidate_raw[confirmed] * alpha
                )
                candidate_age[confirmed] = 0

        frame = np.clip(
            1.0 - (stable_raw - min_) / (max_ - min_),
            0.0,
            1.0,
        ).astype(np.float32)

        if frame.shape != (out_h, out_w):
            from scipy.ndimage import zoom

            frame = zoom(frame, (out_h / 480, out_w / 640), order=1).astype(
                np.float32
            )

        with self._lock:
            self._latest = frame

    def _event_loop(self) -> None:
        while self._running:
            rc = self._lib.freenect_process_events(self._ctx)
            if rc < 0:
                break


# ── Mouse simulator ───────────────────────────────────────────────────────────


@_register("mouse_simulator")
class MouseSimulatorSensor(DepthSensor):
    """Simulates depth via mouse sculpting — no hardware required."""

    DEFAULT_LEVEL = 0.45

    def __init__(self, width: int = 640, height: int = 480) -> None:
        self.width = width
        self.height = height
        self._map = np.full(
            (height, width), self.DEFAULT_LEVEL, dtype=np.float32
        )
        self._ys, self._xs = np.mgrid[0:height, 0:width]
        self._connected = False

    def connect(self) -> bool:
        self._connected = True
        return True

    def disconnect(self) -> None:
        self._connected = False

    def get_depth_frame(self) -> np.ndarray | None:
        return self._map.copy()

    def get_color_frame(self) -> np.ndarray | None:
        return None

    def is_connected(self) -> bool:
        return self._connected

    def get_resolution(self) -> tuple[int, int]:
        return (self.width, self.height)

    def get_sensor_name(self) -> str:
        return "Mouse Simulator"

    def get_sensor_info(self) -> dict:
        return {
            "name": self.get_sensor_name(),
            "resolution": self.get_resolution(),
            "connected": self.is_connected(),
        }

    # ── sculpting / resize ────────────────────────────────────────────────

    def sculpt(self, cx: int, cy: int, radius: int, delta: float) -> None:
        from scipy.ndimage import gaussian_filter

        sigma = radius / 2.5
        dist_sq = (self._xs - cx) ** 2 + (self._ys - cy) ** 2
        brush = np.exp(-dist_sq / (2.0 * sigma**2)).astype(np.float32)
        brush[dist_sq > radius**2] = 0.0
        self._map += brush * delta
        np.clip(self._map, 0.0, 1.0, out=self._map)
        self._map = gaussian_filter(self._map, sigma=1.0).astype(np.float32)

    def reset(self) -> None:
        self._map[:] = self.DEFAULT_LEVEL

    def resize(self, width: int, height: int) -> None:
        from scipy.ndimage import zoom as _zoom

        if (height, width) == self._map.shape:
            return
        zy = height / self._map.shape[0]
        zx = width / self._map.shape[1]
        self._map = _zoom(self._map, (zy, zx), order=1).astype(np.float32)
        self.width = width
        self.height = height
        self._ys, self._xs = np.mgrid[0:height, 0:width]


# ── Dummy / procedural terrain ────────────────────────────────────────────────


@_register("dummy")
class DummySensor(DepthSensor):
    """Generates procedural terrain for testing without any hardware."""

    def __init__(self, width: int = 640, height: int = 480) -> None:
        self.width = width
        self.height = height
        self._connected = False
        self._terrain = self._generate_terrain(width, height)

    @staticmethod
    def _generate_terrain(w: int, h: int) -> np.ndarray:
        """Build a multi-octave simplex-ish noise terrain."""
        xs = np.linspace(0, 4 * math.pi, w, dtype=np.float32)
        ys = np.linspace(0, 4 * math.pi, h, dtype=np.float32)
        xg, yg = np.meshgrid(xs, ys)

        terrain = (
            0.5
            + 0.25 * np.sin(xg) * np.cos(yg)
            + 0.15 * np.sin(2.3 * xg + 0.7) * np.cos(1.7 * yg + 1.1)
            + 0.10 * np.sin(4.1 * xg + 2.0) * np.cos(3.3 * yg + 0.5)
        )
        return np.clip(terrain, 0.0, 1.0).astype(np.float32)

    def connect(self) -> bool:
        self._connected = True
        return True

    def disconnect(self) -> None:
        self._connected = False

    def get_depth_frame(self) -> np.ndarray | None:
        t = time.monotonic() * 0.3
        shift = int(t * 5) % self.width
        return np.roll(self._terrain, shift, axis=1).copy()

    def get_color_frame(self) -> np.ndarray | None:
        return None

    def is_connected(self) -> bool:
        return self._connected

    def get_resolution(self) -> tuple[int, int]:
        return (self.width, self.height)

    def get_sensor_name(self) -> str:
        return "Dummy (procedural terrain)"

    def get_sensor_info(self) -> dict:
        return {
            "name": self.get_sensor_name(),
            "resolution": self.get_resolution(),
            "connected": self.is_connected(),
        }

    def resize(self, width: int, height: int) -> None:
        if (width, height) == (self.width, self.height):
            return
        self.width = width
        self.height = height
        self._terrain = self._generate_terrain(width, height)


# ── Kinect V2 stub ────────────────────────────────────────────────────────────


@_register("kinect_v2")
class KinectV2Sensor(DepthSensor):
    """Kinect V2 via pylibfreenect2 — stub, not yet implemented."""

    def __init__(self, **kwargs) -> None:
        self._check_import()
        self._connected = False

    @staticmethod
    def _check_import() -> None:
        try:
            import pylibfreenect2  # noqa: F401
        except ImportError as exc:
            raise ImportError(
                "Kinect V2 support requires pylibfreenect2.\n"
                "Install it with:  pip install pylibfreenect2\n"
                "See: https://github.com/r9y9/pylibfreenect2"
            ) from exc

    def connect(self) -> bool:
        raise NotImplementedError("Kinect V2 backend is not yet implemented")

    def disconnect(self) -> None:
        self._connected = False

    def get_depth_frame(self) -> np.ndarray | None:
        return None

    def get_color_frame(self) -> np.ndarray | None:
        return None

    def is_connected(self) -> bool:
        return self._connected

    def get_resolution(self) -> tuple[int, int]:
        return (512, 424)

    def get_sensor_name(self) -> str:
        return "Kinect V2 (pylibfreenect2)"

    def get_sensor_info(self) -> dict:
        return {
            "name": self.get_sensor_name(),
            "resolution": self.get_resolution(),
            "connected": False,
            "status": "stub — not yet implemented",
        }


# ── Orbbec stub ───────────────────────────────────────────────────────────────


@_register("orbbec")
class OrbbecSensor(DepthSensor):
    """Orbbec depth camera via pyorbbecsdk — stub, not yet implemented."""

    def __init__(self, **kwargs) -> None:
        self._check_import()
        self._connected = False

    @staticmethod
    def _check_import() -> None:
        try:
            import pyorbbecsdk  # noqa: F401
        except ImportError as exc:
            raise ImportError(
                "Orbbec support requires pyorbbecsdk.\n"
                "Install it with:  pip install pyorbbecsdk\n"
                "See: https://github.com/orbbec/pyorbbecsdk"
            ) from exc

    def connect(self) -> bool:
        raise NotImplementedError("Orbbec backend is not yet implemented")

    def disconnect(self) -> None:
        self._connected = False

    def get_depth_frame(self) -> np.ndarray | None:
        return None

    def get_color_frame(self) -> np.ndarray | None:
        return None

    def is_connected(self) -> bool:
        return self._connected

    def get_resolution(self) -> tuple[int, int]:
        return (640, 480)

    def get_sensor_name(self) -> str:
        return "Orbbec (pyorbbecsdk)"

    def get_sensor_info(self) -> dict:
        return {
            "name": self.get_sensor_name(),
            "resolution": self.get_resolution(),
            "connected": False,
            "status": "stub — not yet implemented",
        }


# ── RealSense stub ────────────────────────────────────────────────────────────


@_register("realsense")
class RealSenseSensor(DepthSensor):
    """Intel RealSense via pyrealsense2 — stub, not yet implemented."""

    def __init__(self, **kwargs) -> None:
        self._check_import()
        self._connected = False

    @staticmethod
    def _check_import() -> None:
        try:
            import pyrealsense2  # noqa: F401
        except ImportError as exc:
            raise ImportError(
                "RealSense support requires pyrealsense2.\n"
                "Install it with:  pip install pyrealsense2\n"
                "See: https://github.com/IntelRealSense/librealsense"
            ) from exc

    def connect(self) -> bool:
        raise NotImplementedError("RealSense backend is not yet implemented")

    def disconnect(self) -> None:
        self._connected = False

    def get_depth_frame(self) -> np.ndarray | None:
        return None

    def get_color_frame(self) -> np.ndarray | None:
        return None

    def is_connected(self) -> bool:
        return self._connected

    def get_resolution(self) -> tuple[int, int]:
        return (640, 480)

    def get_sensor_name(self) -> str:
        return "Intel RealSense (pyrealsense2)"

    def get_sensor_info(self) -> dict:
        return {
            "name": self.get_sensor_name(),
            "resolution": self.get_resolution(),
            "connected": False,
            "status": "stub — not yet implemented",
        }


# ── Factory ───────────────────────────────────────────────────────────────────


def create_sensor(config: dict, **kwargs) -> DepthSensor:
    """
    Create a depth sensor from a config dict.

    Expected keys (all optional):
        sensor_type     – one of: kinect_v1, kinect_v2, orbbec, realsense,
                          mouse_simulator, dummy  (default: kinect_v1)
        sensor_fallback – fallback type if the primary fails to connect
                          (default: mouse_simulator)

    Extra *kwargs* (width, height, min_depth_mm, …) are forwarded to
    the sensor constructor.
    """
    sensor_type = config.get("sensor_type", "kinect_v1")
    fallback = config.get("sensor_fallback", "mouse_simulator")

    sensor = _try_create(sensor_type, kwargs)
    if sensor is not None:
        return sensor

    if fallback and fallback != sensor_type:
        logger.warning(
            "Primary sensor '%s' unavailable, falling back to '%s'",
            sensor_type,
            fallback,
        )
        sensor = _try_create(fallback, kwargs)
        if sensor is not None:
            return sensor

    logger.warning("All sensor backends failed — using MouseSimulator")
    sim = MouseSimulatorSensor(
        width=kwargs.get("width", 640), height=kwargs.get("height", 480)
    )
    sim.connect()
    return sim


def _try_create(
    sensor_type: str, kwargs: dict
) -> DepthSensor | None:
    cls = SENSOR_TYPES.get(sensor_type)
    if cls is None:
        logger.error("Unknown sensor type: '%s'", sensor_type)
        return None

    try:
        sensor = cls(**kwargs)
        sensor.connect()
        return sensor
    except (ImportError, NotImplementedError) as exc:
        logger.warning("Cannot use %s: %s", sensor_type, exc)
        return None
    except Exception:
        logger.exception("Failed to create sensor '%s'", sensor_type)
        return None
