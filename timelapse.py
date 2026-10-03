"""
Timelapse recorder: saves the projected image as numbered PNG frames.

Frames go to assets/timelapse/<start time>/frame_00001.png. Turn a folder
into a video with, for example:

    ffmpeg -framerate 12 -i frame_%05d.png -pix_fmt yuv420p timelapse.mp4
"""

from __future__ import annotations

import logging
import pathlib
import queue
import threading
from datetime import datetime

import pygame

logger = logging.getLogger(__name__)

TIMELAPSE_DIR = pathlib.Path(__file__).parent / "assets" / "timelapse"


class TimelapseRecorder:
    """Copies a frame every ``interval`` seconds; a worker thread writes PNGs
    so the render loop never waits on disk."""

    def __init__(
        self,
        root: pathlib.Path = TIMELAPSE_DIR,
        interval: float = 10.0,
        max_frames: int = 5000,
    ) -> None:
        self.root = root
        self.interval = max(1.0, float(interval))
        self.max_frames = max_frames
        self.folder: pathlib.Path | None = None
        self.frames = 0
        self._last = 0.0
        self._queue: queue.Queue[tuple[pygame.Surface, pathlib.Path] | None] = queue.Queue(maxsize=8)
        self._worker: threading.Thread | None = None

    @property
    def active(self) -> bool:
        return self.folder is not None

    def start(self) -> pathlib.Path:
        if self.folder is not None:
            return self.folder
        self.folder = self.root / datetime.now().strftime("%Y%m%d_%H%M%S")
        self.folder.mkdir(parents=True, exist_ok=True)
        self.frames = 0
        self._last = 0.0
        self._worker = threading.Thread(target=self._run, name="timelapse", daemon=True)
        self._worker.start()
        return self.folder

    def stop(self) -> tuple[pathlib.Path | None, int]:
        folder, frames = self.folder, self.frames
        if self._worker is not None:
            self._queue.put(None)
            self._worker.join(timeout=5.0)
            self._worker = None
        self.folder = None
        return folder, frames

    def update(self, now: float, surface: pygame.Surface) -> None:
        if self.folder is None or now - self._last < self.interval:
            return
        if self.frames >= self.max_frames:
            self.stop()
            return
        self._last = now
        self.frames += 1
        path = self.folder / f"frame_{self.frames:05d}.png"
        try:
            self._queue.put_nowait((surface.copy(), path))
        except queue.Full:
            self.frames -= 1  # disk is behind; skip this frame rather than stall

    def _run(self) -> None:
        while True:
            item = self._queue.get()
            if item is None:
                return
            surface, path = item
            try:
                pygame.image.save(surface, str(path))
            except (OSError, pygame.error) as exc:
                logger.warning("Timelapse frame failed: %s", exc)
