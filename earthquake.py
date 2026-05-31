"""
Earthquake detection and effects.

Detects rapid depth changes (hand slap gesture) and triggers
shockwave animation, dinosaur stampede, and volcanic eruptions.
"""

from __future__ import annotations

import random
import time

import numpy as np
import pygame


# ── Detection thresholds ─────────────────────────────────────────────────────

_PIXEL_CHANGE_THRESHOLD = 0.1   # min depth change per pixel (normalised 0-1)
_AREA_FRACTION_THRESHOLD = 0.15  # fraction of pixels that must exceed threshold

# ── Shockwave visuals ────────────────────────────────────────────────────────

_RING_COUNT = 3
_RING_INTERVAL = 0.3             # seconds between ring spawns
_RING_SPEED = 200.0              # px/sec expansion
_RING_LIFETIME = 2.0             # seconds before full fade
_RING_THICKNESS = 4

# ── Screen shake ─────────────────────────────────────────────────────────────

_SHAKE_DURATION = 1.5
_SHAKE_MIN = 5
_SHAKE_MAX = 12


class _ShockwaveRing:
    """A single expanding ring emanating from the epicentre."""

    __slots__ = ("cx", "cy", "radius", "age", "max_life")

    def __init__(self, cx: int, cy: int) -> None:
        self.cx = cx
        self.cy = cy
        self.radius = 0.0
        self.age = 0.0
        self.max_life = _RING_LIFETIME


class EarthquakeDetector:
    """Detects rapid depth changes (hand slap) and manages shockwave effects."""

    def __init__(
        self,
        width: int,
        height: int,
        threshold: float = _AREA_FRACTION_THRESHOLD,
        cooldown: float = 3.0,
    ) -> None:
        self._w = width
        self._h = height
        self._threshold = threshold
        self._cooldown = cooldown

        # Detection state
        self._last_trigger: float = -999.0
        self._active = False
        self._epicenter: tuple[int, int] | None = None
        self._intensity: float = 0.0

        # Shockwave rings
        self._rings: list[_ShockwaveRing] = []
        self._rings_spawned = 0
        self._ring_spawn_timer = 0.0

        # Screen shake
        self._shake_intensity: float = 0.0
        self._shake_timer: float = 0.0
        self._shake_offset: tuple[int, int] = (0, 0)

        # Duration tracking for the whole event
        self._event_timer: float = 0.0

        # Sound events emitted this frame
        self._sound_events: list[str] = []

    # ── public API ────────────────────────────────────────────────────

    def update(
        self,
        height_data: np.ndarray,
        prev_height_data: np.ndarray | None,
        dt: float,
    ) -> bool:
        """Detect earthquake from depth changes. Returns True if triggered this frame."""
        dt = min(dt, 0.1)
        triggered = False

        # Try to detect a new earthquake
        if prev_height_data is not None:
            triggered = self._detect(height_data, prev_height_data)

        # Update ongoing effects
        self._update_rings(dt)
        self._update_shake(dt)

        if self._active:
            self._event_timer -= dt
            if self._event_timer <= 0 and len(self._rings) == 0:
                self._active = False
                self._epicenter = None
                self._intensity = 0.0

        return triggered

    def draw(self, surface: pygame.Surface) -> None:
        """Draw shockwave ring effects."""
        for ring in self._rings:
            self._draw_ring(surface, ring)

    def is_active(self) -> bool:
        return self._active

    def get_epicenter(self) -> tuple[int, int] | None:
        return self._epicenter

    def get_intensity(self) -> float:
        return self._intensity

    def get_shake_offset(self) -> tuple[int, int]:
        return self._shake_offset

    def pop_sound_events(self) -> list[str]:
        events = self._sound_events
        self._sound_events = []
        return events

    def force_trigger(self, cx: int, cy: int, intensity: float = 0.8) -> None:
        """Manually trigger an earthquake at (cx, cy) — for testing via K key."""
        now = time.monotonic()
        if now - self._last_trigger < self._cooldown:
            return
        self._start_event(cx, cy, intensity)

    # ── detection ─────────────────────────────────────────────────────

    def _detect(self, current: np.ndarray, previous: np.ndarray) -> bool:
        now = time.monotonic()
        if now - self._last_trigger < self._cooldown:
            return False

        # Resize if shapes differ
        if current.shape != previous.shape:
            return False

        diff = np.abs(current.astype(np.float32) - previous.astype(np.float32))
        changed_mask = diff > _PIXEL_CHANGE_THRESHOLD
        fraction = float(np.mean(changed_mask))

        if fraction < self._threshold:
            return False

        # Compute epicentre as centroid of highest-change region
        magnitude = float(np.mean(diff[changed_mask]))
        intensity = min(1.0, magnitude / 0.3)

        ys, xs = np.where(changed_mask)
        if len(ys) == 0:
            return False
        cx = int(np.mean(xs))
        cy = int(np.mean(ys))

        self._start_event(cx, cy, intensity)
        return True

    def _start_event(self, cx: int, cy: int, intensity: float) -> None:
        self._last_trigger = time.monotonic()
        self._active = True
        self._epicenter = (cx, cy)
        self._intensity = max(0.3, min(1.0, intensity))
        self._event_timer = 2.5

        # Reset ring spawning
        self._rings.clear()
        self._rings_spawned = 0
        self._ring_spawn_timer = 0.0
        self._spawn_ring()

        # Start screen shake
        shake_px = _SHAKE_MIN + (_SHAKE_MAX - _SHAKE_MIN) * self._intensity
        self._shake_intensity = shake_px
        self._shake_timer = _SHAKE_DURATION

        self._sound_events.append("earthquake_rumble")

    # ── shockwave rings ───────────────────────────────────────────────

    def _spawn_ring(self) -> None:
        if self._epicenter is None:
            return
        ring = _ShockwaveRing(self._epicenter[0], self._epicenter[1])
        self._rings.append(ring)
        self._rings_spawned += 1

    def _update_rings(self, dt: float) -> None:
        # Spawn additional rings at intervals
        if self._active and self._rings_spawned < _RING_COUNT:
            self._ring_spawn_timer += dt
            if self._ring_spawn_timer >= _RING_INTERVAL:
                self._ring_spawn_timer -= _RING_INTERVAL
                self._spawn_ring()

        # Update existing rings
        alive: list[_ShockwaveRing] = []
        for ring in self._rings:
            ring.age += dt
            ring.radius += _RING_SPEED * dt
            if ring.age < ring.max_life:
                alive.append(ring)
        self._rings = alive

    def _draw_ring(self, surface: pygame.Surface, ring: _ShockwaveRing) -> None:
        frac = ring.age / ring.max_life
        alpha = int(180 * (1.0 - frac))
        if alpha < 5:
            return
        r = int(ring.radius)
        if r < 2:
            return

        # White-blue gradient ring
        blue_mix = 0.3 + 0.7 * (1.0 - frac)
        color = (
            int(200 + 55 * (1.0 - blue_mix)),
            int(210 + 45 * (1.0 - blue_mix)),
            int(220 + 35 * blue_mix),
        )

        # Draw onto a temporary surface for alpha blending
        diameter = r * 2 + _RING_THICKNESS * 2
        if diameter < 4:
            return
        ring_surf = pygame.Surface((diameter, diameter), pygame.SRCALPHA)
        centre = (diameter // 2, diameter // 2)
        pygame.draw.circle(ring_surf, (*color, alpha), centre, r, _RING_THICKNESS)

        blit_x = ring.cx - diameter // 2
        blit_y = ring.cy - diameter // 2
        surface.blit(ring_surf, (blit_x, blit_y))

    # ── screen shake ─────────────────────────────────────────────────

    def _update_shake(self, dt: float) -> None:
        if self._shake_timer > 0:
            self._shake_timer -= dt
            # Smooth decay: intensity tapers toward end
            decay = max(0.0, self._shake_timer / _SHAKE_DURATION)
            current_px = int(self._shake_intensity * decay)
            if current_px > 0:
                self._shake_offset = (
                    random.randint(-current_px, current_px),
                    random.randint(-current_px, current_px),
                )
            else:
                self._shake_offset = (0, 0)
        else:
            self._shake_offset = (0, 0)
