"""Physical buttons for visitors: big arcade buttons instead of a keyboard.

Two ways to wire them up, both mapped to actions in the dashboard:

* A USB keypad (or any keyboard): the numeric keypad keys and F13-F15 act as
  buttons. A cheap USB number pad gives 17 buttons with no soldering.
* An Arduino over USB serial running ``hardware/buttons/buttons.ino``. It
  prints one line per press, such as ``BTN 3``.
"""

from __future__ import annotations

import logging
import queue
import re
import threading
import time
from typing import Any

logger = logging.getLogger(__name__)

BAUD = 115200
MAX_SEEN = 24
_LINE_RE = re.compile(r"^(?:BTN\s+)?([A-Za-z0-9_]{1,16})$")

# Known USB-serial chips used by Arduino boards and clones (vendor IDs)
_ARDUINO_VIDS = {0x2341, 0x2A03, 0x1A86, 0x10C4, 0x0403, 0x239A}

# key: (label, command)
BUTTON_ACTIONS: dict[str, tuple[str, dict[str, Any]]] = {
    "none": ("Nothing", {}),
    "erupt_volcano": ("Erupt a volcano", {"action": "erupt_volcano"}),
    "trigger_earthquake": ("Earthquake", {"action": "trigger_earthquake"}),
    "cycle_theme": ("Next colour theme", {"action": "cycle_theme"}),
    "toggle_contours": ("Contour lines on/off", {"action": "toggle_contours"}),
    "toggle_creatures": ("Creatures on/off", {"action": "toggle_creatures"}),
    "toggle_day_night": ("Day and night on/off", {"action": "toggle_day_night"}),
    "sea_up": ("Raise the sea", {"action": "nudge_sea_level", "value": 0.02}),
    "sea_down": ("Lower the sea", {"action": "nudge_sea_level", "value": -0.02}),
    "start_challenge": ("Start the terrain challenge", {"action": "start_challenge", "value": "island"}),
    "end_game": ("End the game", {"action": "end_game"}),
    "save_snapshot": ("Save the terrain", {"action": "save_snapshot"}),
    "wake": ("Wake the sandbox", {"action": "wake"}),
    "dunebox_water": ("DuneBox: water on/off", {"action": "toggle_water", "target": "dunebox"}),
    "dunebox_lava": ("DuneBox: lava on/off", {"action": "toggle_lava", "target": "dunebox"}),
    "dunebox_volcano": ("DuneBox: erupt volcano", {"action": "erupt_volcano", "target": "dunebox"}),
    "dunebox_dry": ("DuneBox: drain water", {"action": "dry_water", "target": "dunebox"}),
    "dunebox_erosion": ("DuneBox: erosion on/off", {"action": "toggle_erosion", "target": "dunebox"}),
}

DEFAULT_MAP = {
    "1": "erupt_volcano",
    "2": "cycle_theme",
    "3": "toggle_contours",
    "4": "sea_up",
    "5": "sea_down",
    "6": "save_snapshot",
}


def button_for_key(key_name: str) -> str | None:
    """Button id for a pygame key name, or None if the key isn't a button.

    Keypad keys are named "[1]", "[+]" and so on; "enter" is the keypad Enter.
    """
    name = key_name.lower()
    if name.startswith("[") and name.endswith("]") and len(name) > 2:
        return "keypad " + name[1:-1]
    if name == "enter":
        return "keypad enter"
    if name in ("f13", "f14", "f15"):
        return name.upper()
    return None


def button_label(button: str) -> str:
    """'keypad 1' -> 'Keypad 1', '3' -> 'Button 3', 'F13' stays."""
    if button.startswith("keypad "):
        return "Keypad " + button[7:]
    return f"Button {button}" if button.isdigit() else button


def clean_map(mapping: object) -> dict[str, str]:
    if not isinstance(mapping, dict):
        return dict(DEFAULT_MAP)
    return {
        str(k)[:24]: v for k, v in mapping.items()
        if isinstance(v, str) and v in BUTTON_ACTIONS and v != "none"
    }


def find_arduino_port() -> str | None:
    try:
        from serial.tools import list_ports
    except ImportError:
        return None
    for port in list_ports.comports():
        if port.vid in _ARDUINO_VIDS or "arduino" in (port.description or "").lower():
            return port.device
    return None


class ButtonInput:
    def __init__(self, mapping: dict[str, str], *, serial_enabled: bool = False, port: str = "") -> None:
        self.mapping = clean_map(mapping)
        self._presses: queue.SimpleQueue[str] = queue.SimpleQueue()
        self._seen: dict[str, float] = {}
        self._lock = threading.Lock()
        self.serial_enabled = False
        self.port = port
        self.serial_port = ""
        self.serial_error = ""
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        if serial_enabled:
            self.configure_serial(True, port)

    # ── input ─────────────────────────────────────────────────────────

    def press(self, button: str) -> None:
        """Record a press from any thread."""
        self._presses.put(button)

    def poll(self) -> list[dict[str, Any]]:
        """Commands for presses since the last call, in order."""
        commands = []
        now = time.time()
        while True:
            try:
                button = self._presses.get_nowait()
            except queue.Empty:
                break
            with self._lock:
                self._seen[button] = now
                if len(self._seen) > MAX_SEEN:
                    del self._seen[min(self._seen, key=self._seen.get)]
            action = self.mapping.get(button)
            if action:
                label, command = BUTTON_ACTIONS[action]
                commands.append({**command, "source": "button", "button": button, "label": label})
        return commands

    def set_mapping(self, button: str, action: str) -> bool:
        if action not in BUTTON_ACTIONS or not button:
            return False
        if action == "none":
            self.mapping.pop(button, None)
        else:
            self.mapping[button[:24]] = action
        return True

    # ── serial (Arduino) ──────────────────────────────────────────────

    def configure_serial(self, enabled: bool, port: str = "") -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        self.serial_enabled = enabled
        self.port = port
        self.serial_port = ""
        self.serial_error = ""
        if enabled:
            self._stop = threading.Event()
            self._thread = threading.Thread(
                target=self._serial_loop, args=(self._stop,), name="buttons-serial", daemon=True
            )
            self._thread.start()

    def _serial_loop(self, stop: threading.Event) -> None:
        try:
            import serial
        except ImportError:
            self.serial_error = "pyserial isn't installed"
            return
        while not stop.is_set():
            device = self.port or find_arduino_port()
            if not device:
                self.serial_error = "No Arduino found. Plug it in over USB."
                stop.wait(3.0)
                continue
            try:
                with serial.Serial(device, BAUD, timeout=0.5) as conn:
                    self.serial_port, self.serial_error = device, ""
                    logger.info("Buttons: listening on %s", device)
                    while not stop.is_set():
                        line = conn.readline().decode("ascii", "ignore").strip()
                        m = _LINE_RE.match(line)
                        if m:
                            self.press(m[1])
            except (OSError, serial.SerialException) as exc:
                self.serial_port = ""
                self.serial_error = f"{device}: {exc}"
                logger.warning("Buttons: %s", self.serial_error)
                stop.wait(3.0)
        self.serial_port = ""

    def close(self) -> None:
        self._stop.set()

    # ── dashboard ─────────────────────────────────────────────────────

    def status(self) -> dict[str, Any]:
        with self._lock:
            seen = dict(self._seen)
        buttons = sorted(set(self.mapping) | set(seen), key=_button_sort_key)
        return {
            "buttons": [
                {"id": b, "action": self.mapping.get(b, "none"), "pressed": round(seen.get(b, 0.0), 1)}
                for b in buttons
            ],
            "actions": {k: label for k, (label, _) in BUTTON_ACTIONS.items()},
            "serial": {
                "enabled": self.serial_enabled,
                "port": self.serial_port,
                "error": self.serial_error,
            },
        }


def _button_sort_key(button: str) -> tuple[int, int, str]:
    group = 1 if button.startswith("keypad") else 2 if button.startswith("F1") else 0
    digits = re.sub(r"\D", "", button)
    return (group, int(digits) if digits else 999, button)
