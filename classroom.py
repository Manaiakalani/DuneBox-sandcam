"""Classroom tools: step-by-step lessons and a team scoreboard.

Lessons are JSON files in ``lessons/``. Each step can set up the sandbox
(theme, contours, sea level, a game) and can check the sand for a goal, such
as "make a tall mountain". Text can be a plain string or one string per
language, e.g. ``{"en": "Build an island", "es": "Construye una isla"}``.

A lesson file looks like::

    {
      "id": "islands",
      "title": "Islands and rising seas",
      "level": "Ages 9-14",
      "minutes": 20,
      "summary": "…",
      "steps": [
        {"title": "Build an island", "text": "…",
         "settings": {"theme": "terrain", "contours": true, "sea_level": 0},
         "check": {"metric": "below_sea", "min": 0.3, "max": 0.85,
                   "hint": "Leave sea all around it"}}
      ]
    }

Settings: theme, contours, contour_labels, contour_interval, sea_level,
creatures, game (a game id, or "challenge:<landscape>").
Check metrics: below_sea (share of the sand under water, 0-1) and relief
(height between the low and high points, as a share of the depth range).
"""

from __future__ import annotations

import json
import logging
import pathlib
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pygame

logger = logging.getLogger(__name__)

LESSONS_DIR = pathlib.Path(__file__).parent / "lessons"
LANGUAGES = {"en": "English", "es": "Español"}
SETTING_KEYS = {"theme", "contours", "contour_labels", "contour_interval", "sea_level", "creatures", "game"}
METRICS = {"below_sea", "relief"}
MAX_TEAMS = 4
TEAM_LABEL = {"en": "Team", "es": "Equipo"}
TEAM_COLOURS = [(82, 168, 255), (245, 165, 36), (63, 207, 142), (255, 97, 102)]


def localized(value: Any, lang: str) -> str:
    if isinstance(value, dict):
        return str(value.get(lang) or value.get("en") or next(iter(value.values()), ""))
    return "" if value is None else str(value)


@dataclass
class Lesson:
    id: str
    title: Any
    summary: Any
    level: Any
    minutes: int
    steps: list[dict[str, Any]]
    languages: list[str] = field(default_factory=lambda: ["en"])


def _validate(data: dict[str, Any], source: str) -> Lesson:
    steps = data.get("steps")
    if not isinstance(data.get("id"), str) or not isinstance(steps, list) or not steps:
        raise ValueError(f"{source}: needs an id and at least one step")
    langs: set[str] = set()
    for i, step in enumerate(steps):
        if not isinstance(step, dict) or "title" not in step:
            raise ValueError(f"{source}: step {i + 1} needs a title")
        for key in step.get("settings", {}):
            if key not in SETTING_KEYS:
                raise ValueError(f"{source}: step {i + 1} has unknown setting {key!r}")
        check = step.get("check")
        if check is not None and check.get("metric") not in METRICS:
            raise ValueError(f"{source}: step {i + 1} checks an unknown metric")
        for value in (step.get("title"), step.get("text")):
            if isinstance(value, dict):
                langs |= set(value)
    return Lesson(
        id=data["id"],
        title=data.get("title", data["id"]),
        summary=data.get("summary", ""),
        level=data.get("level", ""),
        minutes=int(data.get("minutes", 0)),
        steps=steps,
        languages=sorted(langs & set(LANGUAGES)) or ["en"],
    )


def load_lessons(folder: pathlib.Path = LESSONS_DIR) -> dict[str, Lesson]:
    lessons: dict[str, Lesson] = {}
    for path in sorted(folder.glob("*.json")):
        try:
            lesson = _validate(json.loads(path.read_text(encoding="utf-8")), path.name)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            logger.warning("Skipping lesson %s: %s", path.name, exc)
            continue
        lessons[lesson.id] = lesson
    return lessons


def measure(frame: np.ndarray | None, water_level: float) -> dict[str, float]:
    if frame is None:
        return {}
    sample = frame[::4, ::4]
    lo, hi = np.percentile(sample, [5, 95])
    return {
        "below_sea": round(float(np.mean(sample < water_level)), 3),
        "relief": round(float(hi - lo), 3),
    }


class LessonPlayer:
    def __init__(self, lessons: dict[str, Lesson]) -> None:
        self.lessons = lessons
        self.lesson: Lesson | None = None
        self.index = 0
        self.done = False
        self.metrics: dict[str, float] = {}

    @property
    def step(self) -> dict[str, Any] | None:
        return self.lesson.steps[self.index] if self.lesson else None

    def start(self, lesson_id: str) -> dict[str, Any] | None:
        """Start a lesson; returns the first step's settings, or None if unknown."""
        if lesson_id not in self.lessons:
            return None
        self.lesson = self.lessons[lesson_id]
        return self.go(0)

    def go(self, index: int) -> dict[str, Any]:
        assert self.lesson is not None
        self.index = max(0, min(len(self.lesson.steps) - 1, index))
        self.done = False
        return dict(self.lesson.steps[self.index].get("settings", {}))

    def stop(self) -> None:
        self.lesson = None
        self.index = 0
        self.done = False

    def update(self, metrics: dict[str, float]) -> bool:
        """Re-check the goal; True the moment it's first met."""
        self.metrics = metrics
        step = self.step
        if step is None or self.done or "check" not in step or not metrics:
            return False
        check = step["check"]
        value = metrics.get(check["metric"])
        if value is None:
            return False
        if value >= check.get("min", float("-inf")) and value <= check.get("max", float("inf")):
            self.done = True
            return True
        return False

    def status(self, lang: str) -> dict[str, Any]:
        catalogue = [
            {
                "id": lesson.id,
                "title": localized(lesson.title, lang),
                "summary": localized(lesson.summary, lang),
                "level": localized(lesson.level, lang),
                "minutes": lesson.minutes,
                "steps": len(lesson.steps),
                "languages": lesson.languages,
            }
            for lesson in self.lessons.values()
        ]
        return {"catalogue": catalogue, "active": self.active_status(lang)}

    def active_status(self, lang: str) -> dict[str, Any] | None:
        if self.lesson is None:
            return None
        step = self.step or {}
        check = step.get("check")
        return {
            "id": self.lesson.id,
            "title": localized(self.lesson.title, lang),
            "index": self.index,
            "count": len(self.lesson.steps),
            "step_title": localized(step.get("title"), lang),
            "text": localized(step.get("text"), lang),
            "has_check": check is not None,
            "done": self.done,
            "hint": localized(check.get("hint"), lang) if check and not self.done else "",
        }


class Scoreboard:
    def __init__(self) -> None:
        self.teams: list[dict[str, Any]] = []
        self.visible = True
        self.last_game: dict[str, Any] | None = None
        self.awarded = False
        self._was_active = False

    def set_count(self, count: int, default_name: str = "Team") -> None:
        count = max(0, min(MAX_TEAMS, count))
        while len(self.teams) < count:
            self.teams.append({"name": f"{default_name} {chr(65 + len(self.teams))}", "score": 0})
        del self.teams[count:]

    def add(self, team: int, points: int) -> bool:
        if not 0 <= team < len(self.teams):
            return False
        self.teams[team]["score"] = max(-9999, min(99999, self.teams[team]["score"] + points))
        return True

    def rename(self, team: int, name: str) -> bool:
        name = " ".join(name.split())[:24]
        if not name or not 0 <= team < len(self.teams):
            return False
        self.teams[team]["name"] = name
        return True

    def reset(self) -> None:
        for t in self.teams:
            t["score"] = 0
        self.last_game = None

    def note_game(self, status: dict[str, Any]) -> None:
        """Remember the latest game result so it can be awarded after it ends."""
        active = bool(status.get("active"))
        if active and not self._was_active:
            self.awarded = False
        self._was_active = active
        if active:
            self.last_game = {"mode": status.get("mode"), "score": int(status.get("score") or 0)}

    def award(self, team: int) -> int | None:
        if self.last_game is None or self.awarded or not self.add(team, self.last_game["score"]):
            return None
        self.awarded = True
        return self.last_game["score"]

    def status(self) -> dict[str, Any]:
        return {
            "teams": self.teams,
            "visible": self.visible,
            "last_game": None if self.awarded else self.last_game,
        }


# ── projection overlays ───────────────────────────────────────────────────────

_fonts: dict[tuple[str, int, bool], pygame.font.Font] = {}


def _font(size: int, bold: bool = False) -> pygame.font.Font:
    key = ("segoeui,helvetica,arial", size, bold)
    if key not in _fonts:
        _fonts[key] = pygame.font.SysFont(key[0], size, bold=bold)
    return _fonts[key]


def _wrap(text: str, font: pygame.font.Font, width: int) -> list[str]:
    lines: list[str] = []
    for paragraph in text.splitlines() or [""]:
        line = ""
        for word in paragraph.split():
            trial = f"{line} {word}".strip()
            if font.size(trial)[0] <= width or not line:
                line = trial
            else:
                lines.append(line)
                line = word
        lines.append(line)
    return lines


DONE_LABEL = {"en": "✓ Done", "es": "✓ ¡Hecho!"}


def draw_lesson(screen: pygame.Surface, active: dict[str, Any], lang: str = "en") -> int:
    """Instruction card along the top edge of the projection, readable from a few
    metres. Returns the card's bottom edge."""
    w = screen.get_width()
    card_w = min(w - 48, 900)
    title_font, body_font, meta_font = _font(30, True), _font(24), _font(18, True)
    body = _wrap(active["text"], body_font, card_w - 48)
    hint = active["hint"] if active["has_check"] else ""
    rows = [(meta_font, f"{active['index'] + 1} / {active['count']}  ·  {active['title']}", (161, 161, 161))]
    rows.append((title_font, active["step_title"], (237, 237, 237)))
    rows += [(body_font, line, (220, 220, 220)) for line in body if line]
    if active["done"]:
        rows.append((meta_font, localized(DONE_LABEL, lang), (63, 207, 142)))
    elif hint:
        rows.append((meta_font, hint, (245, 165, 36)))
    height = 32 + sum(f.get_linesize() + 4 for f, _, _ in rows)
    card = pygame.Surface((card_w, height), pygame.SRCALPHA)
    pygame.draw.rect(card, (10, 10, 10, 225), card.get_rect(), border_radius=14)
    y = 16
    for f, text, colour in rows:
        card.blit(f.render(text, True, colour), (24, y))
        y += f.get_linesize() + 4
    screen.blit(card, ((w - card_w) // 2, 16))
    return 16 + height


def draw_scoreboard(screen: pygame.Surface, teams: list[dict[str, Any]]) -> None:
    if not teams:
        return
    name_font, score_font = _font(20, True), _font(34, True)
    col_w = 150
    width = col_w * len(teams) + 16
    panel = pygame.Surface((width, 92), pygame.SRCALPHA)
    pygame.draw.rect(panel, (10, 10, 10, 215), panel.get_rect(), border_radius=12)
    for i, team in enumerate(teams):
        x = 8 + i * col_w
        colour = TEAM_COLOURS[i % len(TEAM_COLOURS)]
        pygame.draw.rect(panel, colour, (x + 12, 14, 4, 64), border_radius=2)
        panel.blit(name_font.render(team["name"][:12], True, (237, 237, 237)), (x + 24, 12))
        panel.blit(score_font.render(str(team["score"]), True, colour), (x + 24, 38))
    screen.blit(panel, (screen.get_width() - width - 16, screen.get_height() - 92 - 40))
