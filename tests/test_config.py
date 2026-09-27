"""Section 1 — config loading and .env parsing."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from coco3_mcp.config import load_config, load_dotenv


class LoadConfigTests(unittest.TestCase):
    def test_load_config_applies_documented_defaults(self) -> None:
        root = Path("C:/coco/MCP").resolve()
        cfg = load_config({}, root)
        self.assertEqual(cfg.bridge_port, 18765)
        self.assertEqual(cfg.coco_ram, "512K")
        self.assertEqual(cfg.mame_path, "")
        self.assertEqual(cfg.mame_rom_path, "")
        self.assertEqual(cfg.decb_path, "decb")
        self.assertEqual(cfg.root_dir, root)
        self.assertEqual(cfg.bridge_lua_path, root / "scripts" / "bridge.lua")
        self.assertEqual(cfg.snapshot_dir, root / "snapshots")
        self.assertEqual(cfg.state_dir, root / "states")
        self.assertEqual(cfg.work_dir, root / "work")
        self.assertEqual(cfg.log_dir, root / "logs")
        for value in (
            cfg.root_dir,
            cfg.bridge_lua_path,
            cfg.snapshot_dir,
            cfg.state_dir,
            cfg.work_dir,
            cfg.log_dir,
        ):
            self.assertTrue(value.is_absolute())

    def test_load_config_resolves_relative_root_and_honors_overrides(self) -> None:
        cfg = load_config(
            {
                "BRIDGE_PORT": "19000",
                "COCO_RAM": "128K",
                "MAME_PATH": r"C:\mame\mame.exe",
                "MAME_ROMPATH": r"C:\mame\roms",
                "DECB_PATH": r"C:\toolshed\decb.exe",
            },
            Path("relative-root"),
        )
        self.assertEqual(cfg.root_dir, Path("relative-root").resolve())
        self.assertEqual(cfg.bridge_port, 19000)
        self.assertEqual(cfg.coco_ram, "128K")
        self.assertEqual(cfg.mame_path, str(Path(r"C:\mame\mame.exe")))
        self.assertEqual(cfg.mame_rom_path, str(Path(r"C:\mame\roms")))
        self.assertEqual(cfg.decb_path, str(Path(r"C:\toolshed\decb.exe")))
        self.assertEqual(cfg.bridge_lua_path, cfg.root_dir / "scripts" / "bridge.lua")

    def test_load_config_rejects_a_bad_bridge_port(self) -> None:
        root = Path("root").resolve()
        for port in ("nope", "0", "65536", "1.5", "-1"):
            with self.assertRaises(ValueError) as ctx:
                load_config({"BRIDGE_PORT": port}, root)
            self.assertIn(port, str(ctx.exception))

    def test_load_dotenv_parses_comments_blanks_and_quotes(self) -> None:
        with tempfile.TemporaryDirectory(prefix="coco-env-") as tmp:
            file = Path(tmp) / ".env"
            file.write_text(
                "\n".join(
                    [
                        "# comment",
                        "BRIDGE_PORT=19001",
                        r'MAME_PATH="C:\mame\mame.exe"',
                        "DECB_PATH='decb.exe'",
                        "",
                        "COCO_RAM=512K",
                        "",
                    ]
                ),
                encoding="utf-8",
            )
            self.assertEqual(
                load_dotenv(file),
                {
                    "BRIDGE_PORT": "19001",
                    "MAME_PATH": r"C:\mame\mame.exe",
                    "DECB_PATH": "decb.exe",
                    "COCO_RAM": "512K",
                },
            )
            self.assertEqual(load_dotenv(Path(tmp) / "missing.env"), {})


if __name__ == "__main__":
    unittest.main()
