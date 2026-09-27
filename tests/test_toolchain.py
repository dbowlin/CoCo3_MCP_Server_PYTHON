"""Section 2 — ToolShed decb disk planning and execution."""

from __future__ import annotations

import unittest
from typing import Any

from coco3_mcp.toolchain import create_toolchain, plan_decb_steps


class ToolchainTests(unittest.TestCase):
    def test_plan_decb_steps_tokenizes_basic_and_copies_bin_data(self) -> None:
        self.assertEqual(
            plan_decb_steps(
                {
                    "dskPath": r"C:\work\hi.dsk",
                    "files": [
                        {"hostPath": r"C:\work\hi.bas", "cocoName": "HI.BAS", "kind": "bas"},
                        {"hostPath": r"C:\work\hi.bin", "cocoName": "HI.BIN", "kind": "bin"},
                        {"hostPath": r"C:\work\hi.dat", "cocoName": "HI.DAT", "kind": "data"},
                    ],
                }
            ),
            [
                {"args": ["dskini", "-3", r"C:\work\hi.dsk"]},
                {"args": ["copy", "-t", r"C:\work\hi.bas", r"C:\work\hi.dsk,HI.BAS"]},
                {"args": ["copy", r"C:\work\hi.bin", r"C:\work\hi.dsk,HI.BIN"]},
                {"args": ["copy", r"C:\work\hi.dat", r"C:\work\hi.dsk,HI.DAT"]},
            ],
        )

    def test_plan_decb_steps_rejects_invalid_names(self) -> None:
        dsk_path = "a.dsk"
        with self.assertRaises(ValueError):
            plan_decb_steps(
                {"dskPath": dsk_path, "files": [{"hostPath": "a", "cocoName": "", "kind": "bas"}]}
            )
        with self.assertRaises(ValueError):
            plan_decb_steps(
                {"dskPath": dsk_path, "files": [{"hostPath": "a", "cocoName": "A,B", "kind": "bas"}]}
            )
        with self.assertRaises(ValueError):
            plan_decb_steps(
                {"dskPath": dsk_path, "files": [{"hostPath": "a", "cocoName": "A/B", "kind": "bin"}]}
            )
        with self.assertRaises(ValueError):
            plan_decb_steps(
                {"dskPath": dsk_path, "files": [{"hostPath": "a", "cocoName": r"A\B", "kind": "data"}]}
            )
        with self.assertRaises(ValueError):
            plan_decb_steps(
                {
                    "dskPath": dsk_path,
                    "files": [{"hostPath": "a", "cocoName": "A.BAS", "kind": "nope"}],
                }
            )

    def test_build_disk_stops_at_first_error(self) -> None:
        seen: list[dict[str, Any]] = []

        def run(command: str, args: list[str]) -> dict[str, Any]:
            seen.append({"command": command, "args": args})
            if args[0] == "copy":
                return {"code": 1, "stdout": "", "stderr": "disk full"}
            return {"code": 0, "stdout": "", "stderr": ""}

        toolchain = create_toolchain(r"C:\toolshed\decb.exe", runner=run)
        with self.assertRaisesRegex(RuntimeError, "disk full"):
            toolchain.build_disk(
                {
                    "dskPath": "o.dsk",
                    "files": [
                        {"hostPath": "a.bas", "cocoName": "A.BAS", "kind": "bas"},
                        {"hostPath": "b.bin", "cocoName": "B.BIN", "kind": "bin"},
                    ],
                }
            )
        self.assertEqual(
            [call["command"] for call in seen],
            [r"C:\toolshed\decb.exe", r"C:\toolshed\decb.exe"],
        )
        self.assertEqual(
            [call["args"] for call in seen],
            [
                ["dskini", "-3", "o.dsk"],
                ["copy", "-t", "a.bas", "o.dsk,A.BAS"],
            ],
        )

    def test_build_disk_uses_stdout_when_stderr_empty(self) -> None:
        def boom(_command: str, args: list[str]) -> dict[str, Any]:
            if args[0] == "dskini":
                return {"code": 2, "stdout": "boom-stdout", "stderr": ""}
            return {"code": 0, "stdout": "", "stderr": ""}

        toolchain = create_toolchain("decb", runner=boom)
        with self.assertRaisesRegex(RuntimeError, "boom-stdout"):
            toolchain.build_disk({"dskPath": "o.dsk", "files": []})

        ok = create_toolchain(
            "decb",
            runner=lambda *_a, **_k: {"code": 0, "stdout": "", "stderr": ""},
        )
        result = ok.build_disk(
            {
                "dskPath": "o.dsk",
                "files": [{"hostPath": "a.bas", "cocoName": "A.BAS", "kind": "bas"}],
            }
        )
        self.assertEqual(
            result,
            {
                "dskPath": "o.dsk",
                "steps": ["dskini -3 o.dsk", "copy -t a.bas o.dsk,A.BAS"],
            },
        )


if __name__ == "__main__":
    unittest.main()
