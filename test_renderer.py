"""Renderer hot-path tests: LUT, contours, and hillshade stay in-place."""

from __future__ import annotations

import unittest

import numpy as np
import pygame

from renderer import WATER_LEVEL, Renderer


class RendererTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        pygame.init()
        pygame.display.set_mode((80, 60))

    @classmethod
    def tearDownClass(cls) -> None:
        pygame.quit()

    def test_draw_produces_varied_pixels(self) -> None:
        renderer = Renderer(80, 60)
        target = pygame.Surface((80, 60))
        height = np.linspace(0.0, 1.0, 80 * 60, dtype=np.float32).reshape(60, 80)
        renderer.draw(target, height, show_contours=True, colour_scheme="terrain")
        pixels = pygame.surfarray.array3d(target)
        self.assertGreater(int(pixels.max()) - int(pixels.min()), 20)

    def test_water_pixels_are_blueish(self) -> None:
        renderer = Renderer(32, 32)
        target = pygame.Surface((32, 32))
        height = np.full((32, 32), WATER_LEVEL - 0.2, dtype=np.float32)
        renderer.draw(target, height, show_contours=False, colour_scheme="terrain")
        pixels = pygame.surfarray.array3d(target)
        blue = int(pixels[:, :, 2].mean())
        red = int(pixels[:, :, 0].mean())
        self.assertGreater(blue, red)


if __name__ == "__main__":
    unittest.main()
