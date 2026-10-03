"""Unattended running: opening hours, projector power and sensor reconnects.

* ``Schedule``: opening hours such as 08:00-18:00 on weekdays.
* ``PJLink``: switches a networked projector on and off (PJLink class 1,
  TCP 4352, the standard most Epson, NEC, Panasonic, Sony and BenQ models use).
* ``Kiosk``: goes dark outside opening hours and powers the projector with
  the schedule; anyone can wake it until the next opening or closing time.
* ``SensorReconnector``: keeps retrying the configured depth camera in the
  background, so unplugging it or starting without it recovers by itself.
"""

from __future__ import annotations

import hashlib
import logging
import re
import socket
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from datetime import time as dtime

logger = logging.getLogger(__name__)

DAY_NAMES = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
_HOURS_RE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)-([01]\d|2[0-3]):([0-5]\d)$")


def parse_hours(text: str) -> tuple[dtime, dtime] | None:
    m = _HOURS_RE.match(text.strip())
    if not m:
        return None
    start = dtime(int(m[1]), int(m[2]))
    end = dtime(int(m[3]), int(m[4]))
    return (start, end) if start != end else None


def parse_days(text: str) -> frozenset[int]:
    return frozenset(int(c) for c in text if c in "0123456")


@dataclass(frozen=True)
class Schedule:
    start: dtime
    end: dtime
    days: frozenset[int]

    @classmethod
    def parse(cls, hours: str, days: str) -> Schedule | None:
        span = parse_hours(hours)
        return cls(span[0], span[1], parse_days(days)) if span else None

    def is_open(self, now: datetime) -> bool:
        t = now.time()
        if self.start < self.end:
            return now.weekday() in self.days and self.start <= t < self.end
        # Overnight hours (e.g. 18:00-02:00) belong to the day they start on
        if t >= self.start:
            return now.weekday() in self.days
        return t < self.end and (now.weekday() - 1) % 7 in self.days

    def next_change(self, now: datetime) -> datetime | None:
        state = self.is_open(now)
        base = now.replace(second=0, microsecond=0)
        candidates = sorted(
            datetime.combine(base.date() + timedelta(days=d), t)
            for d in range(9)
            for t in (self.start, self.end)
        )
        for c in candidates:
            if c > now and self.is_open(c) != state:
                return c
        return None


def read_cr_line(sock: socket.socket, limit: int = 256) -> str:
    """Read one PJLink line. PJLink ends lines with CR alone, not CRLF."""
    data = bytearray()
    while len(data) < limit:
        chunk = sock.recv(1)
        if not chunk or chunk == b"\r":
            break
        data += chunk
    return data.decode("ascii", "replace").strip()


class PJLink:
    PORT = 4352

    def __init__(self, host: str, password: str = "", timeout: float = 3.0, port: int = PORT) -> None:
        self.host = host
        self.password = password
        self.timeout = timeout
        self.port = port

    def _command(self, body: str) -> str:
        with socket.create_connection((self.host, self.port), timeout=self.timeout) as sock:
            greeting = read_cr_line(sock)
            if greeting.startswith("PJLINK ERRA"):
                raise PermissionError("Projector rejected the connection")
            prefix = ""
            if greeting.startswith("PJLINK 1 "):
                if not self.password:
                    raise PermissionError("Projector needs a PJLink password")
                salt = greeting.split(" ", 2)[2]
                prefix = hashlib.md5((salt + self.password).encode()).hexdigest()
            elif not greeting.startswith("PJLINK 0"):
                raise ConnectionError(f"Not a PJLink projector: {greeting!r}")
            sock.sendall(f"{prefix}%1{body}\r".encode("ascii"))
            reply = read_cr_line(sock)
        if reply.startswith("PJLINK ERRA"):
            raise PermissionError("Wrong PJLink password")
        return reply

    def set_power(self, on: bool) -> None:
        reply = self._command(f"POWR {1 if on else 0}")
        if reply != "%1POWR=OK":
            raise ConnectionError(f"Projector refused: {reply}")

    def get_power(self) -> str:
        """Return "off", "on", "cooling", "warming" or "error"."""
        reply = self._command("POWR ?")
        return {"0": "off", "1": "on", "2": "cooling", "3": "warming"}.get(
            reply.removeprefix("%1POWR="), "error"
        )


class Kiosk:
    def __init__(
        self,
        *,
        enabled: bool,
        hours: str,
        days: str,
        projector_host: str = "",
        projector_password: str = "",
    ) -> None:
        self.enabled = enabled
        self.hours = hours
        self.days = days
        self.schedule = Schedule.parse(hours, days)
        self.projector = PJLink(projector_host, projector_password) if projector_host else None
        self.projector_power = "unknown"
        self.projector_error = ""
        self._open: bool | None = None
        self._woken = False
        self._lock = threading.Lock()

    def configure(self, *, enabled: bool | None = None, hours: str | None = None,
                  days: str | None = None) -> None:
        if enabled is not None:
            self.enabled = enabled
        if hours is not None:
            self.hours = hours
        if days is not None:
            self.days = days
        self.schedule = Schedule.parse(self.hours, self.days)
        self._open = None   # re-evaluate (and switch the projector) on the next update
        self._woken = False

    def set_projector_host(self, host: str, password: str = "") -> None:
        self.projector = PJLink(host, password) if host else None
        with self._lock:
            self.projector_power, self.projector_error = "unknown", ""

    def is_open(self, now: datetime) -> bool:
        return not self.enabled or self.schedule is None or self.schedule.is_open(now)

    def update(self, now: datetime) -> None:
        is_open = self.is_open(now)
        if is_open != self._open:
            self._open = is_open
            self._woken = False
            if self.enabled:
                self.set_projector(is_open)

    @property
    def asleep(self) -> bool:
        return self._open is False and not self._woken

    def wake(self) -> None:
        if self.asleep:
            self._woken = True
            self.set_projector(True)

    def set_projector(self, on: bool) -> bool:
        """Switch the projector in the background. False if none is set up."""
        if self.projector is None:
            return False
        projector = self.projector

        def work() -> None:
            try:
                projector.set_power(on)
                power, error = ("on" if on else "off"), ""
            except OSError as exc:
                power, error = "unknown", _explain(exc)
                logger.warning("Projector power %s failed: %s", "on" if on else "off", error)
            with self._lock:
                self.projector_power, self.projector_error = power, error

        threading.Thread(target=work, name="pjlink", daemon=True).start()
        return True

    def status(self, now: datetime) -> dict:
        nxt = self.schedule.next_change(now) if self.enabled and self.schedule else None
        with self._lock:
            power, error = self.projector_power, self.projector_error
        return {
            "enabled": self.enabled,
            "hours": self.hours,
            "days": self.days,
            "valid": self.schedule is not None,
            "open": self.is_open(now),
            "asleep": self.asleep,
            "next_change": _when(nxt, now) if nxt else "",
            "projector": {
                "configured": self.projector is not None,
                "host": self.projector.host if self.projector else "",
                "power": power,
                "error": error,
            },
        }


def _explain(exc: OSError) -> str:
    if isinstance(exc, ConnectionRefusedError):
        return "nothing answered on port 4352. Turn on network control (PJLink) in the projector's menu."
    if isinstance(exc, TimeoutError):
        return "no reply. Check the IP address and that the projector is on the network."
    if isinstance(exc, socket.gaierror):
        return "that address can't be found."
    if isinstance(exc, (PermissionError, ConnectionError)) and str(exc):
        return str(exc)[0].lower() + str(exc)[1:]
    return str(exc) or type(exc).__name__


def _when(at: datetime, now: datetime) -> str:
    """'18:00', 'tomorrow 08:00' or 'Mon 08:00'."""
    days = (at.date() - now.date()).days
    clock = at.strftime("%H:%M")
    if days == 0:
        return clock
    if days == 1:
        return f"tomorrow {clock}"
    return f"{DAY_NAMES[at.weekday()]} {clock}"


class SensorReconnector:
    """Retries the configured sensor in a worker thread.

    ``factory`` builds and connects the sensor, returning None on failure.
    ``poll`` returns a freshly connected sensor exactly once; the caller swaps
    it in and closes the old one.
    """

    def __init__(self, factory: Callable[[], object | None], interval: float = 10.0) -> None:
        self._factory = factory
        self.interval = interval
        self._next_try = 0.0
        self._busy = False
        self._result: object | None = None
        self._released: object | None = None
        self.attempts = 0
        self._lock = threading.Lock()

    def poll(self, now: float, source, *, simulated: bool) -> object | None:
        with self._lock:
            ready, self._result = self._result, None
            busy = self._busy
        if ready is not None:
            return ready
        if busy or now < self._next_try or (not simulated and source.is_connected()):
            return None
        if not simulated and self._released is not source:
            # Free the dead device handle so the new connection can claim it
            self._released = source
            try:
                source.disconnect()
            except Exception:
                logger.exception("Disconnecting the lost sensor failed")
        self._next_try = now + self.interval
        self._busy = True
        self.attempts += 1
        threading.Thread(target=self._attempt, name="sensor-reconnect", daemon=True).start()
        return None

    def _attempt(self) -> None:
        sensor = None
        try:
            sensor = self._factory()
            if sensor is not None and not sensor.is_connected():
                sensor.disconnect()
                sensor = None
        except Exception:
            logger.exception("Sensor reconnect attempt failed")
            sensor = None
        with self._lock:
            self._result = sensor
            self._busy = False
