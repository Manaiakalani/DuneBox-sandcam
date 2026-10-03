import unittest

import numpy as np

from health import SurfaceHealth


class SurfaceHealthTests(unittest.TestCase):
    def test_measures_after_two_samples(self):
        h = SurfaceHealth()
        frame = np.full((120, 160), 0.5, np.float32)
        h.update(0.0, frame, 400)
        self.assertEqual(h.in_range_pct, 100.0)
        self.assertIsNone(h.noise_mm)
        h.update(1.0, frame + 0.01, 400)
        self.assertAlmostEqual(h.noise_mm, 4.0, places=1)

    def test_rate_limited(self):
        h = SurfaceHealth()
        frame = np.full((40, 40), 0.5, np.float32)
        h.update(0.0, frame, 400)
        h.update(0.5, frame + 0.2, 400)
        self.assertIsNone(h.noise_mm)

    def test_clipped_pixels_count_as_out_of_range(self):
        h = SurfaceHealth()
        frame = np.full((40, 40), 0.5, np.float32)
        frame[:, :20] = 0.0
        h.update(0.0, frame, 400)
        self.assertEqual(h.in_range_pct, 50.0)

    def test_ignores_small_local_changes(self):
        h = SurfaceHealth()
        frame = np.full((80, 80), 0.5, np.float32)
        h.update(0.0, frame, 400)
        moved = frame.copy()
        moved[:4, :] = 0.9  # a hand over one edge
        h.update(1.0, moved, 400)
        self.assertEqual(h.noise_mm, 0.0)

    def test_none_frame(self):
        h = SurfaceHealth()
        h.update(0.0, None, 400)
        self.assertEqual(h.as_dict(), {"noise_mm": None, "in_range_pct": None})


if __name__ == "__main__":
    unittest.main()
