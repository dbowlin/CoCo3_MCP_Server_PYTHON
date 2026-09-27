"""Section 1 — Lua bridge newline JSON protocol."""

from __future__ import annotations

import json
import unittest

from coco3_mcp.protocol import encode_request, parse_response_line


class ProtocolTests(unittest.TestCase):
    def test_encode_request_writes_one_json_object_and_a_newline(self) -> None:
        line = encode_request(
            {
                "id": "1",
                "cmd": "mount",
                "params": {"briefname": "flop1", "path": r"C:\games\a.dsk"},
            }
        )
        self.assertIn("\n", line)
        self.assertEqual(line.index("\n"), len(line) - 1)
        self.assertEqual(
            line,
            json.dumps(
                {
                    "id": "1",
                    "cmd": "mount",
                    "params": {"briefname": "flop1", "path": r"C:\games\a.dsk"},
                },
                separators=(",", ":"),
            )
            + "\n",
        )

    def test_encode_request_defaults_omitted_params_to_an_object(self) -> None:
        self.assertEqual(
            encode_request({"id": "2", "cmd": "status"}),
            json.dumps({"id": "2", "cmd": "status", "params": {}}, separators=(",", ":")) + "\n",
        )

    def test_parse_response_line_accepts_success_missing_result_and_errors(self) -> None:
        self.assertEqual(
            parse_response_line('{"id":"1","ok":true,"result":{"t":1}}\n'),
            {"id": "1", "ok": True, "result": {"t": 1}},
        )
        self.assertEqual(
            parse_response_line('  {"id":"1","ok":true}  \n'),
            {"id": "1", "ok": True, "result": {}},
        )
        self.assertEqual(
            parse_response_line('{"id":"1","ok":false,"error":"no flop1 image device"}'),
            {"id": "1", "ok": False, "error": "no flop1 image device"},
        )
        self.assertEqual(
            parse_response_line('{"id":"1","ok":false,"error":12}'),
            {"id": "1", "ok": False, "error": "bridge error"},
        )

    def test_parse_response_line_rejects_malformed_lines(self) -> None:
        for line in (
            "not json",
            '{"ok":true}',
            '{"id":1,"ok":true}',
            '{"id":"1","ok":"yes"}',
        ):
            with self.assertRaises(ValueError):
                parse_response_line(line)


if __name__ == "__main__":
    unittest.main()
