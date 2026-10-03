"""Tests for the dashboard server: HTTP routes, PIN gate, commands and acks."""

from __future__ import annotations

import asyncio
import json
import pathlib
import socket
import tempfile
import time
import unittest
import urllib.error
import urllib.request
from unittest import mock

import numpy as np

import dem_loader
from depth_server import DepthStreamServer, is_loopback


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _wait_for(port: int, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/healthz", timeout=0.5):
                return
        except OSError:
            time.sleep(0.05)
    raise TimeoutError("server did not start")


class LoopbackServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.port = _free_port()
        cls.server = DepthStreamServer(host="127.0.0.1", port=cls.port)
        cls.server.start()
        _wait_for(cls.port)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.stop()

    def _get(self, path: str) -> tuple[int, str, bytes]:
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}{path}", timeout=2) as resp:
            return resp.status, resp.headers["Content-Type"], resp.read()

    def test_serves_dashboard_html(self) -> None:
        status, ctype, body = self._get("/")
        self.assertEqual(status, 200)
        self.assertIn("text/html", ctype)
        self.assertIn(b"<html", body)

    def test_palettes_cover_every_theme(self) -> None:
        _, ctype, body = self._get("/api/palettes")
        self.assertIn("application/json", ctype)
        palettes = json.loads(body)
        self.assertEqual(set(palettes), {"terrain", "heat", "greyscale", "desert"})
        self.assertEqual(len(palettes["terrain"]), 256)

    def test_rejects_path_traversal(self) -> None:
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self._get("/assets/../../main.py")
        self.assertEqual(ctx.exception.code, 404)

    def test_snapshot_download_and_bad_names(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(
            dem_loader, "SAVED_DIR", pathlib.Path(tmp)
        ):
            paths = dem_loader.export_snapshot(
                np.full((6, 8), 0.5, dtype=np.float32), depth_range_mm=(500, 1100)
            )
            asc = next(p for p in paths if p.suffix == ".asc")
            status, ctype, body = self._get(f"/snapshots/{asc.name}")
            self.assertEqual(status, 200)
            self.assertIn("text/plain", ctype)
            self.assertTrue(body.startswith(b"ncols 8\nnrows 6\n"))
            for bad in ("/snapshots/..%2Fmain.py", "/snapshots/terrain_x.npy", f"/snapshots/{asc.stem}.py"):
                with self.assertRaises(urllib.error.HTTPError) as ctx:
                    self._get(bad)
                self.assertEqual(ctx.exception.code, 404)

    def test_no_pin_on_loopback(self) -> None:
        self.assertEqual(self.server.pin, "")
        self.assertFalse(self.server.lan_enabled)
        self.assertEqual(self.server.dashboard_url(), f"http://127.0.0.1:{self.port}/")

    def test_command_roundtrip_and_ack(self) -> None:
        from websockets.asyncio.client import connect

        async def run() -> dict:
            async with connect(f"ws://127.0.0.1:{self.port}/ws") as ws:
                await ws.send(json.dumps({"type": "command", "id": 7, "action": "toggle_sound"}))
                for _ in range(50):
                    cmds = self.server.poll_commands()
                    if cmds:
                        self.assertEqual(cmds[0]["action"], "toggle_sound")
                        self.server.push_event({"type": "ack", "id": 7, "ok": True, "message": "ok"})
                        break
                    await asyncio.sleep(0.02)
                return json.loads(await asyncio.wait_for(ws.recv(), 2))

        ack = asyncio.run(run())
        self.assertEqual(ack, {"type": "ack", "id": 7, "ok": True, "message": "ok"})


class LanPinTests(unittest.TestCase):
    def test_lan_bind_generates_pin_and_gates_websocket(self) -> None:
        from websockets.asyncio.client import connect
        from websockets.exceptions import InvalidStatus

        port = _free_port()
        server = DepthStreamServer(host="0.0.0.0", port=port)
        self.assertRegex(server.pin, r"^\d{6}$")
        self.assertIn(f"?pin={server.pin}", server.dashboard_url())
        server.start()
        try:
            _wait_for(port)

            async def attempt(pin: str) -> bool:
                try:
                    async with connect(f"ws://127.0.0.1:{port}/ws?pin={pin}"):
                        return True
                except InvalidStatus:
                    return False

            self.assertFalse(asyncio.run(attempt("000000" if server.pin != "000000" else "111111")))
            self.assertTrue(asyncio.run(attempt(server.pin)))

            with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/session", timeout=2) as resp:
                self.assertEqual(json.loads(resp.read()), {"pin_required": True})
            with urllib.request.urlopen(
                f"http://127.0.0.1:{port}/api/auth?pin={server.pin}", timeout=2
            ) as resp:
                self.assertEqual(resp.status, 200)
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(f"http://127.0.0.1:{port}/api/auth?pin=x", timeout=2)
            self.assertEqual(ctx.exception.code, 401)

            # The pairing QR embeds the PIN, so it must not be readable without it.
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(f"http://127.0.0.1:{port}/qr.svg", timeout=2)
            self.assertEqual(ctx.exception.code, 401)
            try:
                with urllib.request.urlopen(
                    f"http://127.0.0.1:{port}/qr.svg?pin={server.pin}", timeout=2
                ) as resp:
                    self.assertEqual(resp.status, 200)
            except urllib.error.HTTPError as exc:
                self.assertEqual(exc.code, 501)  # segno not installed
        finally:
            server.stop()

    def test_configured_pin_is_used(self) -> None:
        server = DepthStreamServer(host="0.0.0.0", port=_free_port(), pin="12-34")
        self.assertEqual(server.pin, "1234")

    def test_is_loopback(self) -> None:
        self.assertTrue(is_loopback("localhost"))
        self.assertFalse(is_loopback("0.0.0.0"))


if __name__ == "__main__":
    unittest.main()
