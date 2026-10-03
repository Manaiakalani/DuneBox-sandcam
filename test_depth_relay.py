import socket
import struct
import time
import unittest

import numpy as np

from depth_relay import (
    FLAG_COLOR,
    HEADER,
    MAGIC,
    RELAY_SIZE,
    DepthRelay,
    encode,
    intrinsics,
    to_millimetres,
)


def recv_exact(sock: socket.socket, n: int) -> bytes:
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ConnectionError("closed")
        buf += chunk
    return buf


class TestConversion(unittest.TestCase):
    def test_millimetres_from_heights(self):
        frame = np.array([[1.0, 0.0], [0.5, 0.25]], dtype=np.float32)
        mm = to_millimetres(frame, 500, 1500, size=(2, 2))
        self.assertEqual(mm.dtype, np.dtype("<u2"))
        np.testing.assert_array_equal(mm, [[500, 1500], [1000, 1250]])

    def test_resamples_to_relay_size(self):
        frame = np.zeros((300, 400), dtype=np.float32)
        frame[:, 200:] = 1.0
        mm = to_millimetres(frame, 400, 1100)
        self.assertEqual(mm.shape, (RELAY_SIZE[1], RELAY_SIZE[0]))
        self.assertEqual(mm[0, 0], 1100)
        self.assertEqual(mm[0, -1], 400)

    def test_intrinsics_span_the_field_of_view(self):
        sx, ax, sy, ay = intrinsics((90.0, 90.0), size=(100, 50))
        self.assertAlmostEqual(ax, -1.0)
        self.assertAlmostEqual(sx * 100 + ax, 1.0)
        self.assertAlmostEqual(sy * 50 + ay, 1.0)

    def test_encode_layout(self):
        mm = np.array([[1, 2, 3]], dtype="<u2")
        msg = encode(mm, 7, (0.1, -0.2, 0.3, -0.4))
        magic, w, h, n, sx, ax, sy, ay, flags = HEADER.unpack_from(msg)
        self.assertEqual((magic, w, h, n, flags), (MAGIC, 3, 1, 7, 0))
        self.assertAlmostEqual(ay, -0.4, places=6)
        self.assertEqual(struct.unpack("<3H", msg[HEADER.size:]), (1, 2, 3))
        self.assertEqual(len(msg), HEADER.size + 6)

    def test_encode_with_colour(self):
        mm = np.zeros((1, 2), dtype="<u2")
        rgb = np.array([[[1, 2, 3], [4, 5, 6]]], dtype=np.uint8)
        msg = encode(mm, 1, (0, 0, 0, 0), rgb)
        self.assertEqual(HEADER.unpack_from(msg)[-1], FLAG_COLOR)
        self.assertEqual(msg[HEADER.size + 4:], bytes([1, 2, 3, 4, 5, 6]))


class TestRelay(unittest.TestCase):
    def setUp(self):
        self.relay = DepthRelay(port=0)
        self.assertTrue(self.relay.start())

    def tearDown(self):
        self.relay.stop()

    def wait_for(self, predicate, timeout=2.0):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if predicate():
                return True
            time.sleep(0.02)
        return False

    def test_no_work_without_clients(self):
        self.relay.publish(np.ones((10, 10), np.float32), 400, 1100, "orbbec")
        self.assertIsNone(self.relay._latest)

    def test_client_receives_latest_frame(self):
        with socket.create_connection(("127.0.0.1", self.relay.port), timeout=2) as client:
            self.assertTrue(self.wait_for(lambda: self.relay.client_count == 1))
            frame = np.full((48, 64), 0.5, np.float32)
            self.relay.publish(frame, 400, 1200, "realsense")
            header = HEADER.unpack(recv_exact(client, HEADER.size))
            self.assertEqual(header[:3], (MAGIC, RELAY_SIZE[0], RELAY_SIZE[1]))
            payload = recv_exact(client, RELAY_SIZE[0] * RELAY_SIZE[1] * 2)
            depth = np.frombuffer(payload, "<u2")
            self.assertTrue((depth == 800).all())
            self.assertAlmostEqual(header[5], -np.tan(np.radians(87.0) / 2), places=5)

    def test_colour_on_request(self):
        with socket.create_connection(("127.0.0.1", self.relay.port), timeout=2) as client:
            self.assertTrue(self.wait_for(lambda: self.relay.client_count == 1))
            self.assertFalse(self.relay.wants_color)
            client.sendall(b"C1\n")
            self.assertTrue(self.wait_for(lambda: self.relay.wants_color))
            colour = np.zeros((48, 64, 3), np.uint8)
            colour[..., 0] = 200
            self.relay.publish(np.zeros((48, 64), np.float32), 400, 1100, "orbbec", colour)
            header = HEADER.unpack(recv_exact(client, HEADER.size))
            self.assertEqual(header[-1], FLAG_COLOR)
            w, h = RELAY_SIZE
            recv_exact(client, w * h * 2)
            rgb = np.frombuffer(recv_exact(client, w * h * 3), np.uint8).reshape(h, w, 3)
            self.assertTrue((rgb[..., 0] == 200).all())
            client.sendall(b"C0\n")
            self.assertTrue(self.wait_for(lambda: not self.relay.wants_color))

    def test_disconnected_client_is_dropped(self):
        client = socket.create_connection(("127.0.0.1", self.relay.port), timeout=2)
        self.assertTrue(self.wait_for(lambda: self.relay.client_count == 1))
        client.close()
        frame = np.zeros((48, 64), np.float32)
        self.assertTrue(self.wait_for(lambda: (
            self.relay.publish(frame, 400, 1100, "orbbec") or self.relay.client_count == 0
        ), timeout=5))

    def test_status(self):
        status = self.relay.status()
        self.assertTrue(status["enabled"])
        self.assertEqual(status["clients"], 0)


if __name__ == "__main__":
    unittest.main()
