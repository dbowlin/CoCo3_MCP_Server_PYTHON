"""Section 3 — source hygiene for the Python MCP server."""

from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT / "coco3_mcp"


class SourceRulesTests(unittest.TestCase):
    def test_server_source_never_writes_stdout_with_print(self) -> None:
        files = list(PKG.rglob("*.py"))
        self.assertGreater(len(files), 0)
        for file in files:
            text = file.read_text(encoding="utf-8")
            # Allow print only in __main__ diagnostics that go to stderr via explicit file=.
            for line in text.splitlines():
                stripped = line.strip()
                if stripped.startswith("#"):
                    continue
                if "print(" in stripped:
                    self.assertIn(
                        "file=sys.stderr",
                        stripped,
                        f"{file} uses print without file=sys.stderr: {stripped}",
                    )

    def test_package_has_no_third_party_imports(self) -> None:
        banned = (
            "modelcontextprotocol",
            "mcp.server",
            "pydantic",
            "zod",
            "anyio",
            "httpx",
            "requests",
        )
        for file in PKG.rglob("*.py"):
            text = file.read_text(encoding="utf-8")
            for name in banned:
                self.assertNotIn(name, text, f"{file} imports/mentions {name}")

    def test_entry_uses_stdlib_stdio_mcp(self) -> None:
        main = (PKG / "__main__.py").read_text(encoding="utf-8")
        self.assertIn("run_stdio_server", main)
        self.assertIn("coco3-mcp-bridge", (PKG / "mcp_server.py").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
