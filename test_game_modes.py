"""Game water sim should not wrap across opposite edges."""

from __future__ import annotations

import unittest

import numpy as np

from game_modes import GameManager, water_sim_step


class WaterSimTests(unittest.TestCase):
    def test_water_does_not_wrap_around_edges(self) -> None:
        terrain = np.full((16, 16), 0.4, dtype=np.float32)
        water = np.zeros((16, 16), dtype=np.float32)
        water[0, 0] = 1.0
        water_sim_step(terrain, water, dt=1.0)
        self.assertLess(float(water[-1, -1]), 1e-4)
        self.assertLess(float(water[-1, 0]), 1e-4)
        self.assertLess(float(water[0, -1]), 1e-4)

    def test_game_manager_status_when_idle(self) -> None:
        mgr = GameManager()
        self.assertEqual(mgr.get_status(), {"active": False})
        self.assertIn("dam", mgr.get_available_modes())


if __name__ == "__main__":
    unittest.main()
