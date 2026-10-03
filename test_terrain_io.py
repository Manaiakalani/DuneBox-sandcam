"""Snapshot export/reload, the terrain challenge, and timelapse frames."""

from __future__ import annotations

import os
import pathlib
import tempfile
import time
import unittest
from unittest import mock

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import numpy as np
import pygame

import dem_loader
from game_modes import BUILTIN_TARGETS, GameManager, TerrainChallenge, builtin_target
from sensor_api import MouseSimulatorSensor
from timelapse import TimelapseRecorder


class SnapshotExportTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        patcher = mock.patch.object(dem_loader, "SAVED_DIR", pathlib.Path(self._tmp.name))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self._tmp.cleanup)

    def test_export_writes_reloadable_npy_and_dem_in_mm(self) -> None:
        height = np.linspace(0.0, 1.0, 12, dtype=np.float32).reshape(3, 4)
        paths = dem_loader.export_snapshot(height, depth_range_mm=(600, 1100))
        self.assertEqual({p.suffix for p in paths}, {".npy", ".asc"})

        lines = paths[1].read_text(encoding="ascii").splitlines()
        self.assertEqual(lines[0], "ncols 4")
        self.assertEqual(lines[1], "nrows 3")
        self.assertTrue(lines[4].startswith("cellsize "))
        grid = np.array([[float(v) for v in row.split()] for row in lines[6:]])
        np.testing.assert_allclose(grid, height * 500.0, atol=0.06)

        np.testing.assert_allclose(dem_loader.load_snapshot(paths[0].stem), height)

    def test_same_second_exports_get_distinct_names(self) -> None:
        h = np.zeros((2, 2), dtype=np.float32)
        a = dem_loader.export_snapshot(h, depth_range_mm=(0, 100))[0].stem
        b = dem_loader.export_snapshot(h, depth_range_mm=(0, 100))[0].stem
        self.assertNotEqual(a, b)
        self.assertEqual({s["name"] for s in dem_loader.list_snapshots()}, {a, b})

    def test_png_written_from_surface(self) -> None:
        pygame.init()
        try:
            surf = pygame.Surface((8, 6))
            paths = dem_loader.export_snapshot(
                np.zeros((6, 8), dtype=np.float32), depth_range_mm=(0, 100), image=surf
            )
        finally:
            pygame.quit()
        self.assertTrue(any(p.suffix == ".png" and p.stat().st_size > 0 for p in paths))

    def test_snapshot_path_rejects_unsafe_names(self) -> None:
        for name in ("../ui", "terrain_1", "terrain_20260101_000000/../x", ""):
            self.assertIsNone(dem_loader.snapshot_path(name))
        self.assertIsNone(dem_loader.snapshot_path("terrain_20260101_000000", ".py"))
        with self.assertRaises(FileNotFoundError):
            dem_loader.load_snapshot("terrain_20260101_000000")

    def test_fit_to_is_exact_for_awkward_ratios(self) -> None:
        out = dem_loader.fit_to(np.random.rand(7, 13).astype(np.float32), (240, 320))
        self.assertEqual(out.shape, (240, 320))

    def test_simulator_loads_any_size_terrain(self) -> None:
        sim = MouseSimulatorSensor(64, 48)
        sim.load_terrain(np.full((10, 10), 0.8, dtype=np.float32))
        frame = sim.get_frame()
        self.assertEqual(frame.shape, (48, 64))
        self.assertAlmostEqual(float(frame.mean()), 0.8, places=4)


class TerrainChallengeTests(unittest.TestCase):
    def test_matching_target_wins_and_mismatch_scores_low(self) -> None:
        target = builtin_target("island", (120, 160))
        game = TerrainChallenge(target="island")
        game.start(target)
        for _ in range(16):
            game.update(target, 0.25)
        self.assertTrue(game.is_complete())
        self.assertGreaterEqual(game.get_score(), 90)

        flat = np.full((120, 160), 0.9, dtype=np.float32)
        miss = TerrainChallenge(target="island")
        miss.start(flat)
        self.assertLess(miss.get_score(), 30)
        self.assertFalse(miss.is_complete())

    def test_saved_target_any_size(self) -> None:
        manager = GameManager()
        frame = np.full((96, 128), 0.5, dtype=np.float32)
        self.assertTrue(manager.start_game(
            "challenge", frame, target=np.full((30, 30), 0.5, dtype=np.float32), target_name="Saved"
        ))
        manager.update(frame, 0.3)
        self.assertGreaterEqual(manager.get_status()["score"], 99)

    def test_builtin_targets_are_valid_height_maps(self) -> None:
        for key in BUILTIN_TARGETS:
            t = builtin_target(key, (30, 40))
            self.assertEqual(t.shape, (30, 40))
            self.assertGreater(float(t.max() - t.min()), 0.2)
            self.assertTrue(0.0 <= float(t.min()) and float(t.max()) <= 1.0)

    def test_hint_overlay_draws(self) -> None:
        pygame.init()
        try:
            game = TerrainChallenge(target="valley")
            game.start(np.full((60, 80), 0.5, dtype=np.float32))
            surf = pygame.Surface((80, 60))
            game.draw(surf)
            self.assertGreater(int(pygame.surfarray.array3d(surf).max()), 0)
        finally:
            pygame.quit()


class TimelapseTests(unittest.TestCase):
    def test_records_on_interval_and_stops_cleanly(self) -> None:
        pygame.init()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                rec = TimelapseRecorder(root=pathlib.Path(tmp), interval=1.0)
                folder = rec.start()
                surf = pygame.Surface((16, 12))
                rec.update(100.0, surf)
                rec.update(100.5, surf)  # inside the interval: skipped
                rec.update(101.0, surf)
                done, frames = rec.stop()
                self.assertEqual(done, folder)
                self.assertEqual(frames, 2)
                self.assertFalse(rec.active)
                deadline = time.monotonic() + 2
                while len(list(folder.glob("frame_*.png"))) < 2 and time.monotonic() < deadline:
                    time.sleep(0.05)
                self.assertEqual(sorted(p.name for p in folder.glob("*.png")),
                                 ["frame_00001.png", "frame_00002.png"])
        finally:
            pygame.quit()


if __name__ == "__main__":
    unittest.main()
