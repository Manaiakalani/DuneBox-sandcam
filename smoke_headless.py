"""Headless launch smoke test for the AR sandbox pipeline.

Exercises the real runtime pipeline (depth sensor -> renderer -> creatures ->
interaction -> day/night) for a handful of frames using the procedural
``dummy`` sensor and SDL's dummy video/audio drivers, so it runs without any
hardware or display. It is intended for CI: a non-zero exit means the core
update/draw loop regressed.

Run: ``python smoke_headless.py [frames]`` (default 30).
"""

from __future__ import annotations

import os
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame
from sensor_api import create_sensor
from renderer import Renderer
from creatures import CreatureManager
from interaction_engine import InteractionEngine
from day_night import DayNightCycle

WIDTH, HEIGHT = 240, 180


def run(frames: int = 30) -> int:
    pygame.init()
    # convert_alpha() and sprite ops require an initialised video mode; the
    # dummy SDL driver provides one without a real window.
    pygame.display.set_mode((WIDTH, HEIGHT))
    surface = pygame.Surface((WIDTH, HEIGHT))

    sensor = create_sensor(
        {"sensor_type": "dummy", "sensor_fallback": "dummy"},
        width=WIDTH,
        height=HEIGHT,
    )
    renderer = Renderer(WIDTH, HEIGHT)
    creatures = CreatureManager(n_sharks=2, n_dinos=2)
    interactions = InteractionEngine()
    day_night = DayNightCycle(cycle_duration=10.0)

    dt = 1.0 / 30.0
    now = 0.0

    for i in range(frames):
        frame = sensor.get_depth_frame()
        if frame is None:
            print(f"frame {i}: sensor returned None", file=sys.stderr)
            return 1
        if frame.shape != (HEIGHT, WIDTH):
            print(f"frame {i}: unexpected shape {frame.shape}", file=sys.stderr)
            return 1

        renderer.draw(surface, frame, show_contours=True)
        creatures.update(frame, dt)
        creatures.draw(surface, frame)
        interactions.update([], frame, now, reactions_enabled=True)
        interactions.draw(surface)
        day_night.update(dt)
        now += dt

    pygame.quit()
    print(f"Headless smoke OK: {frames} frames rendered cleanly.")
    return 0


if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 30
    sys.exit(run(n))
