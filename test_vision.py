from __future__ import annotations

import time
import unittest
from unittest.mock import patch

import numpy as np

from interaction_engine import InteractionEngine
from webcam_observer import (
    ARUCO_DICTIONARY_NAME,
    CORNER_MARKER_IDS,
    OBJECT_KIND_BY_MARKER,
    CameraTestResult,
    CalibrationData,
    VisionObject,
    calibration_from_corner_markers,
    list_cameras,
    map_camera_to_sandbox,
)


class VisionTests(unittest.TestCase):
    def test_corner_marker_calibration_builds_when_all_corners_present(self) -> None:
        calibration = calibration_from_corner_markers(
            [
                (100, (10.0, 20.0)),
                (101, (110.0, 20.0)),
                (102, (110.0, 120.0)),
                (103, (10.0, 120.0)),
            ]
        )
        self.assertIsNotNone(calibration)
        assert calibration is not None
        self.assertTrue(calibration.ready)
        self.assertEqual(CORNER_MARKER_IDS[102], "bottom_right")
        self.assertEqual(CORNER_MARKER_IDS[103], "bottom_left")
        self.assertEqual(ARUCO_DICTIONARY_NAME, "DICT_4X4_250")
        self.assertIn(20, OBJECT_KIND_BY_MARKER)
        self.assertIn(21, OBJECT_KIND_BY_MARKER)

    def test_printed_corner_ids_build_uncrossed_homography(self) -> None:
        # Filenames: TL-100, TR-101, BR-102, BL-103.
        calibration = calibration_from_corner_markers(
            [
                (100, (10.0, 10.0)),
                (101, (110.0, 10.0)),
                (102, (110.0, 110.0)),
                (103, (10.0, 110.0)),
            ]
        )
        self.assertIsNotNone(calibration)
        assert calibration is not None
        mapped = map_camera_to_sandbox((110.0, 110.0), calibration, (200, 200))
        self.assertGreater(mapped[0], 150)
        self.assertGreater(mapped[1], 150)

    def test_homography_maps_camera_center_to_scene_center(self) -> None:
        calibration = CalibrationData(
            camera_points=((10.0, 10.0), (110.0, 10.0), (110.0, 110.0), (10.0, 110.0))
        )
        mapped = map_camera_to_sandbox((60.0, 60.0), calibration, (200, 200))
        self.assertAlmostEqual(mapped[0], 99.5, delta=1.0)
        self.assertAlmostEqual(mapped[1], 99.5, delta=1.0)

    def test_boat_in_water_emits_event(self) -> None:
        frame = np.full((80, 80), 0.2, dtype=np.float32)
        engine = InteractionEngine()
        engine.update(
            [
                VisionObject(
                    marker_id=1,
                    kind="boat",
                    camera_pos=(50.0, 50.0),
                    sandbox_pos=(40.0, 40.0),
                    confidence=1.0,
                    stable_for_seconds=1.0,
                    biome_under_object="water",
                )
            ],
            frame,
            time.monotonic(),
            reactions_enabled=True,
        )
        events = engine.pop_events()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].kind, "boat_in_water")

    def test_reactions_disabled_suppresses_object_events(self) -> None:
        frame = np.full((80, 80), 0.2, dtype=np.float32)
        engine = InteractionEngine()
        engine.update(
            [
                VisionObject(
                    marker_id=1,
                    kind="boat",
                    camera_pos=(50.0, 50.0),
                    sandbox_pos=(40.0, 40.0),
                    confidence=1.0,
                    stable_for_seconds=1.0,
                    biome_under_object="water",
                )
            ],
            frame,
            time.monotonic(),
            reactions_enabled=False,
        )
        self.assertEqual(engine.pop_events(), [])

    def test_camera_discovery_lists_only_working_cameras(self) -> None:
        with patch(
            "webcam_observer.test_camera",
            side_effect=[
                CameraTestResult(True, "Camera 0 is working at 1280x720."),
                CameraTestResult(False, "Camera 1 could not be opened."),
                CameraTestResult(True, "Camera 2 is working at 640x480."),
            ],
        ):
            cameras = list_cameras(max_index=3)
        self.assertEqual([camera.index for camera in cameras], [0, 2])


if __name__ == "__main__":
    unittest.main()
