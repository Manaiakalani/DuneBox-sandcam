"""
Volcano eruption system with particle effects and lava flow.

ArUco markers trigger eruptions at specific positions. Lava flows
downhill following terrain, cools over time, and interacts with water.
"""

from __future__ import annotations

import math
import random
from enum import Enum, auto

import numpy as np
import pygame

from renderer import WATER_LEVEL


def _shift(a: np.ndarray, dy: int, dx: int, mode: str) -> np.ndarray:
    """Shift ``a`` so result[i, j] == a[i - dy, j - dx] without wrap-around.

    ``mode="edge"`` replicates the border (used for neighbour sampling so the
    height difference across a boundary is zero -> no flow off the grid).
    ``mode="constant"`` fills with zeros (used when redistributing flow so lava
    leaving the grid is dropped rather than teleported to the opposite edge).
    """
    ady, adx = abs(dy), abs(dx)
    ap = np.pad(a, ((ady, ady), (adx, adx)), mode=mode)
    h, w = a.shape
    return ap[ady - dy: ady - dy + h, adx - dx: adx - dx + w]


# ── Eruption states ───────────────────────────────────────────────────────────

class EruptionState(Enum):
    DORMANT = auto()
    RUMBLING = auto()
    ERUPTING = auto()
    FLOWING = auto()
    COOLING = auto()


# ── Timing constants ─────────────────────────────────────────────────────────

_RUMBLE_DURATION = 2.0
_ERUPTION_DURATION = 5.0
_COOLING_DURATION = 15.0

# ── Lava simulation ─────────────────────────────────────────────────────────

_LAVA_FLOW_RATE = 0.06       # slower than water (viscous)
_LAVA_SIM_STEPS = 1
_LAVA_COOL_RATE = 0.012      # temperature decay per second
_LAVA_SOURCE_RATE = 0.008    # lava added at vent per frame-second
_LAVA_EVAPORATION = 0.9995   # gentle volume loss

# ── Colours ──────────────────────────────────────────────────────────────────

_HOT_LAVA = (255, 180, 30)
_WARM_LAVA = (200, 50, 10)
_COOL_LAVA = (60, 15, 5)
_CRUST_LAVA = (30, 10, 5)
_CALDERA_GLOW = (200, 80, 20)
_SMOKE_COLOR = (100, 100, 100)
_STEAM_COLOR = (220, 220, 240)
_ASH_COLOR = (60, 55, 50)


# ── Particle dataclass ───────────────────────────────────────────────────────

class _Particle:
    __slots__ = ("x", "y", "vx", "vy", "life", "max_life", "kind", "size", "color")

    def __init__(
        self,
        x: float,
        y: float,
        vx: float,
        vy: float,
        life: float,
        kind: str,
        size: float = 2.0,
        color: tuple[int, int, int] = (255, 255, 255),
    ) -> None:
        self.x = x
        self.y = y
        self.vx = vx
        self.vy = vy
        self.life = life
        self.max_life = life
        self.kind = kind
        self.size = size
        self.color = color


# ── Volcano ──────────────────────────────────────────────────────────────────

class _Volcano:
    """A single volcano instance with position, state, and timing."""

    def __init__(self, x: int, y: int) -> None:
        self.x = x
        self.y = y
        self.state = EruptionState.DORMANT
        self.timer = 0.0
        self.glow_phase = 0.0  # pulsing caldera glow


# ── VolcanoManager ───────────────────────────────────────────────────────────

class VolcanoManager:
    """Manages volcanoes, particles, lava flow, and screen shake."""

    def __init__(self, width: int, height: int) -> None:
        self._w = width
        self._h = height
        self._volcanoes: list[_Volcano] = []
        self._particles: list[_Particle] = []

        # Lava coverage and temperature fields
        self._lava = np.zeros((height, width), dtype=np.float32)
        self._temperature = np.zeros((height, width), dtype=np.float32)

        # Screen shake state
        self._shake_intensity = 0.0
        self._shake_offset = (0, 0)

        # Sound events emitted this frame (consumed by main loop)
        self._sound_events: list[str] = []

        # Pre-computed lava surface (rebuilt each frame during draw)
        self._lava_surface: pygame.Surface | None = None

    # ── public API ────────────────────────────────────────────────────

    def place_volcano(self, x: int, y: int) -> int:
        """Place a volcano at (x, y). Returns index."""
        v = _Volcano(int(x), int(y))
        self._volcanoes.append(v)
        return len(self._volcanoes) - 1

    def trigger_eruption(self, volcano_index: int = 0) -> None:
        """Start an eruption on the given volcano (if dormant or cooling)."""
        if volcano_index < 0 or volcano_index >= len(self._volcanoes):
            return
        v = self._volcanoes[volcano_index]
        if v.state in (EruptionState.DORMANT, EruptionState.COOLING):
            v.state = EruptionState.RUMBLING
            v.timer = _RUMBLE_DURATION
            self._sound_events.append("volcano_rumble")

    def trigger_all(self) -> None:
        """Trigger every volcano (extinction event)."""
        for i in range(len(self._volcanoes)):
            self.trigger_eruption(i)

    def nearest_volcano(self, x: int, y: int) -> int:
        """Return index of the volcano nearest to (x, y), or -1."""
        best_idx = -1
        best_dist = float("inf")
        for i, v in enumerate(self._volcanoes):
            d = math.hypot(v.x - x, v.y - y)
            if d < best_dist:
                best_dist = d
                best_idx = i
        return best_idx

    def is_erupting(self) -> bool:
        """True if any volcano is actively erupting or flowing."""
        return any(
            v.state in (EruptionState.RUMBLING, EruptionState.ERUPTING, EruptionState.FLOWING)
            for v in self._volcanoes
        )

    def get_lava_map(self) -> np.ndarray:
        """Return lava coverage array (H, W) with values 0.0–1.0."""
        return self._lava

    def get_shake_offset(self) -> tuple[int, int]:
        """Return current screen shake offset (dx, dy)."""
        return self._shake_offset

    def pop_sound_events(self) -> list[str]:
        """Return and clear pending sound events."""
        events = self._sound_events
        self._sound_events = []
        return events

    # ── update ────────────────────────────────────────────────────────

    def update(self, height_data: np.ndarray, dt: float) -> None:
        """Advance volcanoes, particles, lava flow, and cooling."""
        dt = min(dt, 0.1)  # clamp to avoid explosions on lag spikes

        for v in self._volcanoes:
            self._update_volcano_state(v, dt)
            self._emit_particles(v, dt)

        self._update_particles(dt)
        self._update_lava_flow(height_data, dt)
        self._update_cooling(dt)
        self._update_shake(dt)
        self._check_steam(height_data)

    def _update_volcano_state(self, v: _Volcano, dt: float) -> None:
        v.timer -= dt
        v.glow_phase += dt * 3.0

        if v.state == EruptionState.RUMBLING:
            self._shake_intensity = max(self._shake_intensity, 5.0)
            if v.timer <= 0:
                v.state = EruptionState.ERUPTING
                v.timer = _ERUPTION_DURATION
                self._sound_events.append("volcano_eruption")

        elif v.state == EruptionState.ERUPTING:
            self._shake_intensity = max(self._shake_intensity, 8.0)
            # Add lava at vent
            self._add_lava_source(v.x, v.y, radius=12, amount=_LAVA_SOURCE_RATE * dt * 60)
            if v.timer <= 0:
                v.state = EruptionState.FLOWING
                v.timer = 0.0

        elif v.state == EruptionState.FLOWING:
            self._shake_intensity = max(self._shake_intensity, 2.0)
            # Keep adding lava at a diminishing rate
            rate = _LAVA_SOURCE_RATE * 0.3 * dt * 60
            self._add_lava_source(v.x, v.y, radius=8, amount=rate)
            # Transition to cooling when lava flow velocity is negligible
            total_lava = float(np.sum(self._lava))
            if total_lava < 0.5:
                v.state = EruptionState.COOLING
                v.timer = _COOLING_DURATION

        elif v.state == EruptionState.COOLING:
            if v.timer <= 0:
                v.state = EruptionState.DORMANT
                v.timer = 0.0

    def _add_lava_source(self, cx: int, cy: int, radius: int, amount: float) -> None:
        y0 = max(0, cy - radius)
        y1 = min(self._h, cy + radius)
        x0 = max(0, cx - radius)
        x1 = min(self._w, cx + radius)
        yy, xx = np.ogrid[y0:y1, x0:x1]
        dist2 = (xx - cx) ** 2 + (yy - cy) ** 2
        mask = dist2 <= radius * radius
        self._lava[y0:y1, x0:x1][mask] += amount
        self._temperature[y0:y1, x0:x1][mask] = np.maximum(
            self._temperature[y0:y1, x0:x1][mask], 1.0
        )
        np.clip(self._lava, 0.0, 1.0, out=self._lava)

    # ── particle emission ─────────────────────────────────────────────

    def _emit_particles(self, v: _Volcano, dt: float) -> None:
        if v.state == EruptionState.DORMANT:
            return

        cx, cy = float(v.x), float(v.y)

        if v.state == EruptionState.RUMBLING:
            # Smoke rising from caldera
            for _ in range(int(6 * dt * 60)):
                self._particles.append(_Particle(
                    cx + random.uniform(-6, 6), cy + random.uniform(-6, 6),
                    random.uniform(-0.3, 0.3), random.uniform(-1.5, -0.6),
                    random.uniform(1.0, 2.5), "smoke",
                    size=random.uniform(4, 8), color=_SMOKE_COLOR,
                ))

        elif v.state == EruptionState.ERUPTING:
            # Lava sparks shooting upward
            for _ in range(int(20 * dt * 60)):
                angle = random.uniform(-0.8, 0.8)
                speed = random.uniform(2.0, 6.0)
                self._particles.append(_Particle(
                    cx + random.uniform(-4, 4), cy,
                    math.sin(angle) * speed, -math.cos(angle) * speed - 1.5,
                    random.uniform(0.5, 1.5), "spark",
                    size=random.uniform(1.5, 3.0),
                    color=(255, random.randint(140, 220), random.randint(10, 60)),
                ))
            # Dense smoke plume
            for _ in range(int(10 * dt * 60)):
                self._particles.append(_Particle(
                    cx + random.uniform(-8, 8), cy + random.uniform(-4, 2),
                    random.uniform(-0.5, 0.5), random.uniform(-2.5, -1.0),
                    random.uniform(1.5, 3.5), "smoke",
                    size=random.uniform(6, 12), color=_SMOKE_COLOR,
                ))
            # Ash falling in wide radius
            for _ in range(int(4 * dt * 60)):
                self._particles.append(_Particle(
                    cx + random.uniform(-60, 60), cy + random.uniform(-60, 0),
                    random.uniform(-0.15, 0.15), random.uniform(0.2, 0.6),
                    random.uniform(2.0, 5.0), "ash",
                    size=random.uniform(1, 2), color=_ASH_COLOR,
                ))

        elif v.state == EruptionState.FLOWING:
            # Residual smoke
            for _ in range(int(3 * dt * 60)):
                self._particles.append(_Particle(
                    cx + random.uniform(-5, 5), cy + random.uniform(-3, 3),
                    random.uniform(-0.2, 0.2), random.uniform(-1.0, -0.4),
                    random.uniform(1.0, 2.0), "smoke",
                    size=random.uniform(3, 6), color=_SMOKE_COLOR,
                ))

    def _update_particles(self, dt: float) -> None:
        alive: list[_Particle] = []
        gravity = 3.0
        for p in self._particles:
            p.life -= dt
            if p.life <= 0:
                continue
            p.x += p.vx * dt * 60
            p.y += p.vy * dt * 60
            if p.kind == "spark":
                p.vy += gravity * dt
            elif p.kind == "ash":
                p.vx += random.uniform(-0.05, 0.05)
            alive.append(p)
        self._particles = alive

    # ── lava flow (cellular automata, viscous) ────────────────────────

    def _update_lava_flow(self, terrain: np.ndarray, dt: float) -> None:
        lava = self._lava
        if float(np.max(lava)) < 1e-6:
            return

        # Resize terrain to match lava grid if needed
        if terrain.shape != lava.shape:
            from scipy.ndimage import zoom
            terrain = zoom(terrain, (self._h / terrain.shape[0], self._w / terrain.shape[1]), order=0)

        for _ in range(_LAVA_SIM_STEPS):
            surface = terrain + lava
            for dy, dx in ((0, 1), (0, -1), (1, 0), (-1, 0)):
                # Edge-clamp the neighbour so boundary cells see themselves
                # (diff == 0) and never flow lava off the edge of the grid.
                neighbour = _shift(surface, dy, dx, "edge")
                diff = surface - neighbour
                # Viscosity: flow is slower than water
                flow = np.clip(diff * _LAVA_FLOW_RATE, 0.0, lava)
                lava -= flow
                # Zero-fill so flow that would leave the grid is dropped rather
                # than wrapping around to the opposite side.
                lava += _shift(flow, -dy, -dx, "constant")
                surface = terrain + lava

        lava *= _LAVA_EVAPORATION
        np.clip(lava, 0.0, 1.0, out=self._lava)

    def _update_cooling(self, dt: float) -> None:
        # Temperature decays over time
        self._temperature -= _LAVA_COOL_RATE * dt * 60
        np.clip(self._temperature, 0.0, 1.0, out=self._temperature)
        # Where there's no lava, temperature is zero
        self._temperature[self._lava < 1e-4] = 0.0

    def _update_shake(self, dt: float) -> None:
        if self._shake_intensity > 0.1:
            ix = int(self._shake_intensity)
            self._shake_offset = (
                random.randint(-ix, ix),
                random.randint(-ix, ix),
            )
            self._shake_intensity *= max(0.0, 1.0 - 2.0 * dt)
        else:
            self._shake_intensity = 0.0
            self._shake_offset = (0, 0)

    def _check_steam(self, height_data: np.ndarray) -> None:
        """Emit steam where lava meets water."""
        if float(np.max(self._lava)) < 1e-4:
            return
        # Resize height_data if needed
        hd = height_data
        if hd.shape != self._lava.shape:
            from scipy.ndimage import zoom
            hd = zoom(hd, (self._h / hd.shape[0], self._w / hd.shape[1]), order=0)

        # Find cells where lava is present and terrain is below water level
        steam_mask = (self._lava > 0.01) & (hd < WATER_LEVEL)
        steam_ys, steam_xs = np.where(steam_mask)
        if len(steam_ys) == 0:
            return

        # Emit a few steam particles at random steam locations
        n = min(6, len(steam_ys))
        indices = random.sample(range(len(steam_ys)), n)
        sizzle_emitted = False
        for idx in indices:
            sx, sy = float(steam_xs[idx]), float(steam_ys[idx])
            self._particles.append(_Particle(
                sx + random.uniform(-2, 2), sy + random.uniform(-2, 2),
                random.uniform(-0.3, 0.3), random.uniform(-1.5, -0.5),
                random.uniform(0.5, 1.5), "steam",
                size=random.uniform(3, 6), color=_STEAM_COLOR,
            ))
            if not sizzle_emitted:
                self._sound_events.append("lava_sizzle")
                sizzle_emitted = True

    # ── draw ──────────────────────────────────────────────────────────

    def draw(self, surface: pygame.Surface) -> None:
        """Draw lava coverage and particles onto the scene surface."""
        self._draw_lava(surface)
        self._draw_caldera_indicators(surface)
        self._draw_particles(surface)

    def _draw_lava(self, surface: pygame.Surface) -> None:
        """Render lava as a coloured RGBA overlay based on temperature."""
        if float(np.max(self._lava)) < 1e-4:
            return

        w, h = self._w, self._h
        rgba = np.zeros((h, w, 4), dtype=np.uint8)

        temp = self._temperature
        lava_mask = self._lava > 0.005

        # Interpolate colour: hot → warm → cool → crust based on temperature
        r = np.where(lava_mask,
            np.clip(temp * _HOT_LAVA[0] + (1 - temp) * _CRUST_LAVA[0], 0, 255), 0
        ).astype(np.uint8)
        g = np.where(lava_mask,
            np.clip(temp * _HOT_LAVA[1] + (1 - temp) * _CRUST_LAVA[1], 0, 255), 0
        ).astype(np.uint8)
        b = np.where(lava_mask,
            np.clip(temp * _HOT_LAVA[2] + (1 - temp) * _CRUST_LAVA[2], 0, 255), 0
        ).astype(np.uint8)
        a = np.where(lava_mask,
            np.clip(self._lava * 255 * 3, 0, 230), 0
        ).astype(np.uint8)

        rgba[..., 0] = r
        rgba[..., 1] = g
        rgba[..., 2] = b
        rgba[..., 3] = a

        lava_surf = pygame.image.frombuffer(
            rgba.tobytes(), (w, h), "RGBA"
        ).convert_alpha()
        surface.blit(lava_surf, (0, 0))

    def _draw_caldera_indicators(self, surface: pygame.Surface) -> None:
        """Draw pulsing glow circles at volcano positions."""
        for v in self._volcanoes:
            pulse = 0.5 + 0.5 * math.sin(v.glow_phase)
            alpha = int(60 + 80 * pulse)
            radius = int(8 + 4 * pulse)
            glow = pygame.Surface((radius * 2, radius * 2), pygame.SRCALPHA)
            color = (*_CALDERA_GLOW, alpha)
            pygame.draw.circle(glow, color, (radius, radius), radius)
            surface.blit(glow, (v.x - radius, v.y - radius))

    def _draw_particles(self, surface: pygame.Surface) -> None:
        for p in self._particles:
            frac = max(0.0, p.life / p.max_life)
            alpha = int(255 * frac)
            if alpha < 5:
                continue

            ix, iy = int(p.x), int(p.y)
            if ix < 0 or ix >= self._w or iy < 0 or iy >= self._h:
                continue

            sz = max(1, int(p.size * (0.5 + 0.5 * frac)))

            if p.kind == "smoke":
                # Smoke grows as it fades
                sz = max(1, int(p.size * (1.0 + 0.5 * (1 - frac))))
                smoke_alpha = int(alpha * 0.6)
                s = pygame.Surface((sz * 2, sz * 2), pygame.SRCALPHA)
                pygame.draw.circle(s, (*p.color, smoke_alpha), (sz, sz), sz)
                surface.blit(s, (ix - sz, iy - sz))
            elif p.kind == "spark":
                pygame.draw.circle(surface, p.color, (ix, iy), sz)
            elif p.kind == "ash":
                ash_alpha = int(alpha * 0.4)
                s = pygame.Surface((3, 3), pygame.SRCALPHA)
                s.fill((*p.color, ash_alpha))
                surface.blit(s, (ix, iy))
            elif p.kind == "steam":
                sz = max(1, int(p.size * (1.0 + 0.3 * (1 - frac))))
                steam_alpha = int(alpha * 0.5)
                s = pygame.Surface((sz * 2, sz * 2), pygame.SRCALPHA)
                pygame.draw.circle(s, (*p.color, steam_alpha), (sz, sz), sz)
                surface.blit(s, (ix - sz, iy - sz))
