"""
Day/night cycle system.

Cycles through dawn → day → dusk → night phases, affecting terrain
lighting, sky color, creature behavior, and ambient sounds.
"""

from __future__ import annotations

import math
import random

import numpy as np
import pygame

# ── Phase boundaries (fraction of the 0.0–1.0 cycle) ─────────────────────────
_NIGHT_1_END = 0.2
_DAWN_END = 0.3
_DAY_END = 0.7
_DUSK_END = 0.8
# Night resumes from 0.8 → 1.0 (wraps to 0.0)

# ── Lighting tints per phase (R, G, B multipliers) ────────────────────────────
_TINT_NIGHT = (0.3, 0.3, 0.5)
_TINT_DAWN = (0.9, 0.7, 0.5)
_TINT_DAY = (1.0, 1.0, 1.0)
_TINT_DUSK = (0.8, 0.6, 0.7)

# ── Sky colours ───────────────────────────────────────────────────────────────
_SKY_NIGHT = (10, 12, 40)
_SKY_DAWN = (180, 110, 70)
_SKY_DAY = (135, 195, 235)
_SKY_DUSK = (140, 90, 110)

# ── Stars ─────────────────────────────────────────────────────────────────────
_MAX_STARS = 120
_STAR_SEED = 42


def _lerp_colour(
    a: tuple[float, ...],
    b: tuple[float, ...],
    t: float,
) -> tuple[float, ...]:
    return tuple(a[i] + (b[i] - a[i]) * t for i in range(len(a)))


def _lerp_int_colour(
    a: tuple[int, ...],
    b: tuple[int, ...],
    t: float,
) -> tuple[int, ...]:
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(len(a)))


class DayNightCycle:
    """Manages a continuous day/night cycle with smooth phase transitions."""

    def __init__(self, cycle_duration: float = 120.0) -> None:
        self._cycle_duration = max(1.0, cycle_duration)
        self._time = 0.0  # seconds elapsed
        self._speed = 1.0
        self._paused = False

        # Pre-generate star positions (normalised 0-1)
        rng = random.Random(_STAR_SEED)
        self._star_positions = [
            (rng.random(), rng.random() * 0.6)
            for _ in range(_MAX_STARS)
        ]
        self._star_base_alpha = [rng.randint(120, 255) for _ in range(_MAX_STARS)]

    # ── core tick ─────────────────────────────────────────────────────────────

    def update(self, dt: float) -> None:
        if self._paused:
            return
        self._time += dt * self._speed

    # ── queries ───────────────────────────────────────────────────────────────

    def get_time_of_day(self) -> float:
        """0.0 (midnight) → 0.25 (dawn) → 0.5 (noon) → 0.75 (dusk) → 1.0."""
        return (self._time % self._cycle_duration) / self._cycle_duration

    def get_phase(self) -> str:
        t = self.get_time_of_day()
        if t < _NIGHT_1_END:
            return "night"
        if t < _DAWN_END:
            return "dawn"
        if t < _DAY_END:
            return "day"
        if t < _DUSK_END:
            return "dusk"
        return "night"

    def get_light_multiplier(self) -> float:
        """0.3 (night) to 1.0 (day), with smooth transitions."""
        t = self.get_time_of_day()
        if t < _NIGHT_1_END:
            return 0.3
        if t < _DAWN_END:
            blend = (t - _NIGHT_1_END) / (_DAWN_END - _NIGHT_1_END)
            return 0.3 + 0.7 * blend
        if t < _DAY_END:
            return 1.0
        if t < _DUSK_END:
            blend = (t - _DAY_END) / (_DUSK_END - _DAY_END)
            return 1.0 - 0.7 * blend
        return 0.3

    def get_sky_tint(self) -> tuple[int, int, int]:
        t = self.get_time_of_day()
        if t < _NIGHT_1_END:
            return _SKY_NIGHT
        if t < _DAWN_END:
            blend = (t - _NIGHT_1_END) / (_DAWN_END - _NIGHT_1_END)
            r, g, b = _lerp_int_colour(_SKY_NIGHT, _SKY_DAWN, blend)
            return (r, g, b)
        if t < (_DAWN_END + _DAY_END) / 2:
            blend = (t - _DAWN_END) / ((_DAY_END - _DAWN_END) / 2)
            blend = min(1.0, blend)
            r, g, b = _lerp_int_colour(_SKY_DAWN, _SKY_DAY, blend)
            return (r, g, b)
        if t < _DAY_END:
            return _SKY_DAY
        if t < _DUSK_END:
            blend = (t - _DAY_END) / (_DUSK_END - _DAY_END)
            r, g, b = _lerp_int_colour(_SKY_DAY, _SKY_DUSK, blend)
            return (r, g, b)
        # night ramp-in
        blend = (t - _DUSK_END) / (1.0 - _DUSK_END)
        r, g, b = _lerp_int_colour(_SKY_DUSK, _SKY_NIGHT, blend)
        return (r, g, b)

    def get_ambient_color(self) -> tuple[int, int, int, int]:
        """RGBA overlay for the scene (low-alpha wash)."""
        r, g, b = self.get_sky_tint()
        phase = self.get_phase()
        if phase == "night":
            return (r, g, b, 45)
        if phase in ("dawn", "dusk"):
            return (r, g, b, 25)
        return (r, g, b, 0)

    def get_terrain_tint(self) -> tuple[float, float, float]:
        """RGB multiplier for terrain rendering (smooth transitions)."""
        t = self.get_time_of_day()
        if t < _NIGHT_1_END:
            return _TINT_NIGHT
        if t < _DAWN_END:
            blend = (t - _NIGHT_1_END) / (_DAWN_END - _NIGHT_1_END)
            r, g, b = _lerp_colour(_TINT_NIGHT, _TINT_DAWN, blend)
            return (r, g, b)
        if t < (_DAWN_END + _DAY_END) / 2:
            blend = (t - _DAWN_END) / ((_DAY_END - _DAWN_END) / 2)
            blend = min(1.0, blend)
            r, g, b = _lerp_colour(_TINT_DAWN, _TINT_DAY, blend)
            return (r, g, b)
        if t < _DAY_END:
            return _TINT_DAY
        if t < _DUSK_END:
            blend = (t - _DAY_END) / (_DUSK_END - _DAY_END)
            r, g, b = _lerp_colour(_TINT_DAY, _TINT_DUSK, blend)
            return (r, g, b)
        blend = (t - _DUSK_END) / (1.0 - _DUSK_END)
        r, g, b = _lerp_colour(_TINT_DUSK, _TINT_NIGHT, blend)
        return (r, g, b)

    # ── controls ──────────────────────────────────────────────────────────────

    def set_speed(self, multiplier: float) -> None:
        self._speed = max(0.1, multiplier)

    def get_speed(self) -> float:
        return self._speed

    def adjust_speed(self, delta: float) -> float:
        """Nudge the cycle speed and return the new multiplier."""
        self.set_speed(self._speed + delta)
        return self._speed

    def toggle_pause(self) -> None:
        self._paused = not self._paused

    def is_paused(self) -> bool:
        return self._paused

    # ── drawing helpers ───────────────────────────────────────────────────────

    def draw_sky_effects(
        self,
        surface: pygame.Surface,
        height_data: np.ndarray | None = None,
    ) -> None:
        """Draw stars, moon, and sun on the given surface."""
        w, h = surface.get_size()
        t = self.get_time_of_day()

        # Ambient colour overlay
        ar, ag, ab, aa = self.get_ambient_color()
        if aa > 0:
            overlay = pygame.Surface((w, h), pygame.SRCALPHA)
            overlay.fill((ar, ag, ab, aa))
            surface.blit(overlay, (0, 0))

        # Stars during night (fade in/out at edges)
        night_intensity = self._night_intensity(t)
        if night_intensity > 0.05:
            self._draw_stars(surface, night_intensity, w, h)
            self._draw_moon(surface, night_intensity, t, w, h)

        # Sun during day
        day_intensity = self._day_intensity(t)
        if day_intensity > 0.05:
            self._draw_sun(surface, day_intensity, t, w, h)

    def draw_phase_hud(
        self,
        surface: pygame.Surface,
        font: pygame.font.Font,
        x: int,
        y: int,
    ) -> None:
        """Draw phase name and time-of-day bar."""
        phase = self.get_phase()
        t = self.get_time_of_day()
        paused_tag = " [paused]" if self._paused else ""
        speed_tag = f" x{self._speed:.1f}" if self._speed != 1.0 else ""

        label = f"{phase.capitalize()}{speed_tag}{paused_tag}"
        text = font.render(label, True, (220, 220, 200))
        shadow = font.render(label, True, (0, 0, 0))
        surface.blit(shadow, (x + 1, y + 1))
        surface.blit(text, (x, y))

        # Small time-of-day bar
        bar_w, bar_h = 60, 4
        bar_x = x
        bar_y = y + text.get_height() + 2
        pygame.draw.rect(surface, (40, 40, 50), (bar_x, bar_y, bar_w, bar_h))
        fill_w = int(bar_w * t)
        colour = {
            "night": (60, 60, 140),
            "dawn": (220, 160, 80),
            "day": (240, 220, 100),
            "dusk": (180, 120, 140),
        }.get(phase, (200, 200, 200))
        pygame.draw.rect(surface, colour, (bar_x, bar_y, fill_w, bar_h))

    # ── internal drawing ──────────────────────────────────────────────────────

    @staticmethod
    def _night_intensity(t: float) -> float:
        """0-1 how 'night-like' the current time is (for stars/moon)."""
        if t < _NIGHT_1_END:
            return 1.0
        if t < _DAWN_END:
            return 1.0 - (t - _NIGHT_1_END) / (_DAWN_END - _NIGHT_1_END)
        if t < _DAY_END:
            return 0.0
        if t < _DUSK_END:
            return (t - _DAY_END) / (_DUSK_END - _DAY_END)
        return 1.0

    @staticmethod
    def _day_intensity(t: float) -> float:
        if t < _NIGHT_1_END:
            return 0.0
        if t < _DAWN_END:
            return (t - _NIGHT_1_END) / (_DAWN_END - _NIGHT_1_END)
        if t < _DAY_END:
            return 1.0
        if t < _DUSK_END:
            return 1.0 - (t - _DAY_END) / (_DUSK_END - _DAY_END)
        return 0.0

    def _draw_stars(
        self,
        surface: pygame.Surface,
        intensity: float,
        w: int,
        h: int,
    ) -> None:
        tick = pygame.time.get_ticks()
        for i, (sx, sy) in enumerate(self._star_positions):
            px = int(sx * w)
            py = int(sy * h)
            # Twinkle: offset phase per star
            twinkle = 0.5 + 0.5 * math.sin(tick * 0.003 + i * 1.7)
            alpha = int(self._star_base_alpha[i] * intensity * twinkle)
            alpha = max(0, min(255, alpha))
            if alpha < 15:
                continue
            size = 1 if self._star_base_alpha[i] < 200 else 2
            star_surf = pygame.Surface((size * 2, size * 2), pygame.SRCALPHA)
            pygame.draw.circle(star_surf, (255, 255, 240, alpha), (size, size), size)
            surface.blit(star_surf, (px - size, py - size))

    @staticmethod
    def _draw_moon(
        surface: pygame.Surface,
        intensity: float,
        t: float,
        w: int,
        h: int,
    ) -> None:
        # Moon sits in the upper-right area, moving slightly
        moon_x = int(w * 0.85)
        moon_y = int(h * 0.08)
        radius = max(8, min(18, w // 50))
        alpha = int(200 * intensity)
        moon = pygame.Surface((radius * 3, radius * 3), pygame.SRCALPHA)
        pygame.draw.circle(moon, (230, 230, 200, alpha), (radius + 1, radius + 1), radius)
        # Crescent shadow
        pygame.draw.circle(
            moon,
            (0, 0, 0, 0),
            (radius + 1 + radius // 3, radius + 1 - radius // 6),
            radius - 2,
        )
        # Glow
        glow_r = radius + 6
        glow = pygame.Surface((glow_r * 2, glow_r * 2), pygame.SRCALPHA)
        pygame.draw.circle(glow, (180, 190, 220, int(40 * intensity)), (glow_r, glow_r), glow_r)
        surface.blit(glow, (moon_x - glow_r, moon_y - glow_r))
        surface.blit(moon, (moon_x - radius - 1, moon_y - radius - 1))

    @staticmethod
    def _draw_sun(
        surface: pygame.Surface,
        intensity: float,
        t: float,
        w: int,
        h: int,
    ) -> None:
        # Sun arcs across the top portion of the screen
        # t: 0.2→0.8 maps to left→right
        progress = (t - 0.2) / 0.6  # 0→1 across the day
        progress = max(0.0, min(1.0, progress))
        sun_x = int(w * (0.1 + 0.8 * progress))
        # Parabolic arc: highest at noon
        arc = 1.0 - 4.0 * (progress - 0.5) ** 2
        sun_y = int(h * (0.06 + 0.08 * (1.0 - arc)))
        radius = max(6, min(14, w // 60))
        alpha = int(180 * intensity)
        if alpha < 10:
            return
        # Glow
        glow_r = radius + 8
        glow = pygame.Surface((glow_r * 2, glow_r * 2), pygame.SRCALPHA)
        pygame.draw.circle(glow, (255, 230, 120, int(50 * intensity)), (glow_r, glow_r), glow_r)
        surface.blit(glow, (sun_x - glow_r, sun_y - glow_r))
        # Disc
        sun = pygame.Surface((radius * 2 + 2, radius * 2 + 2), pygame.SRCALPHA)
        pygame.draw.circle(sun, (255, 240, 100, alpha), (radius + 1, radius + 1), radius)
        surface.blit(sun, (sun_x - radius - 1, sun_y - radius - 1))
