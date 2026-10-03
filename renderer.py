"""
Renders a normalised height map as an AR-sandbox-style elevation image.

Colour schemes : terrain, heat, greyscale, desert
Contour lines  : drawn at a configurable elevation interval above the waterline,
                 optionally labelled with height above sea level in cm
"""

from __future__ import annotations

import numpy as np
import pygame
from scipy.ndimage import gaussian_filter, zoom

# ── colour maps  (normalised_height, (R, G, B)) ───────────────────────────────

_COLORMAPS: dict[str, list[tuple[float, tuple[int, int, int]]]] = {
    "terrain": [
        (0.00, (5,   10,  80)),   # abyssal water
        (0.25, (15,  60, 160)),   # deep water
        (0.38, (25, 110, 200)),   # shallow water
        (0.43, (80, 170, 220)),   # surf
        (0.46, (220, 210, 140)),  # wet sand
        (0.50, (240, 230, 150)),  # beach
        (0.54, (120, 190,  70)),  # low grass
        (0.63, ( 70, 150,  40)),  # grass
        (0.72, (100, 110,  55)),  # highland
        (0.82, (130, 115,  85)),  # rock
        (0.91, (175, 165, 150)),  # high rock
        (1.00, (255, 255, 255)),  # snow
    ],
    "heat": [
        (0.00, (  0,   0,  50)),
        (0.20, (  0,   0, 180)),
        (0.40, (  0, 160, 200)),
        (0.60, ( 50, 210,  50)),
        (0.75, (240, 210,   0)),
        (0.90, (255,  80,   0)),
        (1.00, (255, 255, 255)),
    ],
    "greyscale": [
        (0.00, ( 10,  10,  10)),
        (1.00, (245, 245, 245)),
    ],
    "desert": [
        (0.00, ( 15,  10,   5)),
        (0.25, ( 70,  40,  15)),
        (0.45, (160, 110,  50)),
        (0.60, (210, 170,  90)),
        (0.72, (225, 190, 110)),
        (0.82, (180, 130,  70)),
        (0.92, (140,  95,  55)),
        (1.00, (230, 210, 180)),
    ],
}

WATER_LEVEL      = 0.46
CONTOUR_INTERVAL = 0.05


def _build_lut(colormap: list[tuple[float, tuple[int, int, int]]]) -> np.ndarray:
    lut = np.zeros((256, 3), dtype=np.uint8)
    for i in range(256):
        t = i / 255.0
        for k in range(len(colormap) - 1):
            t0, c0 = colormap[k]
            t1, c1 = colormap[k + 1]
            if t0 <= t <= t1:
                a = (t - t0) / (t1 - t0)
                lut[i] = [int(c0[j] + a * (c1[j] - c0[j])) for j in range(3)]
                break
    return lut


_LUTS = {name: _build_lut(cm) for name, cm in _COLORMAPS.items()}


_LABEL_CELL = 160          # px between elevation label candidates
_LABEL_REFRESH_FRAMES = 15  # labels move with the sand, but not every frame


class Renderer:
    def __init__(self, width: int, height: int) -> None:
        self._surf = pygame.Surface((width, height))
        self._resize_buffers(width, height)
        self._label_font: pygame.font.Font | None = None
        self._labels: list[tuple[int, int, str]] = []
        self._label_age = _LABEL_REFRESH_FRAMES
        self._label_sprites: dict[str, tuple[pygame.Surface, pygame.Surface]] = {}

    def _resize_buffers(self, width: int, height: int) -> None:
        self._display = np.empty((height, width), dtype=np.float32)
        self._work = np.empty((height, width), dtype=np.float32)
        self._indices = np.empty((height, width), dtype=np.uint8)
        self._rgb = np.empty((height, width, 3), dtype=np.uint8)
        self._dy = np.empty((height, width), dtype=np.float32)
        self._dx = np.empty((height, width), dtype=np.float32)
        self._shade = np.empty((height, width), dtype=np.float32)
        self._rgb_f = np.empty((height, width, 3), dtype=np.float32)

    def draw(
        self,
        target: pygame.Surface,
        height_data: np.ndarray,
        *,
        show_contours: bool = True,
        colour_scheme: str = "terrain",
        light_tint: tuple[float, float, float] | None = None,
        contour_interval: float = CONTOUR_INTERVAL,
        contour_labels_cm_per_unit: float | None = None,
    ) -> None:
        """``contour_labels_cm_per_unit`` turns on elevation labels: it is the
        real height in cm of the full 0..1 range (the calibrated depth span)."""
        # Recreate internal surface if window was resized
        if self._surf.get_size() != target.get_size():
            self._surf = pygame.Surface(target.get_size())
            self._resize_buffers(*target.get_size())

        lut = _LUTS.get(colour_scheme, _LUTS["terrain"])

        target_h = target.get_height()
        target_w = target.get_width()
        if height_data.shape != (target_h, target_w):
            height_data = zoom(
                height_data,
                (target_h / height_data.shape[0], target_w / height_data.shape[1]),
                order=1,
            ).astype(np.float32)

        # Mild display-only smoothing
        gaussian_filter(height_data, sigma=1.5, output=self._display, mode="nearest")

        # Base colour from LUT
        np.multiply(self._display, 255.0, out=self._work)
        np.clip(self._work, 0.0, 255.0, out=self._work)
        self._indices[...] = self._work
        self._rgb[...] = lut[self._indices]

        # Hillshading — NW light source. Finite differences in-place so the
        # 60 FPS path does not allocate two gradient arrays every frame.
        src = self._display
        self._dy[1:-1, :] = (src[2:, :] - src[:-2, :]) * 0.5
        self._dy[0, :] = src[1, :] - src[0, :]
        self._dy[-1, :] = src[-1, :] - src[-2, :]
        self._dx[:, 1:-1] = (src[:, 2:] - src[:, :-2]) * 0.5
        self._dx[:, 0] = src[:, 1] - src[:, 0]
        self._dx[:, -1] = src[:, -1] - src[:, -2]
        np.multiply(self._dy, -0.6, out=self._shade)
        self._shade += 1.0
        self._shade += self._dx * 0.2
        np.clip(self._shade, 0.5, 1.3, out=self._shade)
        np.multiply(self._rgb, self._shade[:, :, np.newaxis], out=self._rgb_f)
        np.clip(self._rgb_f, 0, 255, out=self._rgb_f)
        self._rgb[...] = self._rgb_f

        # Contour lines (above waterline only)
        contour = None
        if show_contours:
            above_water = self._display >= WATER_LEVEL
            quantized   = (self._display / contour_interval).astype(np.int32)
            # Compare neighbours without wrapping the screen edges (np.roll would
            # compare the top row with the bottom, drawing false border contours).
            contour = np.zeros_like(quantized, dtype=bool)
            contour[1:, :] |= quantized[1:, :] != quantized[:-1, :]
            contour[:, 1:] |= quantized[:, 1:] != quantized[:, :-1]
            contour &= above_water
            self._rgb[contour] = (self._rgb[contour] * 0.35).astype(np.uint8)

        # Day/night light tint
        if light_tint is not None and light_tint != (1.0, 1.0, 1.0):
            tint = np.array(light_tint, dtype=np.float32).reshape(1, 1, 3)
            np.multiply(self._rgb, tint, out=self._rgb_f)
            np.clip(self._rgb_f, 0, 255, out=self._rgb_f)
            self._rgb[...] = self._rgb_f

        # pygame surfarray is (W, H, 3) — transpose from numpy's (H, W, 3)
        pygame.surfarray.blit_array(self._surf, self._rgb.transpose(1, 0, 2))
        target.blit(self._surf, (0, 0))

        if contour is not None and contour_labels_cm_per_unit:
            self._label_age += 1
            if self._label_age >= _LABEL_REFRESH_FRAMES:
                self._label_age = 0
                self._labels = self._find_labels(
                    contour, self._display, contour_interval, contour_labels_cm_per_unit
                )
            self._draw_labels(target)
        else:
            self._labels = []
            self._label_age = _LABEL_REFRESH_FRAMES

    @staticmethod
    def _find_labels(
        contour: np.ndarray, display: np.ndarray, interval: float, cm_per_unit: float
    ) -> list[tuple[int, int, str]]:
        """One label per grid cell, on the first contour pixel found there,
        giving that contour's height above sea level in centimetres."""
        h, w = contour.shape
        labels = []
        half = _LABEL_CELL // 2
        for cy in range(half // 2, h - 12, _LABEL_CELL):
            for cx in range(half // 2, w - 24, _LABEL_CELL):
                cell = contour[cy:cy + half, cx:cx + half]
                hits = np.flatnonzero(cell)
                if hits.size == 0:
                    continue
                py, px = divmod(int(hits[hits.size // 2]), cell.shape[1])
                y, x = cy + py, cx + px
                level = round(float(display[y, x]) / interval)
                cm = (level * interval - WATER_LEVEL) * cm_per_unit
                labels.append((x, y, f"{cm:+.0f}"))
        return labels

    def _draw_labels(self, target: pygame.Surface) -> None:
        if self._label_font is None:
            self._label_font = pygame.font.SysFont("consolas", 12, bold=True)
        for x, y, text in self._labels:
            sprites = self._label_sprites.get(text)
            if sprites is None:
                sprites = (
                    self._label_font.render(text, True, (20, 20, 20)),
                    self._label_font.render(text, True, (245, 245, 245)),
                )
                self._label_sprites[text] = sprites
            ink, halo = sprites
            r = ink.get_rect(center=(x, y))
            for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                target.blit(halo, r.move(dx, dy))
            target.blit(ink, r)
