"""
Ecosystem simulation — vegetation growth, food web, and population dynamics.

Water proximity drives grass growth, grass clusters become shrubs/trees,
trees create habitat zones. Herbivores eat vegetation, carnivores eat herbivores.
Population naturally balances through carrying capacity.
"""

from __future__ import annotations

import numpy as np
import pygame
from scipy.ndimage import uniform_filter

from renderer import WATER_LEVEL


# ── Biome classification ─────────────────────────────────────────────────────

_BIOME_THRESHOLDS: list[tuple[float, str]] = [
    (0.90, "Snow"),
    (0.80, "Alpine"),
    (0.68, "Highland"),
    (0.60, "Forest"),
    (0.50, "Grassland"),
    (WATER_LEVEL, "Beach"),
]
_BIOME_DEFAULT = "Ocean"

_BIOME_NAMES = ["Ocean", "Beach", "Grassland", "Forest", "Highland", "Alpine", "Snow"]

# ── Vegetation rendering colours ─────────────────────────────────────────────

_GRASS_RGB = (55, 155, 45)
_SHRUB_RGB = (65, 125, 50)
_TREE_CANOPY_BASE = (20, 85, 20)
_TREE_SHADOW_RGBA = (0, 0, 0, 40)


class EcosystemManager:
    """Grid-based vegetation simulation with food-chain dynamics."""

    # Vegetation elevation bands
    _GRASS_ELEV = (0.48, 0.75)
    _SHRUB_ELEV = (0.50, 0.70)
    _TREE_ELEV = (0.52, 0.65)

    # Growth / decay rates (per simulation step at 4 Hz)
    _GRASS_RATE = 0.08
    _SHRUB_RATE = 0.03
    _TREE_RATE = 0.015
    _DECAY_RATE = 0.02
    _GRAZE_RATE = 0.04

    # Succession density thresholds (neighbourhood average)
    _GRASS_TO_SHRUB = 0.6
    _SHRUB_TO_TREE = 0.5

    # Water proximity sensing
    _WATER_SENSE_SIZE = 30

    # Snow / water kill lines
    _SNOW_LINE = 0.85

    # Population balance
    _VEG_PER_HERB = 50.0
    _HERB_PER_CARN = 3.0

    # Internal tick rate
    _TICK_HZ = 4
    _TICK_DT = 1.0 / _TICK_HZ

    def __init__(self, width: int, height: int) -> None:
        self._w = width
        self._h = height
        self._enabled = False

        # Vegetation layers (h × w, float32 0-1)
        self._grass = np.zeros((height, width), dtype=np.float32)
        self._shrubs = np.zeros((height, width), dtype=np.float32)
        self._trees = np.zeros((height, width), dtype=np.float32)

        # Pre-computed helpers (recomputed when terrain changes)
        self._water_prox = np.zeros((height, width), dtype=np.float32)
        self._elev_factor = np.ones((height, width), dtype=np.float32)
        self._grass_zone = np.zeros((height, width), dtype=bool)
        self._shrub_zone = np.zeros((height, width), dtype=bool)
        self._tree_zone = np.zeros((height, width), dtype=bool)
        self._biome_ids = np.zeros((height, width), dtype=np.uint8)
        self._terrain_sig = -1.0

        # Day phase (growth only during day)
        self._is_day = True

        # Tick accumulator
        self._accum = 0.0

        # Render cache
        self._veg_surface = pygame.Surface((width, height), pygame.SRCALPHA)
        self._render_dirty = True

        # Stats cache
        self._stats: dict[str, float | int] = {
            "grass_pct": 0.0,
            "shrub_pct": 0.0,
            "tree_pct": 0.0,
            "herb_cap": 0,
            "carn_cap": 0,
        }

    # ── public API ────────────────────────────────────────────────────────────

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = enabled
        if enabled:
            self._render_dirty = True

    def is_enabled(self) -> bool:
        return self._enabled

    def reset(self) -> None:
        self._grass.fill(0)
        self._shrubs.fill(0)
        self._trees.fill(0)
        self._terrain_sig = -1.0
        self._accum = 0.0
        self._render_dirty = True

    def set_day_phase(self, is_day: bool) -> None:
        self._is_day = is_day

    def update(self, height_data: np.ndarray, dt: float, water_coverage=None) -> None:
        if not self._enabled:
            return

        self._accum += dt
        if self._accum < self._TICK_DT:
            return
        self._accum -= self._TICK_DT

        hd = self._match_shape(height_data)
        self._refresh_terrain_cache(hd)
        self._grow(hd)
        self._refresh_stats(hd)
        self._render_dirty = True

    def draw(self, surface: pygame.Surface) -> None:
        if not self._enabled:
            return
        if self._render_dirty:
            self._paint()
            self._render_dirty = False
        surface.blit(self._veg_surface, (0, 0))

    def get_vegetation_map(self) -> np.ndarray:
        """Combined vegetation density 0-1 (float32, h × w)."""
        return np.clip(
            self._grass * 0.4 + self._shrubs * 0.3 + self._trees * 0.3,
            0.0, 1.0,
        )

    def get_stats(self) -> dict:
        return dict(self._stats)

    def get_biome_name(self, x: int, y: int) -> str:
        if 0 <= x < self._w and 0 <= y < self._h:
            return _BIOME_NAMES[self._biome_ids[y, x]]
        return "Unknown"

    def get_vegetation_at(self, x: int, y: int) -> float:
        if 0 <= x < self._w and 0 <= y < self._h:
            return float(
                self._grass[y, x] * 0.4
                + self._shrubs[y, x] * 0.3
                + self._trees[y, x] * 0.3
            )
        return 0.0

    def graze_at(self, x: int, y: int, radius: int = 5) -> None:
        """Reduce vegetation around a grazing herbivore."""
        if not self._enabled:
            return
        y0, y1 = max(0, y - radius), min(self._h, y + radius + 1)
        x0, x1 = max(0, x - radius), min(self._w, x + radius + 1)
        self._grass[y0:y1, x0:x1] -= self._GRAZE_RATE * self._TICK_DT
        self._shrubs[y0:y1, x0:x1] -= self._GRAZE_RATE * 0.3 * self._TICK_DT
        np.clip(self._grass[y0:y1, x0:x1], 0, 1, out=self._grass[y0:y1, x0:x1])
        np.clip(self._shrubs[y0:y1, x0:x1], 0, 1, out=self._shrubs[y0:y1, x0:x1])

    # ── HUD helpers ───────────────────────────────────────────────────────────

    def draw_stats(
        self,
        surface: pygame.Surface,
        font: pygame.font.Font,
        x: int,
        y: int,
        herbivore_count: int = 0,
        carnivore_count: int = 0,
    ) -> None:
        if not self._enabled:
            return
        g = int(self._stats.get("grass_pct", 0) * 100)
        t = int(self._stats.get("tree_pct", 0) * 100)
        text = (
            f"Grass {g}%  Trees {t}%  "
            f"Herb {herbivore_count}  Carn {carnivore_count}"
        )
        shadow = font.render(text, True, (0, 0, 0))
        label = font.render(text, True, (190, 225, 170))
        surface.blit(shadow, (x + 1, y + 1))
        surface.blit(label, (x, y))

    def draw_biome_tooltip(
        self,
        surface: pygame.Surface,
        font: pygame.font.Font,
        mx: int,
        my: int,
    ) -> None:
        if not self._enabled:
            return
        biome = self.get_biome_name(mx, my)
        veg = self.get_vegetation_at(mx, my)
        text = f"{biome} ({veg:.0%} veg)"
        label = font.render(text, True, (240, 240, 200))
        shadow = font.render(text, True, (0, 0, 0))
        tx = min(mx + 15, surface.get_width() - label.get_width() - 5)
        ty = max(5, my - 20)
        surface.blit(shadow, (tx + 1, ty + 1))
        surface.blit(label, (tx, ty))

    # ── internals ─────────────────────────────────────────────────────────────

    def _match_shape(self, hd: np.ndarray) -> np.ndarray:
        """Return height data matched to (self._h, self._w)."""
        h, w = hd.shape[:2]
        if h == self._h and w == self._w:
            return hd
        # Crop or pad to fit
        rh, rw = min(h, self._h), min(w, self._w)
        out = np.full((self._h, self._w), 0.5, dtype=np.float32)
        out[:rh, :rw] = hd[:rh, :rw]
        return out

    def _refresh_terrain_cache(self, hd: np.ndarray) -> None:
        sig = float(np.mean(hd[::8, ::8]))
        if abs(sig - self._terrain_sig) < 0.008:
            return
        self._terrain_sig = sig

        # Water proximity (0-1, 1 = at water edge)
        water_mask = (hd < WATER_LEVEL).astype(np.float32)
        self._water_prox = np.clip(
            uniform_filter(water_mask, size=self._WATER_SENSE_SIZE * 2) * 4.0,
            0.0, 1.0,
        )

        # Elevation growth penalty (higher = slower)
        self._elev_factor = np.clip(1.0 - (hd - 0.5) * 2.0, 0.2, 1.0).astype(
            np.float32
        )

        # Zone masks
        valid = (hd >= WATER_LEVEL) & (hd < self._SNOW_LINE)
        self._grass_zone = valid & (hd >= self._GRASS_ELEV[0]) & (hd <= self._GRASS_ELEV[1])
        self._shrub_zone = valid & (hd >= self._SHRUB_ELEV[0]) & (hd <= self._SHRUB_ELEV[1])
        self._tree_zone = valid & (hd >= self._TREE_ELEV[0]) & (hd <= self._TREE_ELEV[1])

        # Biome IDs  0=ocean 1=beach 2=grassland 3=forest 4=highland 5=alpine 6=snow
        bm = self._biome_ids
        bm[:] = 0
        bm[hd >= WATER_LEVEL] = 1
        bm[hd >= 0.50] = 2
        bm[hd >= 0.60] = 3
        bm[hd >= 0.68] = 4
        bm[hd >= 0.80] = 5
        bm[hd >= 0.90] = 6

        # Kill vegetation outside valid zones
        invalid = ~valid
        self._grass[invalid] = 0
        self._shrubs[invalid] = 0
        self._trees[invalid] = 0

    def _grow(self, hd: np.ndarray) -> None:
        gm = 1.0 if self._is_day else 0.0
        wp = self._water_prox
        ef = self._elev_factor
        td = self._TICK_DT

        # Grass
        self._grass += (self._GRASS_RATE * wp * ef * gm * td) * self._grass_zone
        self._grass -= self._DECAY_RATE * td * (~self._grass_zone & (self._grass > 0))
        np.clip(self._grass, 0, 1, out=self._grass)

        # Shrubs from dense grass
        grass_nbr = uniform_filter(self._grass, size=5)
        can_shrub = (grass_nbr > self._GRASS_TO_SHRUB) & self._shrub_zone
        self._shrubs += (self._SHRUB_RATE * wp * gm * td) * can_shrub
        self._shrubs -= self._DECAY_RATE * 0.7 * td * (~self._shrub_zone & (self._shrubs > 0))
        np.clip(self._shrubs, 0, 1, out=self._shrubs)

        # Trees from dense shrubs
        shrub_nbr = uniform_filter(self._shrubs, size=7)
        can_tree = (shrub_nbr > self._SHRUB_TO_TREE) & self._tree_zone
        self._trees += (self._TREE_RATE * wp * gm * td) * can_tree
        self._trees -= self._DECAY_RATE * 0.5 * td * (~self._tree_zone & (self._trees > 0))
        np.clip(self._trees, 0, 1, out=self._trees)

    def _refresh_stats(self, hd: np.ndarray) -> None:
        land = float(np.sum(hd >= WATER_LEVEL))
        if land < 1:
            land = 1.0
        self._stats["grass_pct"] = float(np.sum(self._grass > 0.1)) / land
        self._stats["shrub_pct"] = float(np.sum(self._shrubs > 0.1)) / land
        self._stats["tree_pct"] = float(np.sum(self._trees > 0.1)) / land

        veg_above = float(np.sum(self.get_vegetation_map() > 0.3))
        herb_cap = max(1, int(veg_above / self._VEG_PER_HERB))
        self._stats["herb_cap"] = herb_cap
        self._stats["carn_cap"] = max(1, herb_cap // int(self._HERB_PER_CARN))

    # ── rendering ─────────────────────────────────────────────────────────────

    def _paint(self) -> None:
        self._veg_surface.fill((0, 0, 0, 0))

        h, w = self._h, self._w
        pixels = np.zeros((h, w, 4), dtype=np.uint8)

        # Grass layer
        gm = self._grass > 0.12
        ga = np.clip(self._grass * 75, 0, 75).astype(np.uint8)
        pixels[gm, 0] = _GRASS_RGB[0]
        pixels[gm, 1] = _GRASS_RGB[1]
        pixels[gm, 2] = _GRASS_RGB[2]
        pixels[gm, 3] = ga[gm]

        # Shrub layer (additive alpha blend)
        sm = self._shrubs > 0.12
        sa = np.clip(self._shrubs * 100 + 15, 0, 115).astype(np.uint8)
        pixels[sm, 0] = _SHRUB_RGB[0]
        pixels[sm, 1] = _SHRUB_RGB[1]
        pixels[sm, 2] = _SHRUB_RGB[2]
        pixels[sm, 3] = np.maximum(pixels[sm, 3], sa[sm])

        # Tree base (pixel layer — individual circles drawn below)
        tm = self._trees > 0.12
        ta = np.clip(self._trees * 130 + 20, 0, 150).astype(np.uint8)
        pixels[tm, 0] = _TREE_CANOPY_BASE[0]
        pixels[tm, 1] = _TREE_CANOPY_BASE[1]
        pixels[tm, 2] = _TREE_CANOPY_BASE[2]
        pixels[tm, 3] = np.maximum(pixels[tm, 3], ta[tm])

        # Blit pixel buffer
        surf = pygame.image.frombuffer(
            pixels.tobytes(), (w, h), "RGBA"
        ).convert_alpha()
        self._veg_surface.blit(surf, (0, 0))

        # Draw tree circles (subsampled for performance)
        step = 4
        tree_sub = self._trees[::step, ::step]
        tys, txs = np.where(tree_sub > 0.3)
        for i in range(min(len(txs), 600)):
            tx = int(txs[i]) * step
            ty = int(tys[i]) * step
            d = float(self._trees[min(ty, h - 1), min(tx, w - 1)])
            r = int(2 + d * 3)
            a = int(min(180, 70 + d * 110))
            g_val = min(255, 85 + int(d * 35))
            # Shadow first
            pygame.draw.circle(
                self._veg_surface, (0, 0, 0, int(a * 0.25)), (tx + 1, ty + 1), r,
            )
            # Canopy
            pygame.draw.circle(
                self._veg_surface, (22, g_val, 22, a), (tx, ty), r,
            )
