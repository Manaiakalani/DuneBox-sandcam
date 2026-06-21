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

    def __init__(self, width: int = 640, height: int = 480, **_kwargs) -> None:
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

    def __init__(self, width: int = 640, height: int = 480, **_kwargs) -> None:
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
    """
    Kinect V2 (Xbox One) depth sensor via pylibfreenect2.

    Native depth resolution: 512×424, range 0–4500 mm.
    Requires libfreenect2 installed on the system plus the Python bindings.
    """

    _NATIVE_W, _NATIVE_H = 512, 424
    _MAX_DEPTH_MM = 4500.0

    def __init__(
        self,
        width: int = 512,
        height: int = 424,
        min_depth_mm: int = 400,
        max_depth_mm: int = 4500,
        device_index: int = 0,
        pipeline: str = "auto",
        **_kwargs,
    ) -> None:
        self._check_import()
        self._out_width = width
        self._out_height = height
        self._min = float(min_depth_mm)
        self._max = float(max_depth_mm)
        self._device_index = device_index
        self._pipeline_type = pipeline
        self._connected = False

        import threading

        self._lock = threading.Lock()
        self._latest_depth: np.ndarray | None = None
        self._latest_color: np.ndarray | None = None

        self._fn2 = None
        self._device = None
        self._listener = None
        self._registration = None
        self._pipeline = None

    @staticmethod
    def _check_import() -> None:
        try:
            import pylibfreenect2  # noqa: F401
        except ImportError as exc:
            raise ImportError(
                "Kinect V2 support requires pylibfreenect2.\n"
                "Install:  pip install pylibfreenect2\n"
                "Also requires libfreenect2 system library:\n"
                "  macOS:   brew install libfreenect2\n"
                "  Ubuntu:  see https://github.com/OpenKinect/libfreenect2#linux\n"
                "  Windows: download from https://github.com/OpenKinect/libfreenect2/releases\n"
                "Docs: https://github.com/r9y9/pylibfreenect2"
            ) from exc

    def connect(self) -> bool:
        if self._connected:
            return True

        import pylibfreenect2 as fn2

        self._fn2 = fn2
        freenect2 = fn2.Freenect2()
        num_devices = freenect2.enumerateDevices()
        if num_devices == 0:
            raise RuntimeError(
                "No Kinect V2 devices found. Check USB 3.0 connection."
            )
        if self._device_index >= num_devices:
            raise RuntimeError(
                f"Kinect V2 device index {self._device_index} out of range "
                f"(found {num_devices} device(s))"
            )

        serial = freenect2.getDeviceSerialNumber(self._device_index)
        logger.info("Opening Kinect V2 serial=%s", serial)

        # Select pipeline: prefer OpenGL, fall back to CPU
        if self._pipeline_type == "opengl":
            pipeline = fn2.OpenGLPacketPipeline()
        elif self._pipeline_type == "cpu":
            pipeline = fn2.CpuPacketPipeline()
        else:
            try:
                pipeline = fn2.OpenGLPacketPipeline()
            except Exception:
                logger.info("OpenGL pipeline unavailable, using CPU pipeline")
                pipeline = fn2.CpuPacketPipeline()

        self._pipeline = pipeline
        device = freenect2.openDevice(serial, pipeline=pipeline)

        types = fn2.FrameType.Color | fn2.FrameType.Ir | fn2.FrameType.Depth
        listener = fn2.SyncMultiFrameListener(types)
        device.setColorFrameListener(listener)
        device.setIrAndDepthFrameListener(listener)
        device.start()

        registration = fn2.Registration(
            device.getIrCameraParams(), device.getColorCameraParams()
        )

        self._device = device
        self._listener = listener
        self._registration = registration
        self._freenect2 = freenect2
        self._connected = True
        logger.info("Kinect V2 connected (512×424 depth)")
        return True

    def disconnect(self) -> None:
        if not self._connected:
            return
        self._connected = False
        try:
            if self._device is not None:
                self._device.stop()
                self._device.close()
        except Exception:
            pass
        self._device = None
        self._listener = None
        self._registration = None
        logger.info("Kinect V2 disconnected")

    def get_depth_frame(self) -> np.ndarray | None:
        if not self._connected or self._listener is None:
            return None

        fn2 = self._fn2
        frames = self._listener.waitForNewFrame()
        try:
            depth_frame = frames[fn2.FrameType.Depth]
            depth = depth_frame.asarray(np.float32).copy()  # (424, 512) mm
        finally:
            self._listener.release(frames)

        # Clamp to configured range and normalise to 0.0–1.0
        # Invert: close = high terrain, far = low terrain
        # 0 / non-finite = "no data" -> treat as far (lowest terrain) so sensor
        # holes don't render as spurious peaks.
        depth[~np.isfinite(depth) | (depth <= 0)] = self._max
        depth = np.clip(depth, self._min, self._max)
        normalised = 1.0 - (depth - self._min) / (self._max - self._min)
        normalised = normalised.astype(np.float32)

        if normalised.shape != (self._out_height, self._out_width):
            from scipy.ndimage import zoom

            zy = self._out_height / normalised.shape[0]
            zx = self._out_width / normalised.shape[1]
            normalised = zoom(normalised, (zy, zx), order=1).astype(
                np.float32
            )

        with self._lock:
            self._latest_depth = normalised
        return normalised

    def get_color_frame(self) -> np.ndarray | None:
        if not self._connected or self._listener is None:
            return None

        fn2 = self._fn2
        frames = self._listener.waitForNewFrame()
        try:
            color_frame = frames[fn2.FrameType.Color]
            depth_frame = frames[fn2.FrameType.Depth]

            undistorted = fn2.Frame(
                self._NATIVE_W, self._NATIVE_H, 4, fn2.FrameType.Depth
            )
            registered = fn2.Frame(
                self._NATIVE_W, self._NATIVE_H, 4, fn2.FrameType.Color
            )
            self._registration.apply(
                color_frame, depth_frame, undistorted, registered
            )
            color = registered.asarray(np.uint8)[:, :, :3].copy()  # BGR→RGB
        finally:
            self._listener.release(frames)

        return color

    def is_connected(self) -> bool:
        return self._connected

    def get_resolution(self) -> tuple[int, int]:
        return (self._out_width, self._out_height)

    def get_sensor_name(self) -> str:
        return "Kinect V2 (pylibfreenect2)"

    def get_sensor_info(self) -> dict:
        return {
            "name": self.get_sensor_name(),
            "resolution": self.get_resolution(),
            "connected": self.is_connected(),
            "depth_range_mm": (int(self._min), int(self._max)),
            "pipeline": self._pipeline_type,
        }

    def set_depth_range(self, min_mm: int, max_mm: int) -> None:
        with self._lock:
            self._min = float(min_mm)
            self._max = float(max_mm)

    def resize(self, width: int, height: int) -> None:
        with self._lock:
            self._out_width = width
            self._out_height = height


# ── Orbbec stub ───────────────────────────────────────────────────────────────


@_register("orbbec")
class OrbbecSensor(DepthSensor):
    """
    Orbbec depth camera via pyorbbecsdk.

    Supports Femto Bolt (Azure Kinect compatible), Astra, Gemini, etc.
    Alternative: pyk4a can be used for Femto Bolt via Azure Kinect SDK.
    """

    def __init__(
        self,
        width: int = 640,
        height: int = 576,
        min_depth_mm: int = 250,
        max_depth_mm: int = 5460,
        device_index: int = 0,
        use_pyk4a: bool = False,
        **_kwargs,
    ) -> None:
        self._use_pyk4a = use_pyk4a
        if use_pyk4a:
            self._check_pyk4a()
        else:
            self._check_import()
        self._out_width = width
        self._out_height = height
        self._min = float(min_depth_mm)
        self._max = float(max_depth_mm)
        self._device_index = device_index
        self._connected = False

        import threading

        self._lock = threading.Lock()

        # pyorbbecsdk handles
        self._pipeline = None
        self._config = None
        self._device = None
        self._device_name = "Orbbec"

        # pyk4a handles (alternative for Femto Bolt)
        self._k4a = None

    @staticmethod
    def _check_import() -> None:
        try:
            import pyorbbecsdk  # noqa: F401
        except ImportError as exc:
            raise ImportError(
                "Orbbec support requires pyorbbecsdk.\n"
                "Install:  pip install pyorbbecsdk\n"
                "Docs: https://github.com/orbbec/pyorbbecsdk\n\n"
                "Alternative for Femto Bolt: use pyk4a (Azure Kinect SDK)\n"
                "  pip install pyk4a\n"
                "  Set sensor_type='orbbec' and use_pyk4a=true in config"
            ) from exc

    @staticmethod
    def _check_pyk4a() -> None:
        try:
            import pyk4a  # noqa: F401
        except ImportError as exc:
            raise ImportError(
                "pyk4a backend requires the pyk4a package.\n"
                "Install:  pip install pyk4a\n"
                "Also requires Azure Kinect SDK:\n"
                "  https://learn.microsoft.com/azure/kinect-dk/sensor-sdk-download\n"
                "Note: The Orbbec Femto Bolt is compatible with Azure Kinect SDK."
            ) from exc

    def connect(self) -> bool:
        if self._connected:
            return True

        if self._use_pyk4a:
            return self._connect_pyk4a()
        return self._connect_orbbec()

    def _connect_orbbec(self) -> bool:
        import pyorbbecsdk as ob

        ctx = ob.Context()
        device_list = ctx.query_devices()
        if device_list.get_count() == 0:
            raise RuntimeError(
                "No Orbbec devices found. Check USB connection."
            )
        if self._device_index >= device_list.get_count():
            raise RuntimeError(
                f"Orbbec device index {self._device_index} out of range "
                f"(found {device_list.get_count()} device(s))"
            )

        device = device_list.get_device_by_index(self._device_index)
        device_info = device.get_device_info()
        self._device_name = device_info.get_name()
        logger.info("Opening Orbbec device: %s", self._device_name)

        pipeline = ob.Pipeline(device)
        config = ob.Config()

        # Enable depth stream — use default profile (device picks best mode)
        depth_profiles = pipeline.get_stream_profile_list(
            ob.OBSensorType.DEPTH_SENSOR
        )
        depth_profile = depth_profiles.get_default_video_stream_profile()
        config.enable_stream(depth_profile)

        # Enable colour stream if available
        try:
            color_profiles = pipeline.get_stream_profile_list(
                ob.OBSensorType.COLOR_SENSOR
            )
            color_profile = color_profiles.get_default_video_stream_profile()
            config.enable_stream(color_profile)
        except Exception:
            logger.info("Orbbec colour stream not available on this device")

        pipeline.start(config)

        self._pipeline = pipeline
        self._config = config
        self._device = device
        self._ctx = ctx
        self._connected = True
        logger.info("Orbbec %s connected", self._device_name)
        return True

    def _connect_pyk4a(self) -> bool:
        from pyk4a import Config as K4AConfig
        from pyk4a import PyK4A

        k4a = PyK4A(
            K4AConfig(
                depth_mode=self._get_k4a_depth_mode(),
                color_resolution=self._get_k4a_color_res(),
            ),
            device_id=self._device_index,
        )
        k4a.start()
        self._k4a = k4a
        self._device_name = "Femto Bolt (pyk4a)"
        self._connected = True
        logger.info("Orbbec Femto Bolt connected via pyk4a")
        return True

    @staticmethod
    def _get_k4a_depth_mode():
        from pyk4a import DepthMode
        return DepthMode.NFOV_UNBINNED  # 640×576

    @staticmethod
    def _get_k4a_color_res():
        from pyk4a import ColorResolution
        return ColorResolution.RES_720P

    def disconnect(self) -> None:
        if not self._connected:
            return
        self._connected = False
        try:
            if self._pipeline is not None:
                self._pipeline.stop()
        except Exception:
            pass
        try:
            if self._k4a is not None:
                self._k4a.stop()
        except Exception:
            pass
        self._pipeline = None
        self._k4a = None
        self._device = None
        logger.info("Orbbec disconnected")

    def get_depth_frame(self) -> np.ndarray | None:
        if not self._connected:
            return None

        if self._use_pyk4a:
            return self._get_depth_pyk4a()
        return self._get_depth_orbbec()

    def _get_depth_orbbec(self) -> np.ndarray | None:
        frameset = self._pipeline.wait_for_frames(100)
        if frameset is None:
            return None

        depth_frame = frameset.get_depth_frame()
        if depth_frame is None:
            return None

        depth = np.frombuffer(
            depth_frame.get_data(), dtype=np.uint16
        ).reshape(depth_frame.get_height(), depth_frame.get_width())
        depth = depth.astype(np.float32)

        # 0 = "no data" -> treat as far so sensor holes aren't rendered as peaks.
        depth[depth <= 0] = self._max
        depth = np.clip(depth, self._min, self._max)
        normalised = 1.0 - (depth - self._min) / (self._max - self._min)
        normalised = normalised.astype(np.float32)

        if normalised.shape != (self._out_height, self._out_width):
            from scipy.ndimage import zoom

            zy = self._out_height / normalised.shape[0]
            zx = self._out_width / normalised.shape[1]
            normalised = zoom(normalised, (zy, zx), order=1).astype(
                np.float32
            )
        return normalised

    def _get_depth_pyk4a(self) -> np.ndarray | None:
        capture = self._k4a.get_capture()
        if capture.depth is None:
            return None

        depth = capture.depth.astype(np.float32)  # (H, W) in mm
        # 0 = "no data" -> treat as far so sensor holes aren't rendered as peaks.
        depth[depth <= 0] = self._max
        depth = np.clip(depth, self._min, self._max)
        normalised = 1.0 - (depth - self._min) / (self._max - self._min)
        normalised = normalised.astype(np.float32)

        if normalised.shape != (self._out_height, self._out_width):
            from scipy.ndimage import zoom

            zy = self._out_height / normalised.shape[0]
            zx = self._out_width / normalised.shape[1]
            normalised = zoom(normalised, (zy, zx), order=1).astype(
                np.float32
            )
        return normalised

    def get_color_frame(self) -> np.ndarray | None:
        if not self._connected:
            return None

        if self._use_pyk4a:
            capture = self._k4a.get_capture()
            if capture.color is None:
                return None
            return capture.color[:, :, :3].copy()  # BGRA → BGR → first 3 ch

        frameset = self._pipeline.wait_for_frames(100)
        if frameset is None:
            return None
        color_frame = frameset.get_color_frame()
        if color_frame is None:
            return None
        color = np.frombuffer(
            color_frame.get_data(), dtype=np.uint8
        ).reshape(color_frame.get_height(), color_frame.get_width(), -1)
        return color[:, :, :3].copy()

    def is_connected(self) -> bool:
        return self._connected

    def get_resolution(self) -> tuple[int, int]:
        return (self._out_width, self._out_height)

    def get_sensor_name(self) -> str:
        return f"Orbbec {self._device_name}"

    def get_sensor_info(self) -> dict:
        return {
            "name": self.get_sensor_name(),
            "resolution": self.get_resolution(),
            "connected": self.is_connected(),
            "depth_range_mm": (int(self._min), int(self._max)),
            "backend": "pyk4a" if self._use_pyk4a else "pyorbbecsdk",
        }

    def set_depth_range(self, min_mm: int, max_mm: int) -> None:
        with self._lock:
            self._min = float(min_mm)
            self._max = float(max_mm)

    def resize(self, width: int, height: int) -> None:
        with self._lock:
            self._out_width = width
            self._out_height = height


# ── RealSense stub ────────────────────────────────────────────────────────────


@_register("realsense")
class RealSenseSensor(DepthSensor):
    """
    Intel RealSense depth camera via pyrealsense2.

    Supports D400 series (D435, D435i, D415), L515, etc.
    Typical depth ranges: D435 0.1–10 m, L515 0.25–9 m.
    """

    def __init__(
        self,
        width: int = 640,
        height: int = 480,
        min_depth_mm: int = 100,
        max_depth_mm: int = 10000,
        device_index: int = 0,
        fps: int = 30,
        **_kwargs,
    ) -> None:
        self._check_import()
        self._out_width = width
        self._out_height = height
        self._min = float(min_depth_mm)
        self._max = float(max_depth_mm)
        self._device_index = device_index
        self._fps = fps
        self._connected = False

        import threading

        self._lock = threading.Lock()

        self._pipeline = None
        self._profile = None
        self._depth_scale = 1.0  # mm per depth unit
        self._device_name = "RealSense"

    @staticmethod
    def _check_import() -> None:
        try:
            import pyrealsense2  # noqa: F401
        except ImportError as exc:
            raise ImportError(
                "RealSense support requires pyrealsense2.\n"
                "Install:  pip install pyrealsense2\n"
                "Docs: https://github.com/IntelRealSense/librealsense\n"
                "Note: On ARM/macOS you may need to build from source."
            ) from exc

    def connect(self) -> bool:
        if self._connected:
            return True

        import pyrealsense2 as rs

        ctx = rs.context()
        devices = ctx.query_devices()
        if len(devices) == 0:
            raise RuntimeError(
                "No RealSense devices found. Check USB connection."
            )
        if self._device_index >= len(devices):
            raise RuntimeError(
                f"RealSense device index {self._device_index} out of range "
                f"(found {len(devices)} device(s))"
            )

        dev = devices[self._device_index]
        self._device_name = dev.get_info(rs.camera_info.name)
        serial = dev.get_info(rs.camera_info.serial_number)
        logger.info("Opening RealSense %s (serial=%s)", self._device_name, serial)

        pipeline = rs.pipeline()
        config = rs.config()
        config.enable_device(serial)

        # Detect native resolution from device product line
        depth_w, depth_h = self._out_width, self._out_height
        product_line = dev.get_info(rs.camera_info.product_line)
        if "L500" in product_line:
            depth_w, depth_h = 1024, 768
        elif "D400" in product_line:
            depth_w, depth_h = 1280, 720

        config.enable_stream(
            rs.stream.depth, depth_w, depth_h, rs.format.z16, self._fps
        )

        # Enable colour stream if available
        try:
            config.enable_stream(
                rs.stream.color, 640, 480, rs.format.bgr8, self._fps
            )
        except Exception:
            logger.info("RealSense colour stream not available")

        profile = pipeline.start(config)

        # Get depth scale (convert raw depth units to millimetres)
        depth_sensor = profile.get_device().first_depth_sensor()
        self._depth_scale = depth_sensor.get_depth_scale() * 1000.0  # to mm

        self._pipeline = pipeline
        self._profile = profile
        self._rs = rs
        self._connected = True
        logger.info(
            "RealSense %s connected (%dx%d depth)",
            self._device_name, depth_w, depth_h,
        )
        return True

    def disconnect(self) -> None:
        if not self._connected:
            return
        self._connected = False
        try:
            if self._pipeline is not None:
                self._pipeline.stop()
        except Exception:
            pass
        self._pipeline = None
        self._profile = None
        logger.info("RealSense disconnected")

    def get_depth_frame(self) -> np.ndarray | None:
        if not self._connected or self._pipeline is None:
            return None

        frames = self._pipeline.wait_for_frames(timeout_ms=5000)
        depth_frame = frames.get_depth_frame()
        if not depth_frame:
            return None

        depth = (
            np.asanyarray(depth_frame.get_data()).astype(np.float32)
            * self._depth_scale
        )  # now in mm

        # 0 / non-finite = "no data" -> treat as far so sensor holes aren't
        # rendered as spurious peaks.
        depth[~np.isfinite(depth) | (depth <= 0)] = self._max
        depth = np.clip(depth, self._min, self._max)
        normalised = 1.0 - (depth - self._min) / (self._max - self._min)
        normalised = normalised.astype(np.float32)

        if normalised.shape != (self._out_height, self._out_width):
            from scipy.ndimage import zoom

            zy = self._out_height / normalised.shape[0]
            zx = self._out_width / normalised.shape[1]
            normalised = zoom(normalised, (zy, zx), order=1).astype(
                np.float32
            )
        return normalised

    def get_color_frame(self) -> np.ndarray | None:
        if not self._connected or self._pipeline is None:
            return None

        frames = self._pipeline.wait_for_frames(timeout_ms=5000)
        color_frame = frames.get_color_frame()
        if not color_frame:
            return None

        return np.asanyarray(color_frame.get_data()).copy()

    def is_connected(self) -> bool:
        return self._connected

    def get_resolution(self) -> tuple[int, int]:
        return (self._out_width, self._out_height)

    def get_sensor_name(self) -> str:
        return f"Intel {self._device_name}"

    def get_sensor_info(self) -> dict:
        return {
            "name": self.get_sensor_name(),
            "resolution": self.get_resolution(),
            "connected": self.is_connected(),
            "depth_range_mm": (int(self._min), int(self._max)),
            "depth_scale_mm": self._depth_scale,
        }

    def set_depth_range(self, min_mm: int, max_mm: int) -> None:
        with self._lock:
            self._min = float(min_mm)
            self._max = float(max_mm)

    def resize(self, width: int, height: int) -> None:
        with self._lock:
            self._out_width = width
            self._out_height = height


# ── Factory ───────────────────────────────────────────────────────────────────


def create_sensor(config: dict, **kwargs) -> DepthSensor:
    """
    Create a depth sensor from a config dict.

    Expected keys (all optional):
        sensor_type     – one of: kinect_v1, kinect_v2, kinect_v2_sdk, orbbec,
                          realsense, mouse_simulator, dummy  (default: kinect_v1)
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


# ── Kinect V2 via the official Kinect for Windows SDK (pykinect2) ───────────────
#
# This is a Windows-only backend that talks to the Xbox One / Kinect v2 sensor
# through Microsoft's "Kinect for Windows SDK 2.0" using the pure-Python
# `pykinect2` bindings (no native compilation required, unlike `pylibfreenect2`
# used by the KinectV2Sensor backend above).
#
# Requirements (one-time, manual):
#   1. pip install pykinect2 comtypes      (into this venv)
#   2. Install the "Kinect for Windows SDK 2.0" *or* the "Kinect for Windows
#      Runtime 2.0" from Microsoft — this provides the USB driver and
#      Kinect20.dll.  Download:
#        https://www.microsoft.com/en-us/download/details.aspx?id=44561  (SDK)
#        https://www.microsoft.com/en-us/download/details.aspx?id=44559  (Runtime)
#
# pykinect2 0.1.0 ships codegen that only works on 32-bit Python and an ancient
# comtypes; `_patch_pykinect2()` below transparently repairs both issues so the
# bindings import on modern 64-bit Python 3.x.


def _patch_pykinect2() -> bool:
    """Idempotently fix the two well-known pykinect2 import-time bugs on
    64-bit / modern-comtypes Python.  Returns True if a file was rewritten."""
    import importlib.util
    import pathlib

    spec = importlib.util.find_spec("pykinect2")
    if spec is None or not spec.submodule_search_locations:
        return False
    pkg = pathlib.Path(spec.submodule_search_locations[0])
    pv = pkg / "PyKinectV2.py"
    if not pv.exists():
        return False
    patched = False

    src = pv.read_text(encoding="utf-8", errors="ignore")
    new = src
    # (1) 64-bit struct size: tagSTATSTG is 80 bytes on x64, not the hardcoded 72.
    new = new.replace(
        "assert sizeof(tagSTATSTG) == 72, sizeof(tagSTATSTG)",
        "assert sizeof(tagSTATSTG) in (72, 80), sizeof(tagSTATSTG)",
    )
    # (2) ancient comtypes version sentinel that modern comtypes rejects.
    #     Guard against re-wrapping: only patch the bare, unwrapped call.
    if (
        "from comtypes import _check_version; _check_version('')" in new
        and "try:\n    from comtypes import _check_version; _check_version('')"
        not in new
    ):
        new = new.replace(
            "from comtypes import _check_version; _check_version('')",
            "try:\n    from comtypes import _check_version; _check_version('')\n"
            "except Exception:\n    pass  # pykinect2 codegen predates modern comtypes",
        )
    if new != src:
        pv.write_text(new, encoding="utf-8")
        logger.info("Patched pykinect2 for 64-bit / modern comtypes compatibility")
        patched = True

    # (3) time.clock() was removed in Python 3.8+ -> use perf_counter.
    pr = pkg / "PyKinectRuntime.py"
    if pr.exists():
        rsrc = pr.read_text(encoding="utf-8", errors="ignore")
        rnew = rsrc.replace("time.clock(", "time.perf_counter(")
        if rnew != rsrc:
            pr.write_text(rnew, encoding="utf-8")
            logger.info("Patched pykinect2 PyKinectRuntime for Python 3.8+ (time.clock)")
            patched = True

    return patched


def _import_pykinect2():
    """Import pykinect2, applying compatibility patches and retrying once.

    Raises ImportError if pykinect2/comtypes are missing or if the Kinect for
    Windows SDK/Runtime (Kinect20.dll) is not installed, so the sensor factory
    can fall back cleanly.
    """
    import importlib.util
    import sys

    if importlib.util.find_spec("pykinect2") is None:
        raise ImportError(
            "Kinect V2 (SDK) support requires the pykinect2 bindings.\n"
            "Install:  pip install pykinect2 comtypes"
        )

    # Proactively repair the known pykinect2 incompatibilities (64-bit struct
    # sizes, ancient comtypes check, and time.clock() removed in Python 3.8+)
    # before importing.  The time.clock() bug only surfaces at runtime, not at
    # import, so an on-error-only patch would miss it.
    _patch_pykinect2()

    def _do_import():
        from pykinect2 import PyKinectV2, PyKinectRuntime  # noqa: F401

        return PyKinectV2, PyKinectRuntime

    try:
        return _do_import()
    except (AssertionError, ImportError) as exc:
        # Safety net: if a patch didn't take (e.g. file perms), try once more.
        if isinstance(exc, ImportError) and "pykinect2" in str(exc).lower():
            raise ImportError(
                "Kinect V2 (SDK) support requires the pykinect2 bindings.\n"
                "Install:  pip install pykinect2 comtypes"
            ) from exc
        if not _patch_pykinect2():
            raise ImportError(
                "Kinect V2 (SDK) support requires the pykinect2 bindings.\n"
                "Install:  pip install pykinect2 comtypes"
            ) from exc
        import importlib

        importlib.invalidate_caches()
        for mod in [m for m in sys.modules if m.startswith("pykinect2")]:
            del sys.modules[mod]
        try:
            return _do_import()
        except (OSError, ImportError) as exc2:
            raise _sdk_missing_error(exc2) from exc2
    except OSError as exc:
        # ctypes.WinDLL('Kinect20') failed -> SDK/Runtime not installed.
        raise _sdk_missing_error(exc) from exc


def _sdk_missing_error(cause: Exception) -> ImportError:
    return ImportError(
        "Kinect V2 sensor found but the 'Kinect for Windows SDK/Runtime 2.0' "
        "is not installed (could not load Kinect20.dll).\n"
        "Install the driver+runtime from Microsoft, then re-launch:\n"
        "  SDK:     https://www.microsoft.com/en-us/download/details.aspx?id=44561\n"
        "  Runtime: https://www.microsoft.com/en-us/download/details.aspx?id=44559\n"
        f"(underlying error: {cause})"
    )


@_register("kinect_v2_sdk")
class KinectV2SdkSensor(DepthSensor):
    """
    Kinect V2 (Xbox One) depth sensor via the official Kinect for Windows SDK
    using the pure-Python ``pykinect2`` bindings.  Windows-only.

    Native depth: 512×424, range ~500–4500 mm, 0 = no data.
    """

    _NATIVE_W, _NATIVE_H = 512, 424

    def __init__(
        self,
        width: int = 512,
        height: int = 424,
        min_depth_mm: int = 500,
        max_depth_mm: int = 1500,
        temporal_alpha: float = 0.5,
        **_kwargs,
    ) -> None:
        import sys

        if not sys.platform.startswith("win"):
            raise NotImplementedError(
                "kinect_v2_sdk backend is Windows-only "
                "(requires the Kinect for Windows SDK)."
            )
        self._out_width = int(width)
        self._out_height = int(height)
        self._min = float(min_depth_mm)
        self._max = float(max_depth_mm)
        self._alpha = float(temporal_alpha)
        self._connected = False

        import threading

        self._lock = threading.Lock()
        self._pk2 = None
        self._runtime_mod = None
        self._kinect = None
        self._ema: np.ndarray | None = None
        self._latest_depth: np.ndarray | None = None

    def connect(self) -> bool:
        if self._connected:
            return True

        import time

        PyKinectV2, PyKinectRuntime = _import_pykinect2()
        self._pk2 = PyKinectV2
        self._runtime_mod = PyKinectRuntime

        self._kinect = PyKinectRuntime.PyKinectRuntime(
            PyKinectV2.FrameSourceTypes_Depth
        )

        # Wait for the sensor to start streaming depth frames that actually
        # contain data.  Frames can arrive all-zero when the sensor lacks a
        # true USB 3.0 link (depth/IR are uncompressed and need the bandwidth):
        # the RGB camera still works but depth stays empty.  Treat an all-zero
        # depth stream as "not usable" so the factory falls back to the
        # simulator instead of rendering a permanently flat sandbox.
        deadline = time.time() + 8.0
        saw_frame = False
        while time.time() < deadline:
            if self._kinect.has_new_depth_frame():
                saw_frame = True
                raw = self._kinect.get_last_depth_frame()
                if np.any(np.asarray(raw, dtype=np.uint16) > 0):
                    self._connected = True
                    logger.info("Kinect V2 (SDK) connected (512×424 depth)")
                    return True
            time.sleep(0.05)

        try:
            self._kinect.close()
        except Exception:
            pass
        self._kinect = None
        if saw_frame:
            raise RuntimeError(
                "Kinect V2 depth frames are arriving but contain no data "
                "(all-zero). The RGB camera works, so this is almost always a "
                "USB link problem: the sensor needs a true USB 3.0 port. "
                "Plug the Kinect Adapter for Windows into a USB 3.0 port "
                "(SuperSpeed / blue, marked 'SS' or '3.0') directly on the PC "
                "— not a front-panel port, hub, or USB 2.0 port. "
                "Verify with the Kinect V2 Configuration Verifier."
            )
        raise RuntimeError(
            "Kinect V2 (SDK) opened but no depth frames arrived within 8s. "
            "Check the USB 3.0 connection and the sensor's power adapter."
        )

    def disconnect(self) -> None:
        if not self._connected:
            return
        self._connected = False
        try:
            if self._kinect is not None:
                self._kinect.close()
        except Exception:
            pass
        self._kinect = None
        logger.info("Kinect V2 (SDK) disconnected")

    def get_depth_frame(self) -> np.ndarray | None:
        if not self._connected or self._kinect is None:
            return None
        if not self._kinect.has_new_depth_frame():
            with self._lock:
                return self._latest_depth

        raw = self._kinect.get_last_depth_frame()  # 1D uint16, len 512*424, mm
        depth = np.asarray(raw, dtype=np.float32).reshape(
            self._NATIVE_H, self._NATIVE_W
        )
        # The sensor image is mirrored; flip X so sculpting feels natural.
        depth = np.fliplr(depth)
        # 0 = "no data" -> treat as far (lowest terrain).
        depth[depth == 0] = self._max

        depth = np.clip(depth, self._min, self._max)
        # Invert: close = high terrain, far = low terrain.
        normalised = 1.0 - (depth - self._min) / (self._max - self._min)
        normalised = normalised.astype(np.float32)

        # Temporal EMA smoothing.
        if self._ema is None or self._ema.shape != normalised.shape:
            self._ema = normalised
        else:
            self._ema = (
                self._alpha * normalised + (1.0 - self._alpha) * self._ema
            ).astype(np.float32)
        out = self._ema

        if out.shape != (self._out_height, self._out_width):
            from scipy.ndimage import zoom

            zy = self._out_height / out.shape[0]
            zx = self._out_width / out.shape[1]
            out = zoom(out, (zy, zx), order=1).astype(np.float32)

        with self._lock:
            self._latest_depth = out
        return out

    def get_color_frame(self) -> np.ndarray | None:
        return None

    def is_connected(self) -> bool:
        return self._connected

    def get_resolution(self) -> tuple[int, int]:
        return (self._out_width, self._out_height)

    def get_sensor_name(self) -> str:
        return "Kinect V2 (Kinect for Windows SDK)"

    def get_sensor_info(self) -> dict:
        return {
            "name": self.get_sensor_name(),
            "resolution": self.get_resolution(),
            "connected": self.is_connected(),
            "depth_range_mm": (int(self._min), int(self._max)),
            "backend": "pykinect2",
        }

    def set_depth_range(self, min_mm: int, max_mm: int) -> None:
        max_mm = max(int(max_mm), int(min_mm) + 50)
        with self._lock:
            self._min = float(min_mm)
            self._max = float(max_mm)

    def auto_calibrate_flat_surface(
        self,
        samples: int = 30,  # unused; kept for API compatibility
        roi_frac: float = 0.5,
        build_height_mm: int = 250,
        dig_depth_mm: int = 120,
    ) -> tuple[int, int] | None:
        """Sample the flat sand surface (sensor mounted top-down over the sandbox)
        and derive a sensible (min_mm, max_mm) depth range.

        The median depth of the central ROI is taken as the flat sand plane.
        Sculpted peaks rise toward the sensor (plane - build_height_mm -> min/near)
        and dug valleys recede from it (plane + dig_depth_mm -> max/far).
        Returns (min_mm, max_mm), or None if no valid depth was captured.
        Does NOT apply the range itself; the caller applies it via set_depth_range.
        """
        if not self._connected or self._kinect is None:
            return None

        h, w = self._NATIVE_H, self._NATIVE_W
        y0, y1 = int(h * (1 - roi_frac) / 2), int(h * (1 + roi_frac) / 2)
        x0, x1 = int(w * (1 - roi_frac) / 2), int(w * (1 + roi_frac) / 2)

        # Single snapshot — spatial median over the large ROI is stable enough;
        # the previous temporal loop (collecting 30 frames) was redundant and
        # could block the UI thread for up to 5 seconds.
        if not self._kinect.has_new_depth_frame():
            return None
        raw = self._kinect.get_last_depth_frame()
        frame = np.asarray(raw, dtype=np.float32).reshape(h, w)[y0:y1, x0:x1]
        valid = frame[frame > 0]
        if not valid.size:
            return None

        plane = float(np.median(valid))
        min_mm = int(max(500, plane - build_height_mm))
        max_mm = int(min(4500, plane + dig_depth_mm))
        if max_mm <= min_mm:
            max_mm = min_mm + 200
        return (min_mm, max_mm)

    def set_filter_params(
        self,
        *,
        temporal_alpha: float,
        change_threshold_mm: int,
        persistence_frames: int,
        foreground_reject_mm: int,
    ) -> None:
        self._alpha = float(temporal_alpha)

    def resize(self, width: int, height: int) -> None:
        with self._lock:
            self._out_width = int(width)
            self._out_height = int(height)
