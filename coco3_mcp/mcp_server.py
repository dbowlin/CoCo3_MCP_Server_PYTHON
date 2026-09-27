"""Minimal MCP server over stdio using only the Python standard library.

Wire format: JSON-RPC 2.0. Cursor sends one JSON object per line. The
Content-Length framing used by the local tests is still accepted.
"""

from __future__ import annotations

import json
import sys
from typing import Any, BinaryIO, Callable, Mapping

from coco3_mcp import __version__
from coco3_mcp.tools import INPUT_SCHEMAS, TOOL_INFO, create_tool_handlers

PROTOCOL_VERSION = "2024-11-05"
SERVER_NAME = "coco3-mcp-bridge"


class McpStdioServer:
    def __init__(self, deps: Mapping[str, Any]) -> None:
        self._handlers = create_tool_handlers(dict(deps))
        self._tools: list[dict[str, Any]] = []
        for name, info in TOOL_INFO.items():
            self._tools.append(
                {
                    "name": name,
                    "description": info["description"],
                    "inputSchema": INPUT_SCHEMAS.get(
                        name, {"type": "object", "properties": {}}
                    ),
                }
            )
        self._tools.sort(key=lambda tool: tool["name"])

    def register_tool(
        self,
        name: str,
        description: str,
        input_schema: dict[str, Any],
        handler: Callable[[dict[str, Any]], dict[str, Any]],
    ) -> None:
        self._handlers[name] = handler
        self._tools = [tool for tool in self._tools if tool["name"] != name]
        self._tools.append(
            {"name": name, "description": description, "inputSchema": input_schema}
        )
        self._tools.sort(key=lambda tool: tool["name"])

    def handle(self, message: dict[str, Any]) -> dict[str, Any] | None:
        method = message.get("method")
        msg_id = message.get("id")
        params = message.get("params") or {}

        if method == "initialize":
            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {
                    "protocolVersion": PROTOCOL_VERSION,
                    "capabilities": {"tools": {"listChanged": False}},
                    "serverInfo": {"name": SERVER_NAME, "version": __version__},
                },
            }

        if method in ("notifications/initialized", "initialized"):
            return None

        if method == "ping":
            return {"jsonrpc": "2.0", "id": msg_id, "result": {}}

        if method == "tools/list":
            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {"tools": self._tools},
            }

        if method == "tools/call":
            name = str(params.get("name") or "")
            arguments = params.get("arguments") or {}
            handler = self._handlers.get(name)
            if handler is None:
                return {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "error": {"code": -32601, "message": f"Unknown tool: {name}"},
                }
            try:
                result = handler(arguments if isinstance(arguments, dict) else {})
            except Exception as exc:  # noqa: BLE001
                result = {
                    "isError": True,
                    "content": [{"type": "text", "text": str(exc)}],
                }
            return {"jsonrpc": "2.0", "id": msg_id, "result": result}

        if msg_id is None:
            return None
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "error": {"code": -32601, "message": f"Method not found: {method}"},
        }


def _read_message(stdin: BinaryIO) -> tuple[dict[str, Any] | None, str]:
    while True:
        line = stdin.readline()
        if line == b"":
            return None, "content-length"
        if line not in (b"\n", b"\r\n"):
            break
    if line.lstrip().startswith(b"{"):
        return json.loads(line.decode("utf-8")), "ndjson"

    headers: dict[str, str] = {}
    while True:
        if line in (b"\n", b"\r\n"):
            break
        if b":" in line:
            key, value = line.split(b":", 1)
            headers[key.decode("ascii").strip().lower()] = value.decode("ascii").strip()
        line = stdin.readline()
        if line == b"":
            return None, "content-length"
    if "content-length" not in headers:
        raise RuntimeError("missing Content-Length header")
    length = int(headers["content-length"])
    body = stdin.read(length)
    if len(body) < length:
        return None, "content-length"
    return json.loads(body.decode("utf-8")), "content-length"


def _write_message(
    stdout: BinaryIO, message: dict[str, Any], framing: str = "content-length"
) -> None:
    raw = json.dumps(message, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    if framing == "ndjson":
        stdout.write(raw + b"\n")
    else:
        stdout.write(f"Content-Length: {len(raw)}\r\n\r\n".encode("ascii"))
        stdout.write(raw)
    stdout.flush()


def run_stdio_server(
    deps: Mapping[str, Any],
    stdin: BinaryIO | None = None,
    stdout: BinaryIO | None = None,
) -> None:
    server = McpStdioServer(deps)
    in_stream = stdin if stdin is not None else sys.stdin.buffer
    out_stream = stdout if stdout is not None else sys.stdout.buffer
    while True:
        try:
            message, framing = _read_message(in_stream)
        except Exception as exc:  # noqa: BLE001
            print(f"mcp read error: {exc}", file=sys.stderr)
            continue
        if message is None:
            break
        reply = server.handle(message)
        if reply is not None:
            _write_message(out_stream, reply, framing)
