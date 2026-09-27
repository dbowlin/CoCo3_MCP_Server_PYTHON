"""Stdio must answer Cursor's newline-delimited JSON, not only Content-Length."""

from __future__ import annotations

import json
import unittest
from io import BytesIO

from coco3_mcp.mcp_server import run_stdio_server


class StdioFramingTests(unittest.TestCase):
    def test_newline_delimited_initialize_roundtrip(self) -> None:
        message = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-11-25",
                "capabilities": {},
                "clientInfo": {"name": "cursor", "version": "1"},
            },
        }
        stdin = BytesIO((json.dumps(message) + "\n").encode("utf-8"))
        stdout = BytesIO()
        run_stdio_server({}, stdin=stdin, stdout=stdout)
        raw = stdout.getvalue()
        self.assertFalse(raw.startswith(b"Content-Length"))
        reply = json.loads(raw.decode("utf-8"))
        self.assertEqual(reply["id"], 1)
        self.assertEqual(reply["result"]["protocolVersion"], "2024-11-05")


if __name__ == "__main__":
    unittest.main()
