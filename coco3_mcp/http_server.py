"""HTTP MCP endpoint so any local program can call tools."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Mapping

from coco3_mcp import __version__
from coco3_mcp.mcp_server import SERVER_NAME, McpStdioServer


class _Server(ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True


def _make_handler(mcp: McpStdioServer, lock: threading.Lock) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def address_string(self) -> str:
            return self.client_address[0]

        def log_message(self, fmt: str, *args: Any) -> None:
            return

        def do_GET(self) -> None:  # noqa: N802
            path = self.path.split("?", 1)[0].rstrip("/") or "/"
            if path != "/":
                self.send_error(404)
                return
            host, port = self.server.server_address[:2]
            self._send_json(
                200,
                {
                    "ok": True,
                    "name": SERVER_NAME,
                    "version": __version__,
                    "mcp": f"http://{host}:{port}/mcp",
                },
            )

        def do_POST(self) -> None:  # noqa: N802
            path = self.path.split("?", 1)[0].rstrip("/") or "/"
            if path != "/mcp":
                self.send_error(404)
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                self._send_json(
                    400,
                    {"jsonrpc": "2.0", "error": {"code": -32700, "message": "bad Content-Length"}},
                )
                return
            raw = self.rfile.read(length) if length else b""
            try:
                message = json.loads(raw.decode("utf-8"))
            except (UnicodeError, json.JSONDecodeError):
                self._send_json(
                    400,
                    {"jsonrpc": "2.0", "error": {"code": -32700, "message": "Parse error"}},
                )
                return
            if not isinstance(message, dict):
                self._send_json(
                    400,
                    {"jsonrpc": "2.0", "error": {"code": -32600, "message": "Invalid request"}},
                )
                return
            with lock:
                reply = mcp.handle(message)
            if reply is None:
                self.send_response(204)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            self._send_json(200, reply)

        def _send_json(self, status: int, payload: dict[str, Any]) -> None:
            raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

    return Handler


def serve_http(
    deps: Mapping[str, Any],
    host: str,
    port: int,
    *,
    httpd_out: list | None = None,
) -> None:
    mcp = McpStdioServer(dict(deps))
    httpd = _Server((host, port), _make_handler(mcp, threading.Lock()))
    if httpd_out is not None:
        httpd_out.append(httpd)
    try:
        httpd.serve_forever(poll_interval=0.2)
    finally:
        httpd.server_close()
