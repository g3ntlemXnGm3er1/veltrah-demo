#!/usr/bin/env python3
"""Start the actual packaged app, exercise local HTTP/WS, then clean up."""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import time
from urllib.error import URLError
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "vendor"))
from websockets.asyncio.client import connect


def unused_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


async def exercise(port):
    async with connect(f"ws://127.0.0.1:{port}", open_timeout=3) as ws:
        await ws.send(json.dumps({"type": "ready", "scenario": "planning"}))
        session = json.loads(await asyncio.wait_for(ws.recv(), 3))
        assert session["type"] == "session" and session["fixture"] is True
        assert len(session["options"]) == 4
        request = {
            "type": "message-response", "request_id": "smoke-1",
            "session_id": session["session_id"], "sequence": session["sequence"],
            "option_id": session["options"][0]["id"],
        }
        await ws.send(json.dumps(request))
        ack = json.loads(await asyncio.wait_for(ws.recv(), 3))
        assert ack["type"] == "selection_ack" and ack["delivery"] == "local_fixture_only"
        await ws.send(json.dumps(request))
        assert json.loads(await asyncio.wait_for(ws.recv(), 3)) == ack
        await ws.send(json.dumps({"type": "reset"}))
        fresh = json.loads(await asyncio.wait_for(ws.recv(), 3))
        assert fresh["session_id"] != session["session_id"]
        await ws.send(json.dumps(request))
        assert json.loads(await asyncio.wait_for(ws.recv(), 3))["code"] == "stale_session"


def main():
    http_port, ws_port = unused_port(), unused_port()
    while ws_port == http_port:
        ws_port = unused_port()
    env = {**os.environ, "PYTHONUNBUFFERED": "1"}
    child = subprocess.Popen(
        [sys.executable, "-S", "run_demo.py", "--http-port", str(http_port), "--ws-port", str(ws_port)],
        cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    )
    output = ""
    try:
        deadline = time.monotonic() + 10
        while True:
            if child.poll() is not None:
                raise RuntimeError("Launcher exited before becoming healthy")
            try:
                with urlopen(f"http://127.0.0.1:{http_port}/health", timeout=0.5) as response:
                    health = json.load(response)
                if health.get("status") == "ok":
                    break
            except (OSError, URLError):
                pass
            if time.monotonic() >= deadline:
                raise TimeoutError("Local server did not become healthy")
            time.sleep(0.05)
        assert health["live_api"] is False and health["real_sms"] is False
        with urlopen(f"http://127.0.0.1:{http_port}/config.json", timeout=2) as response:
            config = json.load(response)
        assert config["ws_port"] == ws_port and config["camera_started"] is False
        with urlopen(f"http://127.0.0.1:{http_port}/", timeout=2) as response:
            assert b"<div id=\"root\"></div>" in response.read()
        asyncio.run(exercise(ws_port))
        print("PASS: separate-process launcher, HTTP/config, WebSocket selection, duplicate and stale-session checks.")
        return 0
    finally:
        if child.poll() is None:
            child.send_signal(signal.SIGINT) if os.name != "nt" else child.terminate()
        try:
            raw, _ = child.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            child.kill()
            raw, _ = child.communicate(timeout=3)
        output = raw.decode("utf-8", errors="replace")
        if sys.exc_info()[0] is not None:
            print(output, file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
