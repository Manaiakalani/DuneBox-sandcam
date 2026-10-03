import hashlib
import socket
import threading
import time
import unittest
from datetime import datetime

from kiosk import Kiosk, PJLink, Schedule, SensorReconnector, parse_hours, read_cr_line

# 2026-10-05 is a Monday
MON_10 = datetime(2026, 10, 5, 10, 0)
MON_20 = datetime(2026, 10, 5, 20, 0)
SAT_10 = datetime(2026, 10, 10, 10, 0)


class ScheduleTests(unittest.TestCase):
    def test_parse_hours(self):
        self.assertIsNotNone(parse_hours("08:00-17:30"))
        for bad in ("8:00-17:00", "08:00-08:00", "25:00-26:00", "08:00", ""):
            self.assertIsNone(parse_hours(bad), bad)

    def test_weekday_hours(self):
        s = Schedule.parse("09:00-17:00", "01234")
        self.assertTrue(s.is_open(MON_10))
        self.assertFalse(s.is_open(MON_20))
        self.assertFalse(s.is_open(SAT_10))

    def test_overnight_belongs_to_start_day(self):
        s = Schedule.parse("18:00-02:00", "4")  # Friday night
        self.assertTrue(s.is_open(datetime(2026, 10, 9, 23, 0)))
        self.assertTrue(s.is_open(datetime(2026, 10, 10, 1, 0)))   # early Saturday
        self.assertFalse(s.is_open(datetime(2026, 10, 10, 23, 0)))

    def test_next_change(self):
        s = Schedule.parse("09:00-17:00", "01234")
        self.assertEqual(s.next_change(MON_10), datetime(2026, 10, 5, 17, 0))
        # Friday evening: next opening is Monday
        self.assertEqual(s.next_change(datetime(2026, 10, 9, 18, 0)), datetime(2026, 10, 12, 9, 0))


class FakeProjector:
    def __init__(self, password=""):
        self.password = password
        self.commands = []
        self.server = socket.socket()
        self.server.bind(("127.0.0.1", 0))
        self.server.listen()
        self.port = self.server.getsockname()[1]
        threading.Thread(target=self._serve, daemon=True).start()

    def _serve(self):
        while True:
            try:
                conn, _ = self.server.accept()
            except OSError:
                return
            with conn:
                salt = "498e4a67"
                conn.sendall(f"PJLINK 1 {salt}\r".encode() if self.password else b"PJLINK 0\r")
                line = read_cr_line(conn)
                if self.password:
                    digest = hashlib.md5((salt + self.password).encode()).hexdigest()
                    if not line.startswith(digest):
                        conn.sendall(b"PJLINK ERRA\r")
                        continue
                    line = line[len(digest):]
                self.commands.append(line)
                conn.sendall(b"%1POWR=1\r" if line == "%1POWR ?" else b"%1POWR=OK\r")

    def close(self):
        self.server.close()


class PJLinkTests(unittest.TestCase):
    def test_power_without_auth(self):
        proj = FakeProjector()
        self.addCleanup(proj.close)
        PJLink("127.0.0.1", port=proj.port).set_power(True)
        self.assertEqual(PJLink("127.0.0.1", port=proj.port).get_power(), "on")
        self.assertEqual(proj.commands, ["%1POWR 1", "%1POWR ?"])

    def test_power_with_password(self):
        proj = FakeProjector(password="secret")
        self.addCleanup(proj.close)
        PJLink("127.0.0.1", "secret", port=proj.port).set_power(False)
        self.assertEqual(proj.commands, ["%1POWR 0"])
        with self.assertRaises(PermissionError):
            PJLink("127.0.0.1", "wrong", port=proj.port).set_power(False)
        with self.assertRaises(PermissionError):
            PJLink("127.0.0.1", port=proj.port).set_power(False)


class KioskTests(unittest.TestCase):
    def make(self, enabled=True):
        kiosk = Kiosk(enabled=enabled, hours="09:00-17:00", days="01234")
        calls = []
        kiosk.set_projector = lambda on: calls.append(on) or True
        return kiosk, calls

    def test_disabled_is_always_awake(self):
        kiosk, calls = self.make(enabled=False)
        kiosk.update(MON_20)
        self.assertFalse(kiosk.asleep)
        self.assertEqual(calls, [])

    def test_follows_schedule_and_powers_projector(self):
        kiosk, calls = self.make()
        kiosk.update(MON_10)
        self.assertFalse(kiosk.asleep)
        kiosk.update(MON_20)
        self.assertTrue(kiosk.asleep)
        self.assertEqual(calls, [True, False])
        self.assertEqual(kiosk.status(MON_20)["next_change"], "tomorrow 09:00")

    def test_wake_lasts_until_next_change(self):
        kiosk, calls = self.make()
        kiosk.update(MON_20)
        kiosk.wake()
        self.assertFalse(kiosk.asleep)
        kiosk.update(datetime(2026, 10, 6, 9, 0))   # opens
        kiosk.update(datetime(2026, 10, 6, 17, 0))  # closes again
        self.assertTrue(kiosk.asleep)

    def test_set_projector_without_host(self):
        kiosk = Kiosk(enabled=True, hours="09:00-17:00", days="01234")
        self.assertFalse(kiosk.set_projector(True))


class FakeSensor:
    def __init__(self, connected=True):
        self.connected = connected
        self.disconnects = 0

    def is_connected(self):
        return self.connected

    def disconnect(self):
        self.disconnects += 1
        self.connected = False


class ReconnectorTests(unittest.TestCase):
    def wait_for(self, rec, source, simulated):
        for _ in range(100):
            fresh = rec.poll(time.monotonic() + 1000, source, simulated=simulated)
            if fresh is not None:
                return fresh
            time.sleep(0.01)
        return None

    def test_replaces_simulator_when_camera_appears(self):
        new = FakeSensor()
        rec = SensorReconnector(lambda: new, interval=0)
        self.assertIs(self.wait_for(rec, FakeSensor(), simulated=True), new)

    def test_leaves_working_sensor_alone(self):
        rec = SensorReconnector(lambda: FakeSensor(), interval=0)
        self.assertIsNone(rec.poll(0, FakeSensor(), simulated=False))
        self.assertEqual(rec.attempts, 0)

    def test_releases_lost_sensor_once_then_retries(self):
        lost = FakeSensor(connected=False)
        results = iter([None, FakeSensor()])
        rec = SensorReconnector(lambda: next(results), interval=0)
        fresh = self.wait_for(rec, lost, simulated=False)
        self.assertIsNotNone(fresh)
        self.assertEqual(lost.disconnects, 1)
        self.assertGreaterEqual(rec.attempts, 2)

    def test_discards_sensor_that_fails_to_connect(self):
        dud = FakeSensor(connected=False)
        rec = SensorReconnector(lambda: dud, interval=60)
        rec.poll(0, FakeSensor(), simulated=True)
        time.sleep(0.1)
        self.assertIsNone(rec.poll(1, FakeSensor(), simulated=True))
        self.assertEqual(dud.disconnects, 1)


if __name__ == "__main__":
    unittest.main()
