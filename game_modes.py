"""
Interactive game/mission modes for DuneBox-sandcam.

Each mode presents a terrain challenge with objectives, scoring, and time limits.
Includes a lightweight CPU-based water-flow simulation for game logic.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

import numpy as np
import pygame


# ── Lightweight water-flow simulation ──────────────────────────────────────────

_FLOW_RATE = 0.15  # fraction of excess transferred per step
_SIM_STEPS = 2     # cellular-automata iterations per frame


def _shift(a: np.ndarray, dy: int, dx: int, mode: str) -> np.ndarray:
    """Shift ``a`` so result[i, j] == a[i - dy, j - dx] without wrap-around."""
    ady, adx = abs(dy), abs(dx)
    ap = np.pad(a, ((ady, ady), (adx, adx)), mode=mode)
    h, w = a.shape
    return ap[ady - dy: ady - dy + h, adx - dx: adx - dx + w]


def water_sim_step(
    terrain: np.ndarray,
    water: np.ndarray,
    sources: np.ndarray | None = None,
    dt: float = 1.0 / 60,
) -> np.ndarray:
    """Advance a simple cellular-automata water simulation by one frame.

    *terrain* and *water* are float32 arrays of equal shape (H, W), both in
    normalised 0-1 range.  *sources* is an optional boolean mask where water is
    added each frame.  Returns the updated *water* array (modified in-place).
    """
    if sources is not None:
        water[sources] += 0.004 * dt * 60

    for _ in range(_SIM_STEPS):
        surface = terrain + water
        for dy, dx in ((0, 1), (0, -1), (1, 0), (-1, 0)):
            neighbour = _shift(surface, dy, dx, "edge")
            diff = surface - neighbour
            flow = np.clip(diff * _FLOW_RATE, 0.0, water)
            water -= flow
            water += _shift(flow, -dy, -dx, "constant")
            surface = terrain + water  # refresh

    water *= 0.998  # gentle evaporation
    np.clip(water, 0.0, 1.0, out=water)
    return water


def water_coverage_surface(
    water: np.ndarray,
    size: tuple[int, int],
    colour: tuple[int, int, int] = (30, 100, 220),
    max_alpha: int = 160,
) -> pygame.Surface:
    """Return a semi-transparent RGBA surface showing *water* depth."""
    w, h = size
    if water.shape != (h, w):
        from scipy.ndimage import zoom
        water = zoom(water, (h / water.shape[0], w / water.shape[1]), order=0)
    alpha = np.clip(water * (max_alpha / 0.05), 0, max_alpha).astype(np.uint8)
    rgba = np.zeros((h, w, 4), dtype=np.uint8)
    rgba[..., 0] = colour[0]
    rgba[..., 1] = colour[1]
    rgba[..., 2] = colour[2]
    rgba[..., 3] = alpha
    surf = pygame.image.frombuffer(rgba.tobytes(), (w, h), "RGBA").convert_alpha()
    return surf


# ── UI constants & helpers ─────────────────────────────────────────────────────

_PANEL_BG = (14, 18, 30)
_PANEL_BORDER = (60, 130, 210)
_TEXT_PRIMARY = (230, 235, 245)
_TEXT_SECONDARY = (150, 165, 190)
_TEXT_ACCENT = (80, 200, 130)
_TEXT_WARNING = (240, 180, 50)
_TEXT_DANGER = (240, 80, 80)
_STAR_FILLED = (255, 210, 50)
_STAR_EMPTY = (60, 65, 80)

_font_cache: dict[tuple[str | None, int], pygame.font.Font] = {}


def _font(size: int, bold: bool = False) -> pygame.font.Font:
    key = (None, size * 10 + int(bold))
    if key not in _font_cache:
        _font_cache[key] = pygame.font.SysFont(None, size, bold=bold)
    return _font_cache[key]


def _draw_panel(
    surface: pygame.Surface,
    rect: pygame.Rect,
    *,
    alpha: int = 210,
    border_colour: tuple[int, int, int] = _PANEL_BORDER,
    radius: int = 10,
) -> None:
    panel = pygame.Surface(rect.size, pygame.SRCALPHA)
    pygame.draw.rect(panel, (*_PANEL_BG, alpha), panel.get_rect(), border_radius=radius)
    pygame.draw.rect(panel, border_colour, panel.get_rect(), width=2, border_radius=radius)
    surface.blit(panel, rect.topleft)


def _draw_stars(surface: pygame.Surface, x: int, y: int, count: int, total: int = 3) -> None:
    for i in range(total):
        char = "★" if i < count else "☆"
        colour = _STAR_FILLED if i < count else _STAR_EMPTY
        label = _font(30).render(char, True, colour)
        surface.blit(label, (x + i * 28, y))


def _format_timer(seconds: float) -> str:
    m = int(seconds) // 60
    s = int(seconds) % 60
    return f"{m}:{s:02d}"


# ── Base game mode ─────────────────────────────────────────────────────────────


class GameMode(ABC):
    """Abstract base for all sandbox game modes."""

    name: str = ""
    description: str = ""
    time_limit: float = 0.0  # 0 = unlimited

    def __init__(self) -> None:
        self._score: int = 0
        self._elapsed: float = 0.0
        self._complete: bool = False
        self._result_text: str = ""
        self._star_rating: int = 0
        self._show_end_screen: bool = False
        self._end_screen_timer: float = 0.0

    # ── public interface ──

    @abstractmethod
    def start(self, height_data: np.ndarray) -> None: ...

    @abstractmethod
    def _tick(self, height_data: np.ndarray, dt: float) -> None: ...

    @abstractmethod
    def _draw_game(self, surface: pygame.Surface) -> None: ...

    def update(self, height_data: np.ndarray, dt: float) -> bool:
        """Return True while the game is still active (including end screen)."""
        if self._show_end_screen:
            self._end_screen_timer += dt
            return self._end_screen_timer < 6.0  # show results for 6 s
        if self._complete:
            self._show_end_screen = True
            return True
        self._elapsed += dt
        if 0 < self.time_limit <= self._elapsed:
            self._finish()
            return True
        self._tick(height_data, dt)
        return True

    def draw(self, surface: pygame.Surface) -> None:
        sw, sh = surface.get_size()
        if self._show_end_screen:
            self._draw_end_screen(surface)
            return
        # top bar
        bar_h = 52
        bar_rect = pygame.Rect(0, 0, sw, bar_h)
        _draw_panel(surface, bar_rect, alpha=190, radius=0)

        # name
        name_lbl = _font(22, bold=True).render(self.name, True, _TEXT_PRIMARY)
        surface.blit(name_lbl, (12, 6))

        # objective
        obj_lbl = _font(18).render(self.description, True, _TEXT_SECONDARY)
        surface.blit(obj_lbl, (12, 28))

        # timer
        if self.time_limit > 0:
            remaining = max(0.0, self.time_limit - self._elapsed)
            timer_colour = _TEXT_DANGER if remaining < 10 else _TEXT_WARNING if remaining < 30 else _TEXT_PRIMARY
            timer_lbl = _font(24, bold=True).render(_format_timer(remaining), True, timer_colour)
        else:
            timer_lbl = _font(24, bold=True).render(_format_timer(self._elapsed), True, _TEXT_PRIMARY)
        surface.blit(timer_lbl, (sw - timer_lbl.get_width() - 14, 6))

        # score
        score_lbl = _font(20).render(f"Score: {self._score}", True, _TEXT_ACCENT)
        surface.blit(score_lbl, (sw - score_lbl.get_width() - 14, 30))

        # game-specific overlay
        self._draw_game(surface)

    def get_score(self) -> int:
        return self._score

    def get_elapsed(self) -> float:
        return self._elapsed

    def is_complete(self) -> bool:
        return self._complete

    def get_result_text(self) -> str:
        return self._result_text

    # ── internals ──

    def _finish(self) -> None:
        self._complete = True

    def _draw_end_screen(self, surface: pygame.Surface) -> None:
        sw, sh = surface.get_size()
        pw, ph = min(400, sw - 40), 200
        rect = pygame.Rect((sw - pw) // 2, (sh - ph) // 2, pw, ph)
        _draw_panel(surface, rect, alpha=230, border_colour=_TEXT_ACCENT)

        cx = rect.centerx
        # title
        t = _font(26, bold=True).render("Game Over", True, _TEXT_PRIMARY)
        surface.blit(t, (cx - t.get_width() // 2, rect.y + 14))

        # name
        n = _font(20).render(self.name, True, _TEXT_SECONDARY)
        surface.blit(n, (cx - n.get_width() // 2, rect.y + 44))

        # score
        s = _font(28, bold=True).render(f"Score: {self._score}", True, _TEXT_ACCENT)
        surface.blit(s, (cx - s.get_width() // 2, rect.y + 78))

        # stars
        _draw_stars(surface, cx - 42, rect.y + 118, self._star_rating)

        # result text
        r = _font(18).render(self._result_text, True, _TEXT_SECONDARY)
        surface.blit(r, (cx - r.get_width() // 2, rect.y + 160))


# ── 1. Build-a-Dam ─────────────────────────────────────────────────────────────


class BuildADam(GameMode):
    """Water rises from the left. Sculpt a dam to keep the right side dry."""

    name = "Build a Dam"
    description = "Stop the rising water from flooding the right side!"
    time_limit = 120.0

    def __init__(self) -> None:
        super().__init__()
        self._water: np.ndarray = np.array([])
        self._source_mask: np.ndarray = np.array([])
        self._danger_zone: np.ndarray = np.array([])
        self._flood_amount: float = 0.0
        self._flood_threshold: float = 0.02
        self._water_rise_rate: float = 0.0005
        self._overflowed: bool = False

    def start(self, height_data: np.ndarray) -> None:
        h, w = height_data.shape
        self._water = np.zeros_like(height_data, dtype=np.float32)
        self._source_mask = np.zeros((h, w), dtype=bool)
        self._source_mask[:, :max(1, w // 10)] = True
        self._danger_zone = np.zeros((h, w), dtype=bool)
        self._danger_zone[:, -max(1, w // 6):] = True
        self._water[self._source_mask] = 0.01

    def _tick(self, height_data: np.ndarray, dt: float) -> None:
        self._water_rise_rate = 0.0003 + self._elapsed * 0.000003
        self._water[self._source_mask] += self._water_rise_rate * dt * 60

        self._water = water_sim_step(height_data, self._water, self._source_mask, dt)

        danger_water = float(np.mean(self._water[self._danger_zone]))
        self._flood_amount = danger_water

        survival_seconds = int(self._elapsed)
        self._score = survival_seconds * 10

        if danger_water > self._flood_threshold:
            self._overflowed = True
            self._result_text = f"Dam breached after {_format_timer(self._elapsed)}!"
            self._star_rating = 1 if survival_seconds >= 30 else 0
            if survival_seconds >= 60:
                self._star_rating = 2
            if survival_seconds >= 90:
                self._star_rating = 3
            self._finish()

    def _draw_game(self, surface: pygame.Surface) -> None:
        sw, sh = surface.get_size()
        # water overlay
        if self._water.size > 0 and np.any(self._water > 0.001):
            overlay = water_coverage_surface(self._water, (sw, sh))
            surface.blit(overlay, (0, 0))

        # source indicator (left edge blue stripe)
        stripe = pygame.Surface((8, sh), pygame.SRCALPHA)
        stripe.fill((30, 100, 255, 120))
        surface.blit(stripe, (0, 0))

        # danger zone indicator (right edge red stripe)
        dw = max(1, sw // 6)
        danger = pygame.Surface((dw, sh), pygame.SRCALPHA)
        alpha = int(40 + 80 * min(1.0, self._flood_amount / self._flood_threshold))
        danger.fill((240, 60, 60, alpha))
        surface.blit(danger, (sw - dw, 0))

        # flood meter
        meter_w, meter_h = 120, 14
        mx = sw - dw - meter_w - 12
        my = 62
        _draw_panel(surface, pygame.Rect(mx - 4, my - 4, meter_w + 8, meter_h + 8), alpha=180, radius=6)
        fill_frac = min(1.0, self._flood_amount / self._flood_threshold)
        fill_colour = _TEXT_DANGER if fill_frac > 0.7 else _TEXT_WARNING if fill_frac > 0.4 else _TEXT_ACCENT
        pygame.draw.rect(surface, (40, 45, 60), (mx, my, meter_w, meter_h), border_radius=4)
        if fill_frac > 0:
            pygame.draw.rect(surface, fill_colour, (mx, my, int(meter_w * fill_frac), meter_h), border_radius=4)
        lbl = _font(16).render("Flood Danger", True, _TEXT_SECONDARY)
        surface.blit(lbl, (mx, my - 18))

    def _finish(self) -> None:
        if not self._overflowed:
            self._result_text = f"Dam held for the full {_format_timer(self.time_limit)}!"
            self._star_rating = 3
        super()._finish()


# ── 2. Volcano Defense ─────────────────────────────────────────────────────────


class VolcanoDefense(GameMode):
    """Protect the village from lava flowing downhill from a volcano peak."""

    name = "Volcano Defense"
    description = "Divert lava to protect the village!"
    time_limit = 120.0

    def __init__(self) -> None:
        super().__init__()
        self._lava: np.ndarray = np.array([])
        self._peak: tuple[int, int] = (0, 0)
        self._village: tuple[int, int] = (0, 0)
        self._village_radius: int = 20
        self._village_mask: np.ndarray = np.array([])
        self._village_damage: float = 0.0
        self._damage_threshold: float = 0.15

    def start(self, height_data: np.ndarray) -> None:
        h, w = height_data.shape
        self._lava = np.zeros_like(height_data, dtype=np.float32)

        # place volcano at the highest point (upper region)
        upper = height_data[:h // 2, :]
        peak_idx = np.unravel_index(np.argmax(upper), upper.shape)
        self._peak = (int(peak_idx[0]), int(peak_idx[1]))

        # place village in lower region away from peak
        self._village = (h * 3 // 4, w // 2)
        self._village_radius = max(12, min(w, h) // 10)

        self._village_mask = np.zeros((h, w), dtype=bool)
        yy, xx = np.ogrid[:h, :w]
        dist = np.sqrt((yy - self._village[0]) ** 2 + (xx - self._village[1]) ** 2)
        self._village_mask[dist <= self._village_radius] = True

    def _tick(self, height_data: np.ndarray, dt: float) -> None:
        # emit lava from peak
        py, px = self._peak
        r = 5
        h, w = height_data.shape
        y0, y1 = max(0, py - r), min(h, py + r + 1)
        x0, x1 = max(0, px - r), min(w, px + r + 1)
        self._lava[y0:y1, x0:x1] += 0.003 * dt * 60

        # flow lava downhill (reuse water sim with lava colour)
        self._lava = water_sim_step(height_data, self._lava, dt=dt)

        # check village damage
        village_lava = float(np.mean(self._lava[self._village_mask]))
        self._village_damage += village_lava * dt * 60 * 0.5
        self._score = int(self._elapsed * 10)

        if self._village_damage >= self._damage_threshold:
            self._result_text = f"Village destroyed after {_format_timer(self._elapsed)}!"
            survival = self._elapsed
            self._star_rating = 1 if survival >= 30 else 0
            if survival >= 60:
                self._star_rating = 2
            if survival >= 100:
                self._star_rating = 3
            self._finish()

    def _draw_game(self, surface: pygame.Surface) -> None:
        sw, sh = surface.get_size()

        # lava overlay (orange/red)
        if self._lava.size > 0 and np.any(self._lava > 0.001):
            overlay = water_coverage_surface(self._lava, (sw, sh), colour=(220, 80, 20), max_alpha=200)
            surface.blit(overlay, (0, 0))

        # scale coords to surface
        h, w = max(1, self._lava.shape[0]), max(1, self._lava.shape[1])
        def sx(c): return int(c * sw / w)
        def sy(r): return int(r * sh / h)

        # volcano marker
        py, px = self._peak
        pygame.draw.circle(surface, (255, 100, 30), (sx(px), sy(py)), 10, 3)
        vlbl = _font(16, bold=True).render("🌋 VOLCANO", True, (255, 120, 40))
        surface.blit(vlbl, (sx(px) + 14, sy(py) - 8))

        # village marker
        vy, vx = self._village
        vr = max(8, int(self._village_radius * sw / w))
        pygame.draw.circle(surface, (100, 220, 100), (sx(vx), sy(vy)), vr, 3)
        vlbl2 = _font(16, bold=True).render("🏘 VILLAGE", True, (100, 220, 100))
        surface.blit(vlbl2, (sx(vx) + vr + 4, sy(vy) - 8))

        # damage meter
        meter_w, meter_h = 140, 14
        mx, my = 12, 62
        _draw_panel(surface, pygame.Rect(mx - 4, my - 4, meter_w + 8, meter_h + 24), alpha=180, radius=6)
        fill_frac = min(1.0, self._village_damage / self._damage_threshold)
        fill_colour = _TEXT_DANGER if fill_frac > 0.6 else _TEXT_WARNING if fill_frac > 0.3 else _TEXT_ACCENT
        pygame.draw.rect(surface, (40, 45, 60), (mx, my, meter_w, meter_h), border_radius=4)
        if fill_frac > 0:
            pygame.draw.rect(surface, fill_colour, (mx, my, int(meter_w * fill_frac), meter_h), border_radius=4)
        lbl = _font(16).render("Village Damage", True, _TEXT_SECONDARY)
        surface.blit(lbl, (mx, my + 16))

    def _finish(self) -> None:
        if self._village_damage < self._damage_threshold:
            self._result_text = "Village survived the full eruption!"
            self._star_rating = 3
        super()._finish()


# ── 3. Watershed Puzzle ────────────────────────────────────────────────────────


class WatershedPuzzle(GameMode):
    """Route rainwater from a source point to a target collection basin."""

    name = "Watershed Puzzle"
    description = "Sculpt channels to route water to the green target!"
    time_limit = 90.0

    def __init__(self) -> None:
        super().__init__()
        self._water: np.ndarray = np.array([])
        self._source: tuple[int, int] = (0, 0)
        self._target: tuple[int, int] = (0, 0)
        self._target_radius: int = 15
        self._target_mask: np.ndarray = np.array([])
        self._source_mask: np.ndarray = np.array([])
        self._collected: float = 0.0
        self._total_released: float = 0.0

    def start(self, height_data: np.ndarray) -> None:
        h, w = height_data.shape
        self._water = np.zeros_like(height_data, dtype=np.float32)

        # source near top-left, target near bottom-right
        self._source = (h // 5, w // 5)
        self._target = (h * 4 // 5, w * 4 // 5)
        self._target_radius = max(10, min(w, h) // 8)

        self._source_mask = np.zeros((h, w), dtype=bool)
        sy, sx = self._source
        r = 4
        self._source_mask[max(0, sy - r):min(h, sy + r + 1),
                          max(0, sx - r):min(w, sx + r + 1)] = True

        self._target_mask = np.zeros((h, w), dtype=bool)
        yy, xx = np.ogrid[:h, :w]
        dist = np.sqrt((yy - self._target[0]) ** 2 + (xx - self._target[1]) ** 2)
        self._target_mask[dist <= self._target_radius] = True

    def _tick(self, height_data: np.ndarray, dt: float) -> None:
        self._total_released += 0.003 * dt * 60 * float(np.sum(self._source_mask))

        self._water = water_sim_step(height_data, self._water, self._source_mask, dt)

        # measure water collected in target
        target_water = float(np.sum(self._water[self._target_mask]))
        self._collected = target_water

        pct = (self._collected / max(0.001, self._total_released)) * 100
        self._score = int(min(100, pct))

    def _draw_game(self, surface: pygame.Surface) -> None:
        sw, sh = surface.get_size()

        if self._water.size > 0 and np.any(self._water > 0.001):
            overlay = water_coverage_surface(self._water, (sw, sh), colour=(40, 120, 240))
            surface.blit(overlay, (0, 0))

        h, w = max(1, self._water.shape[0]), max(1, self._water.shape[1])
        def sx_fn(c): return int(c * sw / w)
        def sy_fn(r): return int(r * sh / h)

        # source marker (blue)
        sy, sxp = self._source
        pygame.draw.circle(surface, (60, 140, 255), (sx_fn(sxp), sy_fn(sy)), 10, 3)
        lbl = _font(16, bold=True).render("💧 SOURCE", True, (80, 160, 255))
        surface.blit(lbl, (sx_fn(sxp) + 14, sy_fn(sy) - 8))

        # target marker (green)
        ty, txp = self._target
        tr = max(8, int(self._target_radius * sw / w))
        pygame.draw.circle(surface, (60, 220, 100), (sx_fn(txp), sy_fn(ty)), tr, 3)
        lbl2 = _font(16, bold=True).render("🎯 TARGET", True, (80, 230, 120))
        surface.blit(lbl2, (sx_fn(txp) + tr + 4, sy_fn(ty) - 8))

        # collection progress
        pct = (self._collected / max(0.001, self._total_released)) * 100
        meter_w, meter_h = 140, 14
        mx, my = 12, 62
        _draw_panel(surface, pygame.Rect(mx - 4, my - 4, meter_w + 8, meter_h + 24), alpha=180, radius=6)
        fill_frac = min(1.0, pct / 100.0)
        pygame.draw.rect(surface, (40, 45, 60), (mx, my, meter_w, meter_h), border_radius=4)
        if fill_frac > 0:
            pygame.draw.rect(surface, _TEXT_ACCENT, (mx, my, int(meter_w * fill_frac), meter_h), border_radius=4)
        lbl3 = _font(16).render(f"Collected: {pct:.0f}%", True, _TEXT_SECONDARY)
        surface.blit(lbl3, (mx, my + 16))

    def _finish(self) -> None:
        pct = (self._collected / max(0.001, self._total_released)) * 100
        self._score = int(min(100, pct))
        self._result_text = f"Routed {pct:.0f}% of water to the target"
        if pct >= 60:
            self._star_rating = 3
        elif pct >= 35:
            self._star_rating = 2
        elif pct >= 15:
            self._star_rating = 1
        else:
            self._star_rating = 0
        super()._finish()


# ── 4. Biome Sculpt ───────────────────────────────────────────────────────────


# Target biome elevation distribution
_BIOME_TARGETS: dict[str, tuple[float, float, float]] = {
    # name: (low_threshold, high_threshold, target_percentage)
    "Ocean":     (0.00, 0.38, 20.0),
    "Beach":     (0.38, 0.50, 10.0),
    "Grassland": (0.50, 0.72, 35.0),
    "Mountain":  (0.72, 0.91, 25.0),
    "Snow":      (0.91, 1.01, 10.0),
}

_BIOME_COLOURS: dict[str, tuple[int, int, int]] = {
    "Ocean":     (25, 100, 200),
    "Beach":     (220, 210, 140),
    "Grassland": (80, 180, 60),
    "Mountain":  (130, 115, 85),
    "Snow":      (240, 240, 250),
}


class BiomeSculpt(GameMode):
    """Sculpt terrain to match target biome elevation percentages."""

    name = "Biome Sculpt"
    description = "Shape the terrain to match the target biome distribution!"
    time_limit = 120.0

    def __init__(self) -> None:
        super().__init__()
        self._current_dist: dict[str, float] = {}
        self._accuracy: float = 0.0

    def start(self, height_data: np.ndarray) -> None:
        self._update_distribution(height_data)

    def _update_distribution(self, height_data: np.ndarray) -> None:
        total = float(height_data.size)
        self._current_dist = {}
        for name, (lo, hi, _target) in _BIOME_TARGETS.items():
            count = float(np.sum((height_data >= lo) & (height_data < hi)))
            self._current_dist[name] = (count / total) * 100.0

    def _tick(self, height_data: np.ndarray, dt: float) -> None:
        self._update_distribution(height_data)

        # accuracy: 100 - mean absolute error
        errors = []
        for name, (_lo, _hi, target) in _BIOME_TARGETS.items():
            actual = self._current_dist.get(name, 0.0)
            errors.append(abs(actual - target))
        mean_error = sum(errors) / len(errors) if errors else 0
        self._accuracy = max(0.0, 100.0 - mean_error * 2)
        self._score = int(self._accuracy)

    def _draw_game(self, surface: pygame.Surface) -> None:
        sw, sh = surface.get_size()

        # biome distribution panel on the right side
        panel_w = min(220, sw // 3)
        panel_h = len(_BIOME_TARGETS) * 42 + 30
        px = sw - panel_w - 10
        py = 62
        _draw_panel(surface, pygame.Rect(px, py, panel_w, panel_h), alpha=200)

        y = py + 10
        bar_w = panel_w - 60
        for name, (_lo, _hi, target) in _BIOME_TARGETS.items():
            actual = self._current_dist.get(name, 0.0)
            colour = _BIOME_COLOURS[name]

            # label
            lbl = _font(16).render(name, True, _TEXT_PRIMARY)
            surface.blit(lbl, (px + 8, y))

            # bar background
            bar_x = px + 8
            bar_y = y + 18
            bar_h = 10
            pygame.draw.rect(surface, (40, 45, 60), (bar_x, bar_y, bar_w, bar_h), border_radius=3)

            # actual bar
            actual_w = int(bar_w * min(1.0, actual / 100.0))
            if actual_w > 0:
                pygame.draw.rect(surface, colour, (bar_x, bar_y, actual_w, bar_h), border_radius=3)

            # target marker
            target_x = bar_x + int(bar_w * target / 100.0)
            pygame.draw.line(surface, _TEXT_PRIMARY, (target_x, bar_y - 2), (target_x, bar_y + bar_h + 2), 2)

            # percentage text
            pct_lbl = _font(14).render(f"{actual:.0f}/{target:.0f}%", True, _TEXT_SECONDARY)
            surface.blit(pct_lbl, (bar_x + bar_w + 4, bar_y - 2))

            y += 42

        # overall accuracy
        acc_lbl = _font(20, bold=True).render(f"Match: {self._accuracy:.0f}%", True, _TEXT_ACCENT)
        surface.blit(acc_lbl, (px + 8, y))

    def _finish(self) -> None:
        self._score = int(self._accuracy)
        self._result_text = f"Biome accuracy: {self._accuracy:.0f}%"
        if self._accuracy >= 85:
            self._star_rating = 3
        elif self._accuracy >= 65:
            self._star_rating = 2
        elif self._accuracy >= 40:
            self._star_rating = 1
        else:
            self._star_rating = 0
        super()._finish()


# ── Game Manager ───────────────────────────────────────────────────────────────

_MODE_REGISTRY: dict[str, type[GameMode]] = {
    "dam":       BuildADam,
    "volcano":   VolcanoDefense,
    "watershed": WatershedPuzzle,
    "biome":     BiomeSculpt,
}


class GameManager:
    """Manages the lifecycle of interactive game modes."""

    def __init__(self) -> None:
        self._active: GameMode | None = None
        self._just_started: bool = False
        self._just_ended: bool = False

    def start_game(self, mode_name: str, height_data: np.ndarray) -> bool:
        """Start a game mode by name. Returns True on success."""
        cls = _MODE_REGISTRY.get(mode_name)
        if cls is None:
            return False
        self._active = cls()
        self._active.start(height_data)
        self._just_started = True
        self._just_ended = False
        return True

    def update(self, height_data: np.ndarray, dt: float) -> None:
        if self._active is None:
            return
        still_active = self._active.update(height_data, dt)
        if not still_active:
            self._just_ended = True
            self._active = None

    def draw(self, surface: pygame.Surface) -> None:
        if self._active is not None:
            self._active.draw(surface)

    def end_game(self) -> None:
        """End the current game early."""
        if self._active is not None:
            self._just_ended = True
            self._active = None

    def is_active(self) -> bool:
        return self._active is not None

    def get_status(self) -> dict:
        """Dashboard-safe snapshot of the active game (no private access)."""
        if self._active is None:
            return {"active": False}
        game = self._active
        time_left = (
            max(0.0, game.time_limit - game.get_elapsed()) if game.time_limit > 0 else None
        )
        return {
            "active": True,
            "mode": game.name,
            "score": game.get_score(),
            "time_left": round(time_left, 1) if time_left is not None else None,
        }

    def pop_started(self) -> bool:
        """Return True once when a game just started (for sound triggers)."""
        if self._just_started:
            self._just_started = False
            return True
        return False

    def pop_ended(self) -> bool:
        """Return True once when a game just ended (for sound triggers)."""
        if self._just_ended:
            self._just_ended = False
            return True
        return False

    @staticmethod
    def get_available_modes() -> list[str]:
        return list(_MODE_REGISTRY.keys())

    @staticmethod
    def get_mode_names() -> dict[str, str]:
        """Mode id -> display name, e.g. {"dam": "Build a Dam"}."""
        return {key: cls.name for key, cls in _MODE_REGISTRY.items()}
