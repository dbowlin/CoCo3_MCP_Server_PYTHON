"""Call a running CoCo 3 MCP server from any Python program."""

from __future__ import annotations

import json
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen

from coco3_mcp.endpoint import DEFAULT_HOST, DEFAULT_PORT, endpoint_url, health_url


def probe(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT, timeout_s: float = 0.5) -> bool:
    try:
        with urlopen(health_url(host, port), timeout=timeout_s) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except (OSError, URLError, ValueError, json.JSONDecodeError):
        return False
    return data.get("ok") is True and data.get("name") == "coco3-mcp-bridge"


def call_tool(
    name: str,
    arguments: dict[str, Any] | None = None,
    *,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    timeout_s: float = 60,
) -> dict[str, Any]:
    message = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": name, "arguments": arguments or {}},
    }
    body = _post(host, port, message, timeout_s)
    if "error" in body:
        error = body["error"]
        text = error.get("message") if isinstance(error, dict) else str(error)
        raise RuntimeError(text)
    result = body.get("result")
    if not isinstance(result, dict):
        raise RuntimeError("mcp response missing result")
    return result


def _post(host: str, port: int, message: dict[str, Any], timeout_s: float) -> dict[str, Any]:
    raw = json.dumps(message).encode("utf-8")
    req = Request(
        endpoint_url(host, port),
        data=raw,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(req, timeout=timeout_s) as resp:
        return json.loads(resp.read().decode("utf-8"))
