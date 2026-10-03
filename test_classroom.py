import json
import os
import pathlib
import tempfile
import unittest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import numpy as np
import pygame

from classroom import (
    LessonPlayer,
    Scoreboard,
    draw_lesson,
    draw_scoreboard,
    load_lessons,
    localized,
    measure,
)


class LessonTests(unittest.TestCase):
    def test_bundled_lessons_load_in_both_languages(self):
        lessons = load_lessons()
        self.assertGreaterEqual(set(lessons), {"contours", "islands", "watersheds"})
        for lesson in lessons.values():
            self.assertEqual(lesson.languages, ["en", "es"], lesson.id)

    def test_bad_files_are_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = pathlib.Path(tmp)
            (folder / "broken.json").write_text("{not json", encoding="utf-8")
            (folder / "nosteps.json").write_text(json.dumps({"id": "x", "steps": []}), encoding="utf-8")
            (folder / "badsetting.json").write_text(json.dumps(
                {"id": "y", "steps": [{"title": "a", "settings": {"format": True}}]}
            ), encoding="utf-8")
            (folder / "ok.json").write_text(json.dumps(
                {"id": "ok", "title": "OK", "steps": [{"title": "One", "text": "Do it"}]}
            ), encoding="utf-8")
            self.assertEqual(list(load_lessons(folder)), ["ok"])

    def test_localized(self):
        self.assertEqual(localized({"en": "Hi", "es": "Hola"}, "es"), "Hola")
        self.assertEqual(localized({"en": "Hi"}, "es"), "Hi")
        self.assertEqual(localized("Plain", "es"), "Plain")
        self.assertEqual(localized(None, "en"), "")

    def test_player_steps_and_checks(self):
        player = LessonPlayer(load_lessons())
        self.assertIsNone(player.start("nope"))
        settings = player.start("islands")
        self.assertEqual(settings["sea_level"], 0)
        self.assertFalse(player.update({"below_sea": 0.1}))
        self.assertTrue(player.update({"below_sea": 0.5}))
        self.assertFalse(player.update({"below_sea": 0.5}))   # only fires once
        self.assertTrue(player.active_status("es")["done"])
        self.assertEqual(player.go(3)["sea_level"], 0.1)
        self.assertEqual(player.go(99), {"sea_level": 0})     # clamps to the last step
        status = player.status("es")
        self.assertEqual(status["active"]["step_title"], "Hablemos")
        self.assertEqual(status["active"]["index"], 4)
        player.stop()
        self.assertIsNone(player.status("en")["active"])

    def test_measure(self):
        frame = np.full((40, 40), 0.3, np.float32)
        frame[:, 20:] = 0.8
        m = measure(frame, 0.46)
        self.assertAlmostEqual(m["below_sea"], 0.5)
        self.assertAlmostEqual(m["relief"], 0.5, places=2)
        self.assertEqual(measure(None, 0.46), {})


class ScoreboardTests(unittest.TestCase):
    def test_teams_scores_and_awards(self):
        sb = Scoreboard()
        sb.set_count(3)
        self.assertEqual([t["name"] for t in sb.teams], ["Team A", "Team B", "Team C"])
        self.assertTrue(sb.add(1, 5))
        self.assertFalse(sb.add(7, 5))
        self.assertTrue(sb.rename(0, "  Kahu   kids "))
        self.assertEqual(sb.teams[0]["name"], "Kahu kids")
        self.assertFalse(sb.rename(0, "   "))

        self.assertIsNone(sb.award(0))              # no game yet
        sb.note_game({"active": True, "mode": "Build a Dam", "score": 40})
        sb.note_game({"active": False})
        self.assertEqual(sb.status()["last_game"], {"mode": "Build a Dam", "score": 40})
        self.assertEqual(sb.award(2), 40)
        self.assertIsNone(sb.award(2))              # only once
        self.assertIsNone(sb.status()["last_game"])
        sb.note_game({"active": True, "mode": "Build a Dam", "score": 10})
        self.assertEqual(sb.award(0), 10)           # a new game can be awarded again
        self.assertEqual([t["score"] for t in sb.teams], [10, 5, 40])

        sb.set_count(2)
        self.assertEqual(len(sb.teams), 2)
        sb.reset()
        self.assertEqual([t["score"] for t in sb.teams], [0, 0])


class DrawTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        pygame.init()

    def test_overlays_draw(self):
        screen = pygame.Surface((1280, 800))
        player = LessonPlayer(load_lessons())
        player.start("contours")
        bottom = draw_lesson(screen, player.active_status("es"), "es")
        self.assertGreater(bottom, 60)
        self.assertLess(bottom, 400)
        sb = Scoreboard()
        sb.set_count(4)
        draw_scoreboard(screen, sb.teams)


if __name__ == "__main__":
    unittest.main()
