"""Section 3 — stdio MCP tools/list integration (stdlib client)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYTHON = Path(__file__).resolve().parents[2] / ".python" / "python.exe"

TOOL_NAMES = [
    "coco_build_disk",
    "coco_list_images",
    "coco_load_state",
    "coco_mount_flop",
    "coco_read_memory",
    "coco_save_state",
    "coco_snapshot",
    "coco_soft_reset",
    "coco_start",
    "coco_status",
    "coco_stop",
    "coco_type",
    "coco_unmount_flop",
    "coco_write_memory",
]


class StdioListTests(unittest.TestCase):
    def test_stdio_server_lists_every_coco_tool(self) -> None:
        py = str(PYTHON if PYTHON.is_file() else sys.executable)
        env = {
            **os.environ,
            "MAME_PATH": str(ROOT / "mame.exe"),
            "MAME_ROMPATH": str(ROOT / "roms"),
        }
        proc = subprocess.Popen(
            [py, "-m", "coco3_mcp"],
            cwd=str(ROOT),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
        )
        assert proc.stdin is not None and proc.stdout is not None and proc.stderr is not None

        stderr_chunks: list[bytes] = []

        def drain_stderr() -> None:
            assert proc.stderr is not None
            while True:
                chunk = proc.stderr.read(256)
                if not chunk:
                    return
                stderr_chunks.append(chunk)

        threading.Thread(target=drain_stderr, daemon=True).start()

        def write_msg(msg: dict) -> None:
            raw = json.dumps(msg, separators=(",", ":")).encode("utf-8")
            proc.stdin.write(f"Content-Length: {len(raw)}\r\n\r\n".encode("ascii") + raw)
            proc.stdin.flush()

        def read_msg(timeout_s: float = 10.0) -> dict:
            deadline = time.time() + timeout_s
            headers: dict[str, str] = {}
            while True:
                if time.time() > deadline:
                    err = b"".join(stderr_chunks).decode("utf-8", errors="replace")[-500:]
                    raise TimeoutError(f"headers timeout; stderr={err}")
                line = proc.stdout.readline()
                if line == b"":
                    err = b"".join(stderr_chunks).decode("utf-8", errors="replace")[-500:]
                    raise RuntimeError(f"stdio closed; stderr={err}")
                if line in (b"\n", b"\r\n"):
                    if headers:
                        break
                    continue
                if b":" in line:
                    key, value = line.split(b":", 1)
                    headers[key.decode("ascii").strip().lower()] = value.decode("ascii").strip()
            length = int(headers["content-length"])
            body = proc.stdout.read(length)
            return json.loads(body.decode("utf-8"))

        try:
            write_msg(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {},
                        "clientInfo": {"name": "coco3-test", "version": "1.0.0"},
                    },
                }
            )
            init = read_msg()
            self.assertEqual(init["id"], 1)
            self.assertIn("result", init)

            write_msg({"jsonrpc": "2.0", "method": "notifications/initialized"})
            write_msg({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
            listed = read_msg()
            names = sorted(tool["name"] for tool in listed["result"]["tools"])
            self.assertEqual(names, TOOL_NAMES)
            read = next(t for t in listed["result"]["tools"] if t["name"] == "coco_read_memory")
            write = next(t for t in listed["result"]["tools"] if t["name"] == "coco_write_memory")
            self.assertRegex(read["description"], r"current 64K MMU window")
            self.assertRegex(read["description"], r"not physical RAM")
            self.assertRegex(read["description"], r"\$0400")
            self.assertRegex(write["description"], r"current 64K MMU window")
            self.assertRegex(write["description"], r"not physical RAM")
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()


if __name__ == "__main__":
    unittest.main()
