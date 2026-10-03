"""Live sensor health for the dashboard's setup check.

Measures, about once a second, how much the surface flickers between frames
(after smoothing) and how much of the sand sits inside the depth range.
"""

from __future__ import annotations

import numpy as np

STEP = 4                # analyse every 4th pixel in each direction
INTERVAL_S = 1.0
EDGE = 0.002            # heights this close to 0 or 1 count as clipped


class SurfaceHealth:
    def __init__(self) -> None:
        self._prev: np.ndarray | None = None
        self._last = -INTERVAL_S
        self.noise_mm: float | None = None
        self.in_range_pct: float | None = None

    def update(self, now: float, frame: np.ndarray | None, depth_range_mm: float) -> None:
        if frame is None or now - self._last < INTERVAL_S:
            return
        self._last = now
        sample = np.asarray(frame[::STEP, ::STEP], dtype=np.float32)
        clipped = (sample <= EDGE) | (sample >= 1.0 - EDGE)
        self.in_range_pct = round(100.0 * (1.0 - float(np.mean(clipped))), 1)
        if self._prev is not None and self._prev.shape == sample.shape:
            valid = ~clipped
            if np.any(valid):
                diff = np.abs(sample[valid] - self._prev[valid])
                # The 90th percentile ignores hands and fresh digging but still
                # catches sensor noise that covers the whole box.
                self.noise_mm = round(float(np.percentile(diff, 90)) * depth_range_mm, 1)
        self._prev = sample

    def as_dict(self) -> dict:
        return {"noise_mm": self.noise_mm, "in_range_pct": self.in_range_pct}
