"""
Ambient and event sound effects for DuneBox-sandcam.

Uses pygame.mixer for low-latency audio playback with volume control
and spatial positioning.
"""

from __future__ import annotations

import pathlib

import numpy as np
import pygame

from renderer import WATER_LEVEL

_SOUND_DIR = pathlib.Path(__file__).with_name("assets") / "sounds"

_AMBIENT_FADE_SPEED = 1.0  # full volume change per second (1–2 s crossfade)

# Sound file names keyed by logical name
_AMBIENT_FILES = {
    "water": "water_ambient.wav",
    "wind": "wind_ambient.wav",
}

_EVENT_FILES = {
    "creature_spawn": "creature_spawn.wav",
    "creature_despawn": "creature_despawn.wav",
    "marker_detected": "marker_detected.wav",
    "marker_lost": "marker_lost.wav",
}

# Volume categories
_CATEGORY_AMBIENT = "ambient"
_CATEGORY_EVENTS = "events"


class SoundManager:
    """Manages ambient loops and one-shot event sounds."""

    def __init__(self, enabled: bool = True) -> None:
        self._enabled = enabled
        self._muted = False
        self._master_volume = 0.7
        self._category_volumes = {
            _CATEGORY_AMBIENT: 0.6,
            _CATEGORY_EVENTS: 0.8,
        }

        # Current ambient target/actual volumes for smooth fading
        self._ambient_target: dict[str, float] = {}
        self._ambient_actual: dict[str, float] = {}

        # Loaded sounds
        self._ambient_channels: dict[str, pygame.mixer.Channel] = {}
        self._ambient_sounds: dict[str, pygame.mixer.Sound] = {}
        self._event_sounds: dict[str, pygame.mixer.Sound] = {}

        if not self._enabled:
            return

        try:
            if not pygame.mixer.get_init():
                pygame.mixer.init(frequency=44100, size=-16, channels=2, buffer=1024)
            # Reserve channels: 0-1 for ambient, 2+ for events
            pygame.mixer.set_num_channels(16)
        except pygame.error:
            self._enabled = False
            return

        self._load_sounds()
        self._start_ambient_loops()

    def _load_sounds(self) -> None:
        for name, filename in _AMBIENT_FILES.items():
            path = _SOUND_DIR / filename
            if path.exists():
                try:
                    self._ambient_sounds[name] = pygame.mixer.Sound(str(path))
                except pygame.error:
                    pass

        for name, filename in _EVENT_FILES.items():
            path = _SOUND_DIR / filename
            if path.exists():
                try:
                    self._event_sounds[name] = pygame.mixer.Sound(str(path))
                except pygame.error:
                    pass

    def _start_ambient_loops(self) -> None:
        channel_index = 0
        for name, sound in self._ambient_sounds.items():
            try:
                ch = pygame.mixer.Channel(channel_index)
                ch.play(sound, loops=-1)
                ch.set_volume(0.0)
                self._ambient_channels[name] = ch
                self._ambient_target[name] = 0.0
                self._ambient_actual[name] = 0.0
                channel_index += 1
            except (pygame.error, IndexError):
                pass

    def update(self, height_data: np.ndarray, dt: float) -> None:
        """Call every frame. Adjusts ambient volumes based on terrain."""
        if not self._enabled:
            return

        # Wind always plays at a base level
        self._ambient_target["wind"] = 0.5

        # Water volume scales with fraction of terrain below water level
        if height_data is not None and height_data.size > 0:
            water_fraction = float(np.mean(height_data < WATER_LEVEL))
            self._ambient_target["water"] = min(1.0, water_fraction * 2.0)
        else:
            self._ambient_target["water"] = 0.0

        # Smoothly fade ambient channels toward their targets
        for name, channel in self._ambient_channels.items():
            target = self._ambient_target.get(name, 0.0)
            actual = self._ambient_actual.get(name, 0.0)

            if abs(target - actual) < 0.01:
                actual = target
            else:
                step = _AMBIENT_FADE_SPEED * dt
                if actual < target:
                    actual = min(target, actual + step)
                else:
                    actual = max(target, actual - step)
            self._ambient_actual[name] = actual

            effective = self._effective_volume(actual, _CATEGORY_AMBIENT)
            try:
                channel.set_volume(effective)
            except pygame.error:
                pass

    def play_event(self, event: str) -> None:
        """Play a one-shot event sound by name."""
        if not self._enabled or self._muted:
            return
        sound = self._event_sounds.get(event)
        if sound is None:
            return
        vol = self._effective_volume(1.0, _CATEGORY_EVENTS)
        sound.set_volume(vol)
        try:
            sound.play()
        except pygame.error:
            pass

    def set_master_volume(self, vol: float) -> None:
        self._master_volume = max(0.0, min(1.0, vol))

    def toggle_mute(self) -> bool:
        """Toggle mute state. Returns the new muted state."""
        self._muted = not self._muted
        if self._muted:
            for ch in self._ambient_channels.values():
                try:
                    ch.set_volume(0.0)
                except pygame.error:
                    pass
        return self._muted

    def cleanup(self) -> None:
        """Stop all sounds and release resources."""
        if not self._enabled:
            return
        for ch in self._ambient_channels.values():
            try:
                ch.stop()
            except pygame.error:
                pass
        self._ambient_channels.clear()
        try:
            pygame.mixer.stop()
        except pygame.error:
            pass

    def _effective_volume(self, base: float, category: str) -> float:
        if self._muted:
            return 0.0
        cat_vol = self._category_volumes.get(category, 1.0)
        return base * cat_vol * self._master_volume
