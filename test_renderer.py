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

    def test_wider_contour_spacing_draws_fewer_lines(self) -> None:
        height = np.tile(np.linspace(0.5, 1.0, 200, dtype=np.float32), (40, 1))

        def dark_pixels(interval: float) -> int:
            renderer = Renderer(200, 40)
            target = pygame.Surface((200, 40))
            renderer.draw(target, height, show_contours=True, contour_interval=interval)
            plain = pygame.Surface((200, 40))
            Renderer(200, 40).draw(plain, height, show_contours=False)
            a = pygame.surfarray.array3d(target).sum(axis=2)
            b = pygame.surfarray.array3d(plain).sum(axis=2)
            return int(np.count_nonzero(a < b * 0.6))

        self.assertGreater(dark_pixels(0.02), dark_pixels(0.1))

    def test_elevation_labels_report_height_above_sea_in_cm(self) -> None:
        pygame.font.init()
        renderer = Renderer(400, 200)
        target = pygame.Surface((400, 200))
        height = np.tile(np.linspace(0.3, 1.0, 400, dtype=np.float32), (200, 1))
        renderer.draw(
            target, height, show_contours=True, contour_interval=0.1, contour_labels_cm_per_unit=50.0,
        )
        texts = {text for _, _, text in renderer._labels}
        self.assertTrue(texts)
        for text in texts:
            cm = float(text)
            # Contours are multiples of 0.1 above the 0.46 waterline: 0.5 -> +2 cm, 0.6 -> +7 cm...
            steps = ((cm / 50.0) + WATER_LEVEL) / 0.1
            self.assertAlmostEqual(steps, round(steps), delta=0.1)
        renderer.draw(target, height, show_contours=True, contour_labels_cm_per_unit=None)
        self.assertEqual(renderer._labels, [])

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
