"""Offline behavioral/protocol tests; do not import the legacy camera runtime."""
from __future__ import annotations

import asyncio
import functools
import http.client
import http.server
import json
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
if (ROOT / "vendor").exists():
    sys.path.insert(0, str(ROOT / "vendor"))

from backend.fixture_service import FixtureSession, decode_message, validate_coordinates
from backend.recovery_server import RecoveryService, StaticHandler
from websockets.asyncio.client import connect
from websockets.asyncio.server import serve


class DecodeAndTrackingTests(unittest.TestCase):
    def test_invalid_json_shape_and_bounded_payload(self):
        for raw in [b"{}", "[]", '"x"', '{"type": []}', '{"type":"x","x":NaN}', "{", '{"type":"x","v":"' + "a"*4096 + '"}']:
            with self.subTest(raw=type(raw)):
                with self.assertRaises(ValueError):
                    decode_message(raw)
        self.assertEqual(decode_message('{"type":"ready"}'), {"type": "ready"})

    def test_nonfinite_out_of_range_and_unhashable_coordinates_rejected(self):
        base = {"source": "camera", "valid": True, "x": 0.2, "y": 0.8}
        for changed in [{"source": []}, {"source": {}}, {"source": None}, {"valid": 1}, {"x": float("nan")}, {"x": -0.1}, {"y": 1.01}, {"y": True}, {"x": 10**1000}]:
            with self.subTest(changed=changed):
                with self.assertRaises(ValueError):
                    validate_coordinates({**base, **changed})
        valid = validate_coordinates(base)
        self.assertEqual((valid["source"], valid["x"], valid["y"]), ("camera", 0.2, 0.8))
        lost = validate_coordinates({"source": "camera", "valid": False})
        self.assertIsNone(lost["x"])
        self.assertFalse(lost["valid"])

    def test_default_import_needs_no_sdk_camera_packages_or_network(self):
        # A fresh interpreter prevents already-imported modules from hiding a
        # dependency or import-time side effect. -S also excludes site packages.
        script = """
import asyncio, socket, sys
from pathlib import Path
sys.path.insert(0, str(Path('vendor').resolve()))
for name in ('openai', 'dotenv', 'cv2', 'mediapipe', 'numpy', 'pygame'):
    sys.modules[name] = None
def forbidden(*args, **kwargs):
    raise AssertionError('Network must not be used on import')
socket.socket = forbidden
import backend.recovery_server
assert 'backend.recovery_gaze' not in sys.modules
"""
        result = subprocess.run([sys.executable, "-S", "-c", script], cwd=ROOT,
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)


class FixtureSessionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.session = FixtureSession(delay_seconds=0)
        self.loaded = (await self.session.handle({"type": "ready", "scenario": "planning"}))[0]

    def action(self, **overrides):
        return {"type": "message-response", "option_id": "reply-1", "request_id": "request-1", "session_id": self.loaded["session_id"], "sequence": self.loaded["sequence"], **overrides}

    async def test_each_session_is_synthetic_and_options_are_bounded(self):
        self.assertEqual(self.loaded["generation"], "fixture")
        self.assertEqual(len(self.loaded["options"]), 4)
        self.assertIn("synthetic", self.loaded["incoming"]["from"])
        other = FixtureSession()
        other_loaded = (await other.handle({"type": "ready"}))[0]
        self.assertNotEqual(other_loaded["session_id"], self.loaded["session_id"])
        rejected = (await other.handle(self.action()))[0]
        self.assertEqual(rejected["code"], "stale_session")
        self.assertIsNone(other.selected_option)

    async def test_ack_is_local_only_and_retries_are_idempotent(self):
        first = (await self.session.handle(self.action()))[0]
        again = (await self.session.handle(self.action()))[0]
        self.assertEqual(first, again)
        self.assertEqual(first["delivery"], "local_fixture_only")
        self.assertEqual(first["text"], self.loaded["options"][0]["text"])
        conflict = (await self.session.handle(self.action(option_id="reply-2")))[0]
        self.assertEqual(conflict["code"], "request_conflict")
        second = (await self.session.handle(self.action(request_id="new-request", option_id="reply-2")))[0]
        self.assertEqual(second["code"], "already_selected")

    async def test_stale_and_invalid_selection_never_selects(self):
        for overrides, code in [({"sequence": -1}, "stale_session"), ({"sequence": True}, "stale_session"), ({"session_id": "old"}, "stale_session"), ({"option_id": "injected text"}, "invalid_option"), ({"option_id": []}, "invalid_option"), ({"request_id": ""}, "invalid_request_id")]:
            with self.subTest(overrides=overrides):
                response = (await self.session.handle(self.action(**overrides)))[0]
                self.assertEqual(response["code"], code)
                self.assertIsNone(self.session.selected_option)
        await self.session.handle({"type": "reset"})
        self.assertEqual((await self.session.handle(self.action()))[0]["code"], "stale_session")

    async def test_cancel_never_creates_selection_and_repeat_is_available(self):
        response = (await self.session.handle({"type": "cancel", "session_id": self.loaded["session_id"], "sequence": self.loaded["sequence"]}))[0]
        self.assertEqual(response["type"], "cancelled")
        self.assertIsNone(self.session.selected_option)
        self.assertEqual((await self.session.handle(self.action()))[0]["type"], "selection_ack")
        self.assertEqual((await self.session.handle({"type": "cancel", "session_id": self.loaded["session_id"], "sequence": self.loaded["sequence"]}))[0]["code"], "already_selected")

    async def test_simulated_failure_blocks_action_and_recovery_is_fresh(self):
        failed = await self.session.handle({"type": "simulate", "kind": "generation_failure"})
        self.assertEqual(failed[0]["state"], "error")
        self.assertEqual((await self.session.handle(self.action()))[0]["code"], "generation_unavailable")
        recovered = (await self.session.handle({"type": "simulate", "kind": "recover"}))[0]
        self.assertGreater(recovered["sequence"], self.loaded["sequence"])
        self.assertNotEqual(recovered["session_id"], self.loaded["session_id"])
        self.assertFalse(self.session.failed)

    async def test_simulated_delay_creates_fresh_fixture_no_network(self):
        response = (await self.session.handle({"type": "simulate", "kind": "delay"}))[0]
        self.assertEqual(response["type"], "session")
        self.assertGreater(response["sequence"], self.loaded["sequence"])

    async def test_invalid_commands_leave_current_state_intact(self):
        for message, code in [({"type": "load_scenario", "scenario": []}, "invalid_scenario"), ({"type": "load_scenario", "scenario": "missing"}, "invalid_scenario"), ({"type": "simulate", "kind": {}}, "invalid_simulation"), ({"type": "nonsense"}, "unknown_type")]:
            self.assertEqual((await self.session.handle(message))[0]["code"], code)
            self.assertEqual(self.session.session_id, self.loaded["session_id"])


class WebSocketIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.service = RecoveryService()
        self.server = await serve(self.service.handler, "127.0.0.1", 0, max_size=4096)
        self.url = f"ws://127.0.0.1:{self.server.sockets[0].getsockname()[1]}"

    async def asyncTearDown(self):
        self.server.close()
        await self.server.wait_closed()

    async def receive(self, ws):
        return json.loads(await asyncio.wait_for(ws.recv(), timeout=2))

    async def test_real_socket_selection_and_isolated_sessions(self):
        async with connect(self.url) as one, connect(self.url) as two:
            await one.send(json.dumps({"type": "ready"}))
            await two.send(json.dumps({"type": "ready"}))
            first, second = await self.receive(one), await self.receive(two)
            self.assertNotEqual(first["session_id"], second["session_id"])
            action = {"type": "message-response", "session_id": first["session_id"], "sequence": first["sequence"], "option_id": "reply-1", "request_id": "network-1"}
            await one.send(json.dumps(action))
            ack = await self.receive(one)
            self.assertEqual(ack["type"], "selection_ack")
            await one.send(json.dumps(action))
            self.assertEqual(await self.receive(one), ack)
            await two.send(json.dumps(action))
            self.assertEqual((await self.receive(two))["code"], "stale_session")

    async def test_malformed_input_and_tracker_roles_recover_without_handler_crash(self):
        async with connect(self.url) as browser, connect(self.url) as tracker:
            await browser.send("[]")
            self.assertEqual((await self.receive(browser))["code"], "invalid_message")
            await browser.send(json.dumps({"type": "tracker_coordinates", "source": "camera", "x": 0.3, "y": 0.4, "valid": True}))
            self.assertEqual((await self.receive(browser))["code"], "tracker_not_ready")
            await browser.send(json.dumps({"type": "ready"}))
            self.assertEqual((await self.receive(browser))["type"], "session")
            await tracker.send(json.dumps({"type": "tracker_hello"}))
            self.assertEqual((await self.receive(tracker))["type"], "tracker_ack")
            for payload in [
                {"type": "tracker_coordinates", "source": [], "x": 0.2, "y": 0.3, "valid": True},
                {"type": "tracker_coordinates", "source": "camera", "x": 10**1000, "y": 0.3, "valid": True},
                {"type": "tracker_status", "source": {}, "state": "tracking"},
                {"type": "tracker_status", "source": "camera", "state": []},
            ]:
                await tracker.send(json.dumps(payload))
                self.assertTrue((await self.receive(tracker))["code"].startswith("invalid_"))
            await tracker.send(json.dumps({"type": "tracker_coordinates", "source": "synthetic", "x": 0.3, "y": 0.4, "valid": True}))
            coordinates = await self.receive(browser)
            self.assertEqual((coordinates["source"], coordinates["x"]), ("synthetic", 0.3))
            await tracker.send(json.dumps({"type": "ready"}))
            self.assertEqual((await self.receive(tracker))["code"], "tracker_command_only")
            await browser.send(json.dumps({"type": "ready"}))
            self.assertEqual((await self.receive(browser))["type"], "session")

    async def test_uninitialized_socket_receives_no_broadcast_before_role_ready(self):
        async with connect(self.url) as browser, connect(self.url) as tracker, connect(self.url) as uninitialized:
            await browser.send(json.dumps({"type": "ready"}))
            self.assertEqual((await self.receive(browser))["type"], "session")
            await tracker.send(json.dumps({"type": "tracker_hello"}))
            self.assertEqual((await self.receive(tracker))["type"], "tracker_ack")
            for payload, expected in [
                ({"type": "tracker_coordinates", "source": "synthetic", "valid": True, "x": 0.2, "y": 0.4}, "coordinates"),
                ({"type": "tracker_status", "source": "synthetic", "state": "tracking", "message": "Synthetic test"}, "tracker_status"),
            ]:
                await tracker.send(json.dumps(payload))
                self.assertEqual((await self.receive(browser))["type"], expected)
                with self.assertRaises(asyncio.TimeoutError):
                    await asyncio.wait_for(uninitialized.recv(), timeout=0.05)
            await tracker.close()
            self.assertEqual((await self.receive(browser))["state"], "stopped")
            with self.assertRaises(asyncio.TimeoutError):
                await asyncio.wait_for(uninitialized.recv(), timeout=0.05)
            # No queued coordinate/status can get ahead of the producer ACK.
            await uninitialized.send(json.dumps({"type": "tracker_hello"}))
            self.assertEqual((await self.receive(uninitialized))["type"], "tracker_ack")


class HTTPIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        root = Path(cls.temp.name)
        (root / "index.html").write_text("<h1>Synthetic test asset</h1>")
        (root / ".private").write_text("must not be served")
        (root / "subdir").mkdir()
        handler = functools.partial(StaticHandler, directory=str(root), ws_port=19444)
        cls.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)
        cls.temp.cleanup()

    def request(self, method, path):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_address[1], timeout=2)
        connection.request(method, path)
        response = connection.getresponse()
        value = response.status, response.getheaders(), response.read()
        connection.close()
        return value

    def test_head_has_asset_headers_and_no_body(self):
        status, headers, body = self.request("HEAD", "/")
        self.assertEqual(status, 200)
        self.assertEqual(body, b"")
        self.assertGreater(int(dict(headers)["Content-Length"]), 0)

    def test_health_and_config_are_explicit_fixture_mode(self):
        status, _, body = self.request("GET", "/config.json")
        config = json.loads(body)
        self.assertEqual(status, 200)
        self.assertEqual(config["ws_port"], 19444)
        self.assertEqual(config["http_port"], self.server.server_address[1])
        self.assertEqual(config["mode"], "fixture")
        self.assertFalse(config["live_api"])
        self.assertFalse(json.loads(self.request("GET", "/health")[2])["real_sms"])

    def test_no_hidden_files_directory_listing_or_missing_asset_fallback(self):
        for path in ["/.private", "/subdir/", "/does-not-exist", "/../", "/%2eprivate"]:
            with self.subTest(path=path):
                self.assertEqual(self.request("GET", path)[0], 404)


if __name__ == "__main__":
    unittest.main()
