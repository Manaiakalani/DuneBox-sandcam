"""Factory tests for the depth-sensor seam."""

from __future__ import annotations

import unittest

import numpy as np

from sensor_api import SENSOR_TYPES, create_sensor


class SensorFactoryTests(unittest.TestCase):
    def test_dummy_sensor_returns_heightfield(self) -> None:
        sensor = create_sensor(
            {"sensor_type": "dummy", "sensor_fallback": "dummy"},
            width=32,
            height=24,
        )
        self.assertTrue(sensor.is_connected())
        frame = sensor.get_frame()
        self.assertEqual(frame.shape, (24, 32))
        self.assertEqual(frame.dtype, np.float32)
        self.assertGreaterEqual(float(frame.min()), 0.0)
        self.assertLessEqual(float(frame.max()), 1.0)

    def test_unknown_type_falls_back_to_mouse_simulator(self) -> None:
        sensor = create_sensor(
            {"sensor_type": "not_a_real_sensor", "sensor_fallback": "mouse_simulator"},
            width=16,
            height=16,
        )
        self.assertIn(sensor.get_sensor_name().lower(), {"mouse simulator", "mouse"})
        frame = sensor.get_frame()
        self.assertEqual(frame.shape, (16, 16))

    def test_registry_includes_dummy_and_mouse(self) -> None:
        self.assertIn("dummy", SENSOR_TYPES)
        self.assertIn("mouse_simulator", SENSOR_TYPES)


if __name__ == "__main__":
    unittest.main()
