"""Section 2 — MAME CLI args."""

from __future__ import annotations

import unittest
from pathlib import Path

from coco3_mcp.config import load_config
from coco3_mcp.mame_process import build_mame_args


class MameArgsTests(unittest.TestCase):
    def test_build_mame_args_matches_required_coco3_command(self) -> None:
        root = Path("C:/coco/MCP").resolve()
        cfg = load_config(
            {
                "MAME_PATH": r"C:\mame\mame.exe",
                "MAME_ROMPATH": r"C:\mame\roms",
                "COCO_RAM": "512K",
            },
            root,
        )
        self.assertEqual(
            build_mame_args(cfg),
            [
                "coco3",
                "-window",
                "-skip_gameinfo",
                "-natural",
                "-nomouse",
                "-mouse_device",
                "none",
                "-ext",
                "fdc",
                "-ramsize",
                "512K",
                "-rompath",
                str(Path(r"C:\mame\roms")),
                "-autoboot_script",
                str(root / "scripts" / "bridge.lua"),
                "-autoboot_delay",
                "0",
                "-snapshot_directory",
                str(root / "snapshots"),
                "-state_directory",
                str(root / "states"),
            ],
        )
        self.assertNotIn("-console", build_mame_args(cfg))
        self.assertTrue(Path(build_mame_args(cfg)[14]).is_absolute())


if __name__ == "__main__":
    unittest.main()
