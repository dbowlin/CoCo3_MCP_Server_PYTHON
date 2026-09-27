"""Standalone HTTP MCP server — any local app can call tools."""

from __future__ import annotations

import json
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from coco3_mcp.client import call_tool, probe
from coco3_mcp.http_server import serve_http
from coco3_mcp.mcp_server import SERVER_NAME
from tests.test_stdio_list import TOOL_NAMES


class _FakeMame:
    def status(self) -> dict:
        return {"running": False, "pid": None}


class HttpServerTests(unittest.TestCase):
    def setUp(self) -> None:
        self._httpd: list = []
        self._thread = threading.Thread(
            target=serve_http,
            args=({"mame": _FakeMame()}, "127.0.0.1", 0),
            kwargs={"httpd_out": self._httpd},
            daemon=True,
        )
        self._thread.start()
        for _ in range(50):
            if self._httpd:
                break
            self._thread.join(0.05)
        self.assertTrue(self._httpd, "HTTP server did not bind")
        self.port = self._httpd[0].server_address[1]

    def tearDown(self) -> None:
        if self._httpd:
            self._httpd[0].shutdown()
        self._thread.join(2)

    def test_health_identifies_the_server(self) -> None:
        self.assertTrue(probe("127.0.0.1", self.port))
        with urlopen(f"http://127.0.0.1:{self.port}/", timeout=2) as resp:
            body = json.load(resp)
        self.assertTrue(body["ok"])
        self.assertEqual(body["name"], SERVER_NAME)
        self.assertEqual(body["mcp"], f"http://127.0.0.1:{self.port}/mcp")

    def test_post_lists_every_coco_tool(self) -> None:
        listed = self._post({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        names = sorted(tool["name"] for tool in listed["result"]["tools"])
        self.assertEqual(names, TOOL_NAMES)

    def test_call_tool_from_the_client_helper(self) -> None:
        result = call_tool("coco_status", host="127.0.0.1", port=self.port)
        text = result["content"][0]["text"]
        self.assertIn('"running": false', text)

    def test_invalid_json_is_http_400(self) -> None:
        req = Request(
            f"http://127.0.0.1:{self.port}/mcp",
            data=b"not-json",
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with self.assertRaises(HTTPError) as ctx:
            urlopen(req, timeout=2)
        self.assertEqual(ctx.exception.code, 400)

    def _post(self, message: dict) -> dict:
        req = Request(
            f"http://127.0.0.1:{self.port}/mcp",
            data=json.dumps(message).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(req, timeout=2) as resp:
            self.assertEqual(resp.status, 200)
            return json.load(resp)


if __name__ == "__main__":
    unittest.main()
