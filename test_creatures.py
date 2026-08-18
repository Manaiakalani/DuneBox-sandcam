"""Creature manager tests: marker pins survive set_targets; stampede does not stack."""

from __future__ import annotations

import unittest

import numpy as np
import pygame

from creatures import CreatureManager, MARKER_DINO_SPAWN, TRex


class CreatureManagerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        pygame.init()
        pygame.display.set_mode((64, 64))

    @classmethod
    def tearDownClass(cls) -> None:
        pygame.quit()

    def _land_frame(self, size: int = 80) -> np.ndarray:
        return np.full((size, size), 0.7, dtype=np.float32)

    def test_marker_spawned_trex_survives_set_targets(self) -> None:
        mgr = CreatureManager(n_sharks=1, n_dinos=1)
        frame = self._land_frame()
        self.assertTrue(mgr.spawn_at(TRex, 40.0, 40.0, frame))
        self.assertTrue(any(isinstance(c, TRex) for c in mgr._creatures))

        mgr.set_targets(sharks=1, dinosaurs=1)
        self.assertTrue(any(isinstance(c, TRex) for c in mgr._creatures))

    def test_spawn_at_searches_nearby_valid_land(self) -> None:
        mgr = CreatureManager(n_sharks=0, n_dinos=0)
        frame = np.full((80, 80), 0.2, dtype=np.float32)
        frame[10:25, 10:25] = 0.7
        self.assertTrue(mgr.spawn_at(TRex, 5.0, 5.0, frame))
        self.assertEqual(mgr.counts()["prehistoric"], 1)

    def test_failed_marker_does_not_debounce_or_roar(self) -> None:
        mgr = CreatureManager(n_sharks=0, n_dinos=0)
        frame = np.full((80, 80), 0.2, dtype=np.float32)
        marker_id = next(iter(MARKER_DINO_SPAWN))
        self.assertEqual(mgr.handle_marker(marker_id, (40.0, 40.0), frame), [])
        frame[20:60, 20:60] = 0.7
        events = mgr.handle_marker(marker_id, (40.0, 40.0), frame)
        self.assertTrue(events)

    def test_pinned_death_does_not_respawn_ambient(self) -> None:
        mgr = CreatureManager(n_sharks=0, n_dinos=0)
        frame = self._land_frame()
        self.assertTrue(mgr.spawn_at(TRex, 40.0, 40.0, frame))
        water = np.full((80, 80), 0.2, dtype=np.float32)
        mgr.update(water, 0.016)
        self.assertEqual(mgr.counts()["prehistoric"], 0)
        mgr.update(self._land_frame(), 0.016)
        self.assertEqual(mgr.counts()["prehistoric"], 0)

    def test_set_targets_is_noop_when_counts_unchanged(self) -> None:
        mgr = CreatureManager(n_sharks=2, n_dinos=2)
        before = mgr._creatures
        mgr.set_targets(sharks=2, dinosaurs=2)
        self.assertIs(mgr._creatures, before)

    def test_stampede_does_not_stack_speed(self) -> None:
        mgr = CreatureManager(n_sharks=1, n_dinos=0)
        frame = np.full((80, 80), 0.2, dtype=np.float32)
        mgr.update(frame, 0.016)
        self.assertGreater(len(mgr._creatures), 0)
        original = [c.speed for c in mgr._creatures]
        mgr.trigger_stampede(0, 0)
        after_first = [c.speed for c in mgr._creatures]
        mgr.trigger_stampede(0, 0)
        after_second = [c.speed for c in mgr._creatures]
        for a, b in zip(after_first, after_second, strict=True):
            self.assertAlmostEqual(a, b)
        for before, after in zip(original, after_first, strict=True):
            self.assertAlmostEqual(after, before * 2.0)


if __name__ == "__main__":
    unittest.main()
