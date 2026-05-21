"""
Startup diagnostics — detects and reports hardware status.

Shows a brief diagnostics screen on launch with green/red/yellow indicators
for each subsystem, then auto-proceeds. Use ``--diagnostics`` for extended
mode that waits for a keypress.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field

import pygame


# ── Status model ──────────────────────────────────────────────────────────────

@dataclass
class DiagnosticItem:
    label: str
    status: str  # "ok", "warn", "error"
    detail: str

    @property
    def indicator(self) -> str:
        return {"ok": "✓", "warn": "⚠", "error": "✗"}.get(self.status, "?")

    @property
    def color(self) -> tuple[int, int, int]:
        return {
            "ok": (80, 200, 120),
            "warn": (230, 190, 60),
            "error": (220, 70, 70),
        }.get(self.status, (160, 160, 160))


@dataclass
class DiagnosticReport:
    items: list[DiagnosticItem] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(i.status == "ok" for i in self.items)


# ── Probe functions ───────────────────────────────────────────────────────────

def _check_kinect() -> DiagnosticItem:
    """Try to import freenect ctypes wrapper and detect a device."""
    try:
        from depth_source import KinectV1Source
        # Try to open — constructor probes hardware
        src = KinectV1Source.__new__(KinectV1Source)
        # Check if the low-level library is loadable
        import ctypes, pathlib
        dll_path = pathlib.Path(__file__).with_name("freenect.dll")
        so_names = ["libfreenect.so", "libfreenect.dylib"]
        lib = None
        if dll_path.exists():
            lib = ctypes.CDLL(str(dll_path))
        else:
            for name in so_names:
                try:
                    lib = ctypes.CDLL(name)
                    break
                except OSError:
                    continue
        if lib is None:
            return DiagnosticItem("Kinect", "warn", "freenect library not found")
        return DiagnosticItem("Kinect", "ok", "freenect library available")
    except Exception as exc:
        return DiagnosticItem("Kinect", "error", str(exc)[:60])


def _check_displays() -> DiagnosticItem:
    try:
        sizes = pygame.display.get_desktop_sizes()
        n = len(sizes)
        detail = f"{n} display(s) — " + ", ".join(f"{w}×{h}" for w, h in sizes)
        status = "ok" if n >= 1 else "warn"
        return DiagnosticItem("Displays", status, detail)
    except Exception as exc:
        return DiagnosticItem("Displays", "error", str(exc)[:60])


def _check_python() -> DiagnosticItem:
    v = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    return DiagnosticItem("Python", "ok", v)


def _check_pygame() -> DiagnosticItem:
    return DiagnosticItem("pygame", "ok", pygame.version.ver)


def _check_opencv() -> DiagnosticItem:
    try:
        import cv2
        return DiagnosticItem("OpenCV", "ok", cv2.__version__)
    except ImportError:
        return DiagnosticItem("OpenCV", "warn", "not installed")


def _check_sound() -> DiagnosticItem:
    try:
        if pygame.mixer.get_init():
            freq, size, channels = pygame.mixer.get_init()
            return DiagnosticItem(
                "Sound", "ok", f"{freq} Hz, {channels}ch, {abs(size)}-bit"
            )
        return DiagnosticItem("Sound", "warn", "mixer not initialized")
    except Exception as exc:
        return DiagnosticItem("Sound", "error", str(exc)[:60])


def _check_settings() -> DiagnosticItem:
    import pathlib

    cfg = pathlib.Path(__file__).with_name("sandcam-settings.json")
    if cfg.exists():
        return DiagnosticItem("Settings", "ok", "sandcam-settings.json found")
    return DiagnosticItem("Settings", "warn", "using defaults")


def _check_webcam() -> DiagnosticItem:
    try:
        import cv2
        cap = cv2.VideoCapture(0)
        if cap.isOpened():
            cap.release()
            return DiagnosticItem("Webcam", "ok", "camera 0 available")
        cap.release()
        return DiagnosticItem("Webcam", "warn", "no camera detected")
    except ImportError:
        return DiagnosticItem("Webcam", "warn", "OpenCV required")
    except Exception as exc:
        return DiagnosticItem("Webcam", "error", str(exc)[:60])


# ── Full probe ────────────────────────────────────────────────────────────────

def run_diagnostics() -> DiagnosticReport:
    """Execute all hardware probes and return a report."""
    report = DiagnosticReport()
    report.items.append(_check_python())
    report.items.append(_check_pygame())
    report.items.append(_check_displays())
    report.items.append(_check_kinect())
    report.items.append(_check_opencv())
    report.items.append(_check_webcam())
    report.items.append(_check_sound())
    report.items.append(_check_settings())
    return report


# ── Drawing ───────────────────────────────────────────────────────────────────

_BG = (14, 18, 26)
_CARD_BG = (22, 28, 40, 238)
_CARD_BORDER = (72, 124, 188)
_TITLE_COLOR = (220, 228, 238)
_DETAIL_COLOR = (150, 162, 178)


def draw_diagnostics(
    screen: pygame.Surface,
    report: DiagnosticReport,
    *,
    extended: bool = False,
) -> None:
    """Render the diagnostics overlay onto *screen*."""
    screen.fill(_BG)

    try:
        title_font = pygame.font.SysFont("consolas,menlo,monospace", 22, bold=True)
        row_font = pygame.font.SysFont("consolas,menlo,monospace", 16)
        hint_font = pygame.font.SysFont("consolas,menlo,monospace", 13)
    except Exception:
        title_font = pygame.font.SysFont(None, 24, bold=True)
        row_font = pygame.font.SysFont(None, 18)
        hint_font = pygame.font.SysFont(None, 15)

    row_h = 28
    pad = 20
    panel_w = min(560, screen.get_width() - 60)
    panel_h = 60 + row_h * len(report.items) + (30 if extended else 0)
    px = (screen.get_width() - panel_w) // 2
    py = (screen.get_height() - panel_h) // 2

    # Card background
    card = pygame.Surface((panel_w, panel_h), pygame.SRCALPHA)
    pygame.draw.rect(card, _CARD_BG, card.get_rect(), border_radius=12)
    pygame.draw.rect(card, _CARD_BORDER, card.get_rect(), width=2, border_radius=12)
    screen.blit(card, (px, py))

    # Title
    title = title_font.render("DuneBox Diagnostics", True, _TITLE_COLOR)
    screen.blit(title, (px + pad, py + pad))

    # Rows
    y = py + pad + 34
    for item in report.items:
        indicator = row_font.render(item.indicator, True, item.color)
        screen.blit(indicator, (px + pad, y))

        label = row_font.render(item.label, True, _TITLE_COLOR)
        screen.blit(label, (px + pad + 24, y))

        detail = row_font.render(item.detail, True, _DETAIL_COLOR)
        max_detail_w = panel_w - pad * 2 - 160
        if detail.get_width() > max_detail_w:
            detail = row_font.render(item.detail[: max_detail_w // 8] + "…", True, _DETAIL_COLOR)
        screen.blit(detail, (px + pad + 160, y))

        y += row_h

    if extended:
        hint = hint_font.render("Press any key to continue…", True, (100, 110, 130))
        screen.blit(hint, (px + pad, y + 6))

    pygame.display.flip()


# ── Startup entry-point ───────────────────────────────────────────────────────

def show_startup_diagnostics(
    screen: pygame.Surface,
    *,
    extended: bool = False,
    brief_seconds: float = 2.0,
) -> bool:
    """
    Run probes, display results, then auto-proceed (or wait for keypress).

    Returns False if the user closed the window during diagnostics.
    """
    report = run_diagnostics()
    draw_diagnostics(screen, report, extended=extended)

    if extended:
        # Wait for any keypress or window close
        waiting = True
        while waiting:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    return False
                if event.type == pygame.KEYDOWN:
                    waiting = False
                    break
    else:
        # Brief flash — show for a fixed duration
        deadline = pygame.time.get_ticks() + int(brief_seconds * 1000)
        while pygame.time.get_ticks() < deadline:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    return False
                if event.type == pygame.KEYDOWN:
                    return True  # dismiss early on keypress
            pygame.time.wait(30)

    return True
