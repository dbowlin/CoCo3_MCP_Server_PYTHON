"""Section 3 — bridge.lua source guards."""

from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LUA = ROOT / "scripts" / "bridge.lua"


class LuaBridgeTests(unittest.TestCase):
    def test_bridge_lua_stays_on_mame_allow_list(self) -> None:
        src = LUA.read_text(encoding="utf-8")
        self.assertTrue(LUA.is_file())
        self.assertIsNone(re.search(r"require\s*\(", src))
        self.assertNotIn("floppydisc", src)
        self.assertNotIn("hard_reset", src)
        self.assertIsNone(re.search(r"mame\.machine\s*\(", src))
        self.assertNotIn("0E00", src)
        for needle in (
            "manager.machine",
            "emu.register_frame",
            "emu.file",
            "socket.127.0.0.1",
            "BRIDGE_PORT",
            "18765",
            "os.getenv",
            "in_use",
            "is_posting",
            "empty",
            "soft_reset",
            ":snapshot",
            "video:snapshot",
            "read_u8",
            "write_u8",
            "briefname",
            "brief_instance_name",
            "flop1",
            "flop2",
            "pcall",
            ":save",
            ":load",
            ":unload",
            "ping",
            "wait_idle",
            "list_images",
            "read_mem",
            "write_mem",
            "save_state",
            "load_state",
            "unmount",
            "machine not ready",
            "1024",
            "invalid data byte",
            "address outside current 64K MMU window",
            "^%x%x$",
        ):
            self.assertIn(needle, src, needle)
        self.assertEqual(src.count("post_coded"), 1)

    def test_write_mem_validates_whole_data_string(self) -> None:
        src = LUA.read_text(encoding="utf-8")
        start = src.index("local function cmd_write_mem")
        end = src.index("\nend", start)
        body = src[start:end]
        self.assertRegex(body, r'error\("address outside current 64K MMU window"\)')
        self.assertRegex(body, r'error\("invalid data byte: "')
        self.assertRegex(body, r'string\.match\(token, "\^%x%x\$"\)')

    def test_mount_does_not_unload_before_load(self) -> None:
        src = LUA.read_text(encoding="utf-8")
        start = src.index("local function cmd_mount")
        end = src.index("\nend", start)
        body = src[start:end]
        self.assertIsNone(re.search(r":unload\(\)", body))
        self.assertRegex(body, r"image:load\(params\.path\)")


if __name__ == "__main__":
    unittest.main()
