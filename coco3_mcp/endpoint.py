"""Published address of the standalone CoCo 3 MCP server."""

from __future__ import annotations

from pathlib import Path
from typing import Mapping

from coco3_mcp.mcp_server import SERVER_NAME

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 18766


def bind_from_env(env: Mapping[str, str | None]) -> tuple[str, int]:
    host = (env.get("MCP_HOST") or "").strip() or DEFAULT_HOST
    raw = env.get("MCP_PORT")
    if raw is None or str(raw).strip() == "":
        return host, DEFAULT_PORT
    text = str(raw).strip()
    if not text.isdigit():
        raise ValueError(f"invalid MCP_PORT: {raw}")
    port = int(text)
    if port < 1 or port > 65535:
        raise ValueError(f"invalid MCP_PORT: {raw}")
    return host, port


def endpoint_url(host: str, port: int) -> str:
    return f"http://{host}:{port}/mcp"


def health_url(host: str, port: int) -> str:
    return f"http://{host}:{port}/"


def endpoint_document(*, root: Path, python: str, host: str, port: int) -> dict:
    cwd = str(Path(root))
    return {
        "name": SERVER_NAME,
        "transport": "http",
        "framing": "json-rpc",
        "host": host,
        "port": port,
        "url": endpoint_url(host, port),
        "health": health_url(host, port),
        "listen": {
            "command": python,
            "args": ["-m", "coco3_mcp.serve"],
            "cwd": cwd,
        },
    }
