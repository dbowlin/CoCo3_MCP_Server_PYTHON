"""Newline-delimited JSON protocol between the MCP server and bridge.lua."""

from __future__ import annotations

import json
from typing import Any, Mapping, TypedDict


class BridgeRequest(TypedDict, total=False):
    id: str
    cmd: str
    params: Mapping[str, Any]


class BridgeSuccess(TypedDict):
    id: str
    ok: bool
    result: Any


class BridgeFailure(TypedDict):
    id: str
    ok: bool
    error: str


def encode_request(req: Mapping[str, Any]) -> str:
    payload = {
        "id": req["id"],
        "cmd": req["cmd"],
        "params": req.get("params") if req.get("params") is not None else {},
    }
    return json.dumps(payload, separators=(",", ":")) + "\n"


def parse_response_line(line: str) -> BridgeSuccess | BridgeFailure:
    try:
        value = json.loads(line.strip())
    except json.JSONDecodeError as exc:
        raise ValueError("invalid bridge json") from exc
    if not isinstance(value, dict):
        raise ValueError("invalid bridge response")
    if not isinstance(value.get("id"), str):
        raise ValueError("invalid bridge id")
    if not isinstance(value.get("ok"), bool):
        raise ValueError("invalid bridge ok")
    if value["ok"]:
        result = value.get("result")
        if result is None:
            result = {}
        return {"id": value["id"], "ok": True, "result": result}
    error = value.get("error")
    return {
        "id": value["id"],
        "ok": False,
        "error": error if isinstance(error, str) else "bridge error",
    }
