"""Unit tests for the inter-app communication bridge (bridge.py).

These tests drive AppBridge._service_connection directly with a fake socket so
no real networking is involved. They cover the newline-delimited JSON parsing
and the MAX_LINE_BYTES safety cap that guards against an unbounded buffer.
"""

import unittest
from unittest import mock

import bridge
from bridge import MAX_LINE_BYTES, AppBridge


class FakeSocket:
    """Minimal socket stand-in returning queued recv() chunks in order."""

    def __init__(self, chunks):
        self._chunks = list(chunks)
        self.sent = []

    def recv(self, _bufsize):
        if self._chunks:
            return self._chunks.pop(0)
        return b""  # empty => peer disconnected, ends the loop

    def sendall(self, data):
        self.sent.append(data)

    def send(self, data):
        # Non-blocking socket API used by bridge._send_all(); accept the whole
        # buffer in one call and report the byte count, like a ready socket.
        self.sent.append(bytes(data))
        return len(data)


def _run_service(chunks):
    """Run one _service_connection pass over the given recv chunks."""
    br = AppBridge()
    br._running = True
    br._connected_event.set()
    br._conn_sock = FakeSocket(chunks)
    # Always report the socket readable so recv() is exercised deterministically.
    with mock.patch.object(bridge.select, "select", return_value=([br._conn_sock], [], [])):
        br._service_connection()
    return br


class BridgeProtocolTests(unittest.TestCase):
    def test_parses_newline_delimited_json(self):
        chunks = [b'{"type":"hello","n":1}\n{"type":"world"}\n']
        br = _run_service(chunks)
        msgs = br.poll()
        self.assertEqual(msgs, [{"type": "hello", "n": 1}, {"type": "world"}])

    def test_ping_triggers_pong_reply(self):
        br = _run_service([b'{"type":"ping"}\n'])
        # ping is auto-answered and not surfaced to poll()
        self.assertEqual(br.poll(), [])
        # the pong is flushed to the socket on the next loop iteration
        sent = b"".join(br._conn_sock.sent)
        self.assertIn(b'"type":"pong"', sent)

    def test_invalid_json_is_skipped(self):
        br = _run_service([b"not json at all\n"])
        self.assertEqual(br.poll(), [])

    def test_oversized_line_drops_connection(self):
        # A single chunk over the cap with no newline must drop the connection
        # instead of buffering unboundedly.
        oversized = b"x" * (MAX_LINE_BYTES + 1)
        br = _run_service([oversized])
        self.assertFalse(br._connected_event.is_set())
        self.assertEqual(br.poll(), [])

    def test_large_but_valid_message_within_cap_parses(self):
        payload = "y" * (MAX_LINE_BYTES // 2)
        line = ('{"type":"big","data":"%s"}\n' % payload).encode("utf-8")
        br = _run_service([line])
        msgs = br.poll()
        self.assertEqual(len(msgs), 1)
        self.assertEqual(msgs[0]["type"], "big")


if __name__ == "__main__":
    unittest.main()
