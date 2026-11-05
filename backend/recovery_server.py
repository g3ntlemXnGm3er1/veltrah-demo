"""Local fixture-only HTTP + WebSocket service for the recovered HUD.

No legacy camera, OpenAI, dotenv, pygame or message-log modules are imported.
"""
from __future__ import annotations

import asyncio
import functools
import http.server
import json
import logging
import mimetypes
import threading
from pathlib import Path
from urllib.parse import urlsplit

from websockets.asyncio.server import serve
from websockets.exceptions import ConnectionClosed

from .fixture_service import FixtureSession, MAX_MESSAGE_BYTES, decode_message, error, validate_coordinates

LOGGER = logging.getLogger("veltrah.recovery")


class RecoveryService:
    def __init__(self, *, allowed_origins: set[str] | None = None):
        self.browser_clients = set()
        self.trackers = set()
        self.allowed_origins = allowed_origins or set()

    async def broadcast(self, payload):
        if not self.browser_clients:
            return
        raw = json.dumps(payload, allow_nan=False)
        await asyncio.gather(*(client.send(raw) for client in tuple(self.browser_clients)), return_exceptions=True)

    async def handler(self, websocket):
        session = FixtureSession()
        # A newly connected socket has no role. Do not expose tracker broadcasts
        # until a legitimate UI command creates its first fixture session.
        # In particular, tracker producers must receive tracker_ack first.
        role = "uninitialized"
        try:
            async for raw in websocket:
                try:
                    data = decode_message(raw)
                except ValueError as exc:
                    await websocket.send(json.dumps(error("invalid_message", str(exc))))
                    continue
                typ = data["type"]
                if typ == "tracker_hello":
                    if session.session_id:
                        await websocket.send(json.dumps(error("role_conflict", "A UI connection cannot become a tracker after loading a session.")))
                        continue
                    role = "tracker"
                    self.browser_clients.discard(websocket)
                    self.trackers.add(websocket)
                    await websocket.send(json.dumps({"type": "tracker_ack", "mode": "local_explicit_source_only"}))
                    continue
                if typ == "tracker_coordinates":
                    if role != "tracker":
                        await websocket.send(json.dumps(error("tracker_not_ready", "Use a separate tracker connection and tracker_hello first.")))
                        continue
                    try:
                        coordinates = validate_coordinates(data)
                    except ValueError as exc:
                        await websocket.send(json.dumps(error("invalid_coordinates", str(exc))))
                        continue
                    await self.broadcast(coordinates)
                    continue
                if typ == "tracker_status":
                    if role != "tracker":
                        await websocket.send(json.dumps(error("tracker_not_ready", "Use a separate tracker connection first.")))
                        continue
                    if not isinstance(data.get("source"), str) or not isinstance(data.get("state"), str) or data.get("source") not in {"camera", "synthetic"} or data.get("state") not in {"ready", "tracking", "lost", "calibrating", "error", "stopped"}:
                        await websocket.send(json.dumps(error("invalid_tracker_status", "Explicit source and supported state required.")))
                        continue
                    message = data.get("message", "")
                    if not isinstance(message, str) or len(message) > 240:
                        await websocket.send(json.dumps(error("invalid_tracker_status", "Status message must be at most 240 characters.")))
                        continue
                    await self.broadcast({"type": "tracker_status", "source": data["source"], "state": data["state"], "message": message})
                    continue
                if role == "tracker":
                    await websocket.send(json.dumps(error("tracker_command_only", "Tracker connections cannot select replies or load UI sessions.")))
                    continue
                if typ == "simulate" and data.get("kind") == "delay":
                    await websocket.send(json.dumps({"type": "status", "state": "loading", "message": "Simulated generation delay (2 seconds).", "fixture": True}))
                for payload in await session.handle(data):
                    await websocket.send(json.dumps(payload, allow_nan=False))
                    if payload.get("type") == "session" and role == "uninitialized":
                        role = "browser"
                        self.browser_clients.add(websocket)
        except ConnectionClosed:
            pass
        finally:
            self.browser_clients.discard(websocket)
            was_tracker = websocket in self.trackers
            self.trackers.discard(websocket)
            if was_tracker:
                await self.broadcast({"type": "tracker_status", "state": "stopped", "source": "unknown", "message": "Tracker disconnected. Gaze dwell must stop."})


class StaticHandler(http.server.SimpleHTTPRequestHandler):
    """Serve only built assets and explicit health/config routes."""
    server_version = "VeltrahRecovery/1.0"

    def __init__(self, *args, directory, ws_port, **kwargs):
        self.asset_root = Path(directory).resolve()
        self.ws_port = ws_port
        super().__init__(*args, directory=directory, **kwargs)

    def log_message(self, fmt, *args):
        # No request bodies or synthetic/user message contents are logged.
        LOGGER.debug(fmt, *args)

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")
        super().end_headers()

    def send_json(self, value, status=200):
        payload = json.dumps(value, allow_nan=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(payload)

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        path = urlsplit(self.path).path
        if path == "/health":
            return self.send_json({"status": "ok", "version": "recovery-1.0", "mode": "fixture", "fixture": True, "live_api": False, "real_sms": False})
        if path == "/config.json":
            return self.send_json({"websocket_url": f"ws://127.0.0.1:{self.ws_port}", "ws_url": f"ws://127.0.0.1:{self.ws_port}", "ws_port": self.ws_port, "http_port": self.server.server_address[1], "mode": "fixture", "fixture": True, "bind": "127.0.0.1", "live_api": False, "camera_started": False})
        translated = Path(self.translate_path(path)).resolve()
        if not translated.is_relative_to(self.asset_root) or any(part.startswith(".") for part in translated.relative_to(self.asset_root).parts):
            self.send_error(404)
            return
        if translated.is_dir():
            if path != "/":
                self.send_error(404)
                return
            translated = self.asset_root / "index.html"
        if not translated.is_file():
            self.send_error(404, "Built asset not found")
            return
        if self.command == "HEAD":
            return super().do_HEAD()
        return super().do_GET()

    def list_directory(self, path):
        self.send_error(404)
        return None


async def run_services(*, host: str, http_port: int, ws_port: int, asset_root: Path, open_browser=False, stop_event=None):
    """Run both local services and close both when cancelled/interrupted."""
    origins = [None, f"http://127.0.0.1:{http_port}", f"http://localhost:{http_port}", "http://localhost:5173", "http://127.0.0.1:5173"]
    service = RecoveryService()
    handler = functools.partial(StaticHandler, directory=str(asset_root), ws_port=ws_port)
    httpd = http.server.ThreadingHTTPServer((host, http_port), handler)
    httpd.daemon_threads = True
    thread = threading.Thread(target=httpd.serve_forever, name="veltrah-http", daemon=True)
    try:
        async with serve(service.handler, host, ws_port, origins=origins, max_size=MAX_MESSAGE_BYTES, max_queue=16, compression=None, ping_interval=20, ping_timeout=20, close_timeout=2):
            thread.start()
            url = f"http://127.0.0.1:{http_port}"
            print(f"Veltrah recovery demo: {url}", flush=True)
            print(f"WebSocket: ws://127.0.0.1:{ws_port} | synthetic messages only | no camera/API/SMS started", flush=True)
            print("Press Ctrl+C to stop.", flush=True)
            if open_browser:
                import webbrowser
                webbrowser.open(url)
            if stop_event is None:
                await asyncio.Event().wait()
            else:
                await stop_event.wait()
    finally:
        if thread.is_alive():
            httpd.shutdown()
            thread.join(timeout=3)
        httpd.server_close()
