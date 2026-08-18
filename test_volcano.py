"""Volcano manager tests: snap-or-reuse placement and public marker API."""

from __future__ import annotations

import unittest

import numpy as np

from volcano import (
    MARKER_EXTINCTION,
    MARKER_VOLCANO_PLACE,
    MARKER_VOLCANO_TRIGGER,
    EruptionState,
    VolcanoManager,
)


class VolcanoManagerTests(unittest.TestCase):
    def test_place_volcano_reuses_nearby_vent(self) -> None:
        mgr = VolcanoManager(200, 160)
        first = mgr.place_volcano(50, 50)
        second = mgr.place_volcano(55, 52)
        self.assertEqual(first, second)
        self.assertEqual(mgr.count(), 1)

    def test_place_volcano_creates_second_when_far(self) -> None:
        mgr = VolcanoManager(200, 160)
        mgr.place_volcano(20, 20)
        mgr.place_volcano(160, 140)
        self.assertEqual(mgr.count(), 2)

    def test_marker_place_is_debounced(self) -> None:
        mgr = VolcanoManager(200, 160)
        mgr.handle_marker(MARKER_VOLCANO_PLACE, (80.0, 90.0))
        mgr.handle_marker(MARKER_VOLCANO_PLACE, (140.0, 40.0))
        self.assertEqual(mgr.count(), 1)

    def test_extinction_marker_is_debounced(self) -> None:
        mgr = VolcanoManager(200, 160)
        mgr.place_volcano(40, 40)
        mgr.handle_marker(MARKER_EXTINCTION, (40.0, 40.0))
        first_state = mgr._volcanoes[0].state
        mgr._volcanoes[0].state = EruptionState.DORMANT
        mgr.handle_marker(MARKER_EXTINCTION, (40.0, 40.0))
        self.assertEqual(mgr._volcanoes[0].state, EruptionState.DORMANT)
        self.assertEqual(first_state, EruptionState.RUMBLING)

    def test_trigger_marker_starts_eruption(self) -> None:
        mgr = VolcanoManager(200, 160)
        mgr.place_volcano(80, 90)
        mgr.handle_marker(MARKER_VOLCANO_TRIGGER, (80.0, 90.0))
        self.assertTrue(mgr.is_erupting())
        mgr.handle_marker(MARKER_VOLCANO_TRIGGER, (80.0, 90.0))
        self.assertEqual(sum(1 for v in mgr._volcanoes if v.state == EruptionState.RUMBLING), 1)

    def test_flowing_reaches_cooling(self) -> None:
        mgr = VolcanoManager(64, 64)
        mgr.place_volcano(32, 32)
        mgr.trigger_eruption(0)
        terrain = np.full((64, 64), 0.5, dtype=np.float32)
        for _ in range(int(20 / 0.05)):
            mgr.update(terrain, 0.05)
        self.assertFalse(mgr.is_erupting())
        self.assertEqual(mgr.get_shake_offset(), (0, 0))

    def test_resize_scales_vent_coordinates(self) -> None:
        mgr = VolcanoManager(100, 100)
        mgr.place_volcano(25, 50)
        mgr.resize(200, 200)
        self.assertEqual(mgr.count(), 1)
        self.assertEqual(mgr.nearest_volcano(50, 100), 0)


if __name__ == "__main__":
    unittest.main()
