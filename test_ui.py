"""Config-level behaviour shared by the sidebar and the dashboard."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import ui
from ui import SMOOTHING_PRESETS, Config, apply_smoothing_preset, smoothing_preset_of


class SmoothingPresetTests(unittest.TestCase):
    def test_defaults_match_balanced(self) -> None:
        self.assertEqual(smoothing_preset_of(Config()), "balanced")

    def test_each_preset_round_trips_and_flags_the_filter(self) -> None:
        for name in SMOOTHING_PRESETS:
            config = Config()
            config.filter_changed = False
            self.assertTrue(apply_smoothing_preset(config, name))
            self.assertEqual(smoothing_preset_of(config), name)
            self.assertTrue(config.filter_changed)

    def test_hand_tuned_values_are_custom(self) -> None:
        config = Config()
        config.temporal_alpha = 0.42
        self.assertEqual(smoothing_preset_of(config), "custom")

    def test_unknown_preset_is_rejected(self) -> None:
        config = Config()
        self.assertFalse(apply_smoothing_preset(config, "turbo"))
        self.assertEqual(smoothing_preset_of(config), "balanced")


class ContourConfigTests(unittest.TestCase):
    def test_out_of_range_values_are_clamped_on_load(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "settings.json"
            path.write_text(json.dumps({"contour_interval": 5.0, "sea_level_offset": -3.0}))
            with mock.patch.object(ui, "CONFIG_PATH", path):
                config = Config.load()
        self.assertEqual(config.contour_interval, 0.12)
        self.assertEqual(config.sea_level_offset, -0.2)


if __name__ == "__main__":
    unittest.main()
