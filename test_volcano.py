"""Volcano manager tests: snap-or-reuse placement and public marker API."""

from __future__ import annotations

import unittest

from volcano import MARKER_VOLCANO_PLACE, VolcanoManager


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

    def test_resize_scales_vent_coordinates(self) -> None:
        mgr = VolcanoManager(100, 100)
        mgr.place_volcano(25, 50)
        mgr.resize(200, 200)
        self.assertEqual(mgr.count(), 1)
        self.assertEqual(mgr.nearest_volcano(50, 100), 0)


if __name__ == "__main__":
    unittest.main()
