"""Offline synthetic-message session state. No network, files or model calls.

The service deliberately acknowledges a local selection, not a delivered message.
Each browser connection gets its own instance. Coordinates are handled separately.
"""
from __future__ import annotations

import asyncio
import copy
import json
import math
import re
import time
import uuid
from collections import OrderedDict
from pathlib import Path
from typing import Any

MAX_MESSAGE_BYTES = 4096
MAX_REQUEST_CACHE = 128
REQUEST_ID = re.compile(r"[A-Za-z0-9_.:-]{1,128}\Z")

SCENARIOS = json.loads((Path(__file__).resolve().parent.parent / "fixtures" / "scenarios.json").read_text(encoding="utf-8"))


def error(code: str, message: str, request_id: str | None = None) -> dict[str, Any]:
    result = {"type": "error", "code": code, "message": message}
    if isinstance(request_id, str) and REQUEST_ID.fullmatch(request_id):
        result["request_id"] = request_id
    return result


def decode_message(raw: str | bytes) -> dict[str, Any]:
    if not isinstance(raw, str):
        raise ValueError("Only UTF-8 JSON text messages are accepted.")
    if len(raw.encode("utf-8")) > MAX_MESSAGE_BYTES:
        raise ValueError("Message exceeds the 4096-byte limit.")
    try:
        value = json.loads(raw, parse_constant=lambda _: (_ for _ in ()).throw(ValueError("Non-finite JSON number")))
    except (json.JSONDecodeError, ValueError, RecursionError) as exc:
        raise ValueError("Message must be valid finite JSON.") from exc
    if not isinstance(value, dict) or not isinstance(value.get("type"), str):
        raise ValueError("Message must be an object with a string type.")
    return value


class FixtureSession:
    """Per-browser bounded state. Outgoing data is always a synthetic fixture."""

    def __init__(self, *, delay_seconds: float = 2.0, clock=time.monotonic):
        self.sequence = 0
        self.session_id: str | None = None
        self.scenario = "planning"
        self.options: dict[str, str] = {}
        self.selected_option: str | None = None
        self.started_at = clock()
        self.clock = clock
        self.delay_seconds = delay_seconds
        self.acks: OrderedDict[str, tuple[str, dict[str, Any]]] = OrderedDict()
        self.failed = False
        self.load_generation = 0

    def new_session(self, scenario: str | None = None) -> dict[str, Any]:
        if scenario is not None:
            self.scenario = scenario
        self.load_generation += 1
        self.sequence += 1
        self.session_id = str(uuid.uuid4())
        self.selected_option = None
        self.acks.clear()
        self.failed = False
        self.started_at = self.clock()
        fixture = SCENARIOS[self.scenario]
        self.options = {option["id"]: option["text"] for option in fixture["options"]}
        return {
            "type": "session", "session_id": self.session_id,
            "scenario": self.scenario, "generation": "fixture", "fixture": True,
            "sequence": self.sequence,
            "incoming": {**fixture["incoming"], "id": f"{self.scenario}-{self.sequence}"},
            "options": [{"id": key, "text": value} for key, value in self.options.items()],
        }

    def validate_session(self, data: dict[str, Any]) -> dict[str, Any] | None:
        if not self.session_id:
            return error("not_ready", "Load a synthetic scenario before selecting.", data.get("request_id"))
        if data.get("session_id") != self.session_id or type(data.get("sequence")) is not int or data.get("sequence") != self.sequence:
            return error("stale_session", "This action belongs to an old or invalid session. Reload the scenario.", data.get("request_id"))
        return None

    async def handle(self, data: dict[str, Any]) -> list[dict[str, Any]]:
        typ = data.get("type")
        if typ in {"ready", "load_scenario", "reset"}:
            scenario = data.get("scenario", self.scenario)
            if not isinstance(scenario, str) or scenario not in SCENARIOS:
                return [error("invalid_scenario", "Choose planning, logistics or social.")]
            return [self.new_session(scenario)]
        if typ == "message-response":
            invalid = self.validate_session(data)
            if invalid:
                return [invalid]
            request_id = data.get("request_id")
            option_id = data.get("option_id")
            if not isinstance(request_id, str) or not REQUEST_ID.fullmatch(request_id):
                return [error("invalid_request_id", "A nonempty bounded request_id is required.")]
            if not isinstance(option_id, str) or option_id not in self.options:
                return [error("invalid_option", "Select one of the current fixture options.", request_id)]
            cached = self.acks.get(request_id)
            if cached:
                if cached[0] != option_id:
                    return [error("request_conflict", "This request_id was already used for a different option.", request_id)]
                return [copy.deepcopy(cached[1])]
            if self.failed:
                return [error("generation_unavailable", "The simulated generator failed. Recover before selecting.", request_id)]
            if self.selected_option is not None:
                return [error("already_selected", "This session already has a local selection. Load a new scenario to repeat.", request_id)]
            self.selected_option = option_id
            ack = {
                "type": "selection_ack", "request_id": request_id,
                "session_id": self.session_id, "option_id": option_id,
                "text": self.options[option_id], "sequence": self.sequence,
                "elapsed_ms": max(0, round((self.clock() - self.started_at) * 1000)),
                "delivery": "local_fixture_only", "fixture": True,
            }
            self.acks[request_id] = (option_id, ack)
            while len(self.acks) > MAX_REQUEST_CACHE:
                self.acks.popitem(last=False)
            return [copy.deepcopy(ack)]
        if typ == "cancel":
            invalid = self.validate_session(data)
            if invalid:
                return [invalid]
            if self.selected_option is not None:
                return [error("already_selected", "An acknowledged local selection cannot be undone; load a new scenario.")]
            return [{"type": "cancelled", "session_id": self.session_id, "sequence": self.sequence, "fixture": True}]
        if typ == "simulate":
            kind = data.get("kind")
            if kind == "generation_failure":
                self.load_generation += 1
                self.failed = True
                self.selected_option = None
                self.acks.clear()
                return [{"type": "status", "state": "error", "message": "Simulated reply-generation failure. Nothing was delivered.", "fixture": True}]
            if kind == "recover":
                return [self.new_session()]
            if kind == "delay":
                self.failed = True
                self.load_generation += 1
                generation = self.load_generation
                await asyncio.sleep(self.delay_seconds)
                if generation != self.load_generation:
                    return []
                return [self.new_session()]
            return [error("invalid_simulation", "Choose generation_failure, delay or recover.")]
        return [error("unknown_type", "Unknown command type.")]


def validate_coordinates(data: dict[str, Any]) -> dict[str, Any]:
    """Accept explicit declared source and finite normalized coordinates only."""
    source = data.get("source")
    if not isinstance(source, str) or source not in {"synthetic", "camera"}:
        raise ValueError("Tracker source must be explicitly synthetic or camera.")
    if type(data.get("valid")) is not bool:
        raise ValueError("Tracker valid must be an explicit boolean.")
    x, y = data.get("x"), data.get("y")
    if data["valid"]:
        # Check the normalized range before converting integers to floats in
        # isfinite: a valid JSON integer can be too large for that conversion.
        if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not 0 <= v <= 1 or not math.isfinite(v) for v in (x, y)):
            raise ValueError("Coordinates must be finite normalized x/y values in [0,1].")
    else:
        x = y = None
    return {"type": "coordinates", "x": x, "y": y, "valid": data["valid"], "source": source, "timestamp_ms": round(time.time() * 1000)}
