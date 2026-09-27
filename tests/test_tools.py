"""Section 3 — MCP tool handlers (behavioral port of the TypeScript suite)."""

from __future__ import annotations

import base64
import json
import tempfile
import time
import unittest
from pathlib import Path
from typing import Any

from coco3_mcp.config import AppConfig, load_config
from coco3_mcp.tools import TOOL_INFO, create_tool_handlers, register_tools

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


def text_of(result: dict[str, Any]) -> str:
    return "\n".join(
        part.get("text", "") for part in result.get("content", []) if part.get("type") == "text"
    )


class Harness:
    def __init__(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="coco-tools-"))
        (self.root / "snapshots").mkdir(parents=True)
        (self.root / "states").mkdir(parents=True)
        self.config = load_config(
            {
                "MAME_PATH": str(self.root / "mame.exe"),
                "MAME_ROMPATH": str(self.root / "roms"),
                "DECB_PATH": "decb",
            },
            self.root,
        )
        self.requests: list[dict[str, Any]] = []
        self.order: list[str] = []
        self.mame = {"started": 0, "stopped": 0, "running": False, "pid": None}
        self.ping_ok = True
        self.fail_cmds: set[str] = set()
        self.snapshot_mode = "screen"
        self.list_result: Any = [
            {"tag": ":flop1", "briefname": "flop1", "filename": "A.DSK", "exists": True}
        ]
        self.toolchain_error: str | None = None
        self.built: Any = None
        self._idle_calls = 0
        self.deps = self._build_deps()
        self.handlers = create_tool_handlers(self.deps)

    def _build_deps(self) -> dict[str, Any]:
        state = self

        class Bridge:
            listening = False
            port = state.config.bridge_port
            address = "127.0.0.1"

            def start(self) -> None:
                state.order.append("bridge-start")
                self.listening = True

            def stop(self) -> None:
                state.order.append("bridge-stop")
                self.listening = False

            def request(self, cmd: str, params: dict[str, Any], timeout_ms: int = 5000) -> dict[str, Any]:
                del timeout_ms
                state.requests.append({"cmd": cmd, "params": params})
                if cmd == "ping":
                    if state.ping_ok:
                        return {"id": "1", "ok": True, "result": {"t": 0}}
                    return {"id": "1", "ok": False, "error": "no bridge"}
                if cmd in state.fail_cmds:
                    return {"id": "1", "ok": False, "error": "no flop1 image device"}
                if cmd == "wait_idle":
                    state._idle_calls += 1
                    return {"id": "1", "ok": True, "result": {"idle": state._idle_calls >= 2}}
                if cmd == "status":
                    return {
                        "id": "1",
                        "ok": True,
                        "result": {
                            "driver": "coco3",
                            "flop1": "GAME.DSK",
                            "posting": False,
                            "empty": True,
                        },
                    }
                if cmd == "list_images":
                    return {"id": "1", "ok": True, "result": state.list_result}
                if cmd == "read_mem":
                    return {"id": "1", "ok": True, "result": {"data": "41 42"}}
                if cmd == "write_mem":
                    return {"id": "1", "ok": True, "result": {"bytes": 2}}
                if cmd == "snapshot":
                    path = Path(str(params["path"]))
                    assert not path.exists()
                    if state.snapshot_mode == "screen":
                        path.write_bytes(b"PNGDATA")
                        return {"id": "1", "ok": True, "result": {"method": "screen", "path": str(path)}}
                    if state.snapshot_mode == "video":
                        (state.config.snapshot_dir / "shot.png").write_bytes(b"VIDEO")
                        return {
                            "id": "1",
                            "ok": True,
                            "result": {
                                "method": "video",
                                "snapshotDirectory": params["snapshotDirectory"],
                                "path": str(path),
                            },
                        }
                    return {"id": "1", "ok": True, "result": {"method": "screen", "path": str(path)}}
                if cmd == "type":
                    return {"id": "1", "ok": True, "result": {"queued": True}}
                if cmd == "soft_reset":
                    return {"id": "1", "ok": True, "result": {"reset": "soft"}}
                if cmd in ("save_state", "load_state"):
                    return {"id": "1", "ok": True, "result": {"scheduled": True, "name": params["name"]}}
                return {
                    "id": "1",
                    "ok": True,
                    "result": {"briefname": params.get("briefname"), "filename": params.get("path")},
                }

        class Mame:
            def build_args(self) -> list[str]:
                return []

            def start(self) -> dict[str, Any]:
                state.mame["started"] = int(state.mame["started"]) + 1
                state.mame["running"] = True
                state.mame["pid"] = 4242
                state.order.append("mame-start")
                return {"started": True, "alreadyRunning": False, "pid": 4242}

            def stop(self) -> None:
                state.mame["stopped"] = int(state.mame["stopped"]) + 1
                state.mame["running"] = False
                state.mame["pid"] = None
                state.order.append("mame-stop")

            def status(self) -> dict[str, Any]:
                return {
                    "running": state.mame["running"],
                    "pid": state.mame["pid"],
                    "exitCode": None,
                }

            def on_unexpected_exit(self, _cb: Any) -> None:
                return None

        class Toolchain:
            def build_disk(self, req: dict[str, Any]) -> dict[str, Any]:
                state.built = req
                if state.toolchain_error:
                    raise RuntimeError(state.toolchain_error)
                return {"dskPath": req["dskPath"], "steps": ["dskini"]}

        return {
            "config": self.config,
            "mame": Mame(),
            "bridge": Bridge(),
            "toolchain": Toolchain(),
            "logger": type("L", (), {"log": lambda *_a, **_k: None})(),
        }

    def cleanup(self) -> None:
        import shutil

        shutil.rmtree(self.root, ignore_errors=True)


class ToolsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.box = Harness()

    def tearDown(self) -> None:
        self.box.cleanup()

    def test_tool_handlers_and_descriptions_cover_the_coco_set(self) -> None:
        self.assertEqual(sorted(self.box.handlers.keys()), TOOL_NAMES)
        self.assertEqual(sorted(TOOL_INFO.keys()), TOOL_NAMES)
        self.assertRegex(TOOL_INFO["coco_read_memory"]["description"], r"current 64K MMU window")
        self.assertRegex(TOOL_INFO["coco_read_memory"]["description"], r"not physical RAM")
        self.assertRegex(TOOL_INFO["coco_read_memory"]["description"], r"\$0400")
        self.assertRegex(TOOL_INFO["coco_write_memory"]["description"], r"current 64K MMU window")
        self.assertRegex(TOOL_INFO["coco_write_memory"]["description"], r"not physical RAM")
        registered: list[str] = []

        class FakeServer:
            def register_tool(self, name: str, *_a: Any, **_k: Any) -> None:
                registered.append(name)

        register_tools(FakeServer(), self.box.deps)
        self.assertEqual(sorted(registered), TOOL_NAMES)

    def test_coco_start_idempotent_when_ping_works(self) -> None:
        self.box.mame["running"] = True
        self.box.mame["pid"] = 99
        result = self.box.handlers["coco_start"]({})
        self.assertEqual(self.box.mame["started"], 0)
        self.assertEqual(
            json.loads(text_of(result)),
            {"ok": True, "alreadyRunning": True, "pid": 99, "bridge": True},
        )

    def test_coco_start_no_second_spawn_when_bridge_never_answers(self) -> None:
        self.box.mame["running"] = True
        self.box.mame["pid"] = 99
        self.box.ping_ok = False
        result = self.box.handlers["coco_start"]({})
        self.assertTrue(result.get("isError"))
        self.assertEqual(text_of(result), "no bridge")
        self.assertEqual(self.box.mame["started"], 0)
        self.assertEqual(self.box.mame["stopped"], 0)

    def test_coco_start_listens_before_spawn_and_stops_both_when_ping_fails(self) -> None:
        self.box.ping_ok = False
        result = self.box.handlers["coco_start"]({})
        self.assertTrue(result.get("isError"))
        self.assertEqual(text_of(result), "no bridge")
        self.assertEqual(
            [item for item in self.box.order if item.endswith("start")],
            ["bridge-start", "mame-start"],
        )
        self.assertLess(self.box.order.index("mame-stop"), self.box.order.index("bridge-stop"))
        self.assertEqual(self.box.mame["started"], 1)

    def test_coco_start_reports_fresh_process_when_ping_succeeds(self) -> None:
        result = self.box.handlers["coco_start"]({})
        self.assertFalse(result.get("isError"))
        self.assertEqual(
            json.loads(text_of(result)),
            {"ok": True, "alreadyRunning": False, "pid": 4242, "bridge": True},
        )
        self.assertEqual(
            [item for item in self.box.order if item.endswith("start")],
            ["bridge-start", "mame-start"],
        )

    def test_coco_stop_stops_mame_before_bridge(self) -> None:
        result = self.box.handlers["coco_stop"]({})
        self.assertFalse(result.get("isError"))
        self.assertEqual(self.box.order, ["mame-stop", "bridge-stop"])

    def test_coco_status_reports_process_and_bridge(self) -> None:
        down = json.loads(text_of(self.box.handlers["coco_status"]({})))
        self.assertFalse(down["running"])
        self.assertFalse(down["bridge"])
        self.assertFalse(any(req["cmd"] == "ping" for req in self.box.requests))

        self.box.mame["running"] = True
        self.box.mame["pid"] = 7
        up = json.loads(text_of(self.box.handlers["coco_status"]({})))
        self.assertEqual(
            up,
            {
                "running": True,
                "pid": 7,
                "bridge": True,
                "driver": "coco3",
                "flop1": "GAME.DSK",
                "posting": False,
                "empty": True,
            },
        )

    def test_coco_mount_flop_resolves_path_and_defaults(self) -> None:
        self.box.handlers["coco_mount_flop"]({"path": "disk.dsk"})
        self.box.handlers["coco_mount_flop"]({"path": r"C:\games\a.dsk", "drive": "flop2"})
        self.assertEqual(
            self.box.requests[0],
            {"cmd": "mount", "params": {"briefname": "flop1", "path": str(Path("disk.dsk").resolve())}},
        )
        self.assertEqual(
            self.box.requests[1],
            {
                "cmd": "mount",
                "params": {"briefname": "flop2", "path": str(Path(r"C:\games\a.dsk").resolve())},
            },
        )
        before = len(self.box.requests)
        bad = self.box.handlers["coco_mount_flop"]({"path": "a.dsk", "drive": "flop3"})
        self.assertTrue(bad.get("isError"))
        self.assertEqual(len(self.box.requests), before)

    def test_coco_mount_flop_returns_raw_lua_error(self) -> None:
        self.box.fail_cmds.add("mount")
        result = self.box.handlers["coco_mount_flop"]({"path": "a.dsk"})
        self.assertTrue(result.get("isError"))
        self.assertEqual(text_of(result), "no flop1 image device")

    def test_coco_unmount_flop_defaults_to_flop1(self) -> None:
        self.box.handlers["coco_unmount_flop"]({})
        self.assertEqual(self.box.requests[-1], {"cmd": "unmount", "params": {"briefname": "flop1"}})

    def test_coco_type_posts_and_waits_until_idle(self) -> None:
        self.box.handlers["coco_type"]({"text": "DIR"})
        self.assertEqual(sum(1 for req in self.box.requests if req["cmd"] == "type"), 1)
        self.assertEqual(
            next(req for req in self.box.requests if req["cmd"] == "type")["params"]["text"],
            "DIR{ENTER}",
        )
        self.assertGreaterEqual(sum(1 for req in self.box.requests if req["cmd"] == "wait_idle"), 2)

    def test_coco_type_enter_rules(self) -> None:
        self.box.handlers["coco_type"]({"text": "DIR{ENTER}"})
        self.assertEqual(
            next(req for req in self.box.requests if req["cmd"] == "type")["params"]["text"],
            "DIR{ENTER}",
        )
        self.box.requests.clear()
        self.box._idle_calls = 0
        self.box.handlers["coco_type"]({"text": "DIR", "pressEnter": False})
        self.assertEqual(
            next(req for req in self.box.requests if req["cmd"] == "type")["params"]["text"],
            "DIR",
        )

    def test_coco_snapshot_returns_png_from_screen(self) -> None:
        current = self.box.config.snapshot_dir / "current.png"
        current.write_bytes(b"STALE")
        result = self.box.handlers["coco_snapshot"]({})
        self.assertFalse(result.get("isError"))
        image = next(part for part in result["content"] if part["type"] == "image")
        self.assertEqual(image["mimeType"], "image/png")
        self.assertEqual(base64.b64decode(image["data"]), b"PNGDATA")
        self.assertRegex(text_of(result), r"current\.png")
        self.assertEqual(self.box.requests[0]["cmd"], "snapshot")
        self.assertEqual(self.box.requests[0]["params"]["path"], str(current))
        self.assertEqual(
            self.box.requests[0]["params"]["snapshotDirectory"],
            str(self.box.config.snapshot_dir),
        )

    def test_coco_snapshot_falls_back_to_newest_png(self) -> None:
        self.box.snapshot_mode = "video"
        old = self.box.config.snapshot_dir / "old.png"
        old.write_bytes(b"OLD")
        past = time.time() - 120
        import os

        os.utime(old, (past, past))
        (self.box.config.snapshot_dir / "current.png").write_bytes(b"STALE")
        result = self.box.handlers["coco_snapshot"]({})
        self.assertFalse(result.get("isError"))
        image = next(part for part in result["content"] if part["type"] == "image")
        self.assertEqual(base64.b64decode(image["data"]), b"VIDEO")
        self.assertRegex(text_of(result), r"shot\.png")

    def test_coco_snapshot_errors_when_no_png(self) -> None:
        self.box.snapshot_mode = "missing"
        (self.box.config.snapshot_dir / "current.png").write_bytes(b"STALE")
        result = self.box.handlers["coco_snapshot"]({})
        self.assertTrue(result.get("isError"))

    def test_coco_soft_reset_only(self) -> None:
        result = self.box.handlers["coco_soft_reset"]({})
        self.assertFalse(result.get("isError"))
        self.assertEqual(self.box.requests[-1]["cmd"], "soft_reset")
        self.assertFalse(any(req["cmd"] == "hard_reset" for req in self.box.requests))

    def test_coco_list_images(self) -> None:
        result = self.box.handlers["coco_list_images"]({})
        self.assertEqual(json.loads(text_of(result)), self.box.list_result)

    def test_coco_build_disk(self) -> None:
        files = [{"hostPath": "a.bas", "cocoName": "A.BAS", "kind": "bas"}]
        ok = self.box.handlers["coco_build_disk"]({"dskPath": "a.dsk", "files": files})
        self.assertFalse(ok.get("isError"))
        self.assertEqual(json.loads(text_of(ok)), {"dskPath": "a.dsk", "steps": ["dskini"]})
        self.assertEqual(self.box.built, {"dskPath": "a.dsk", "files": files})
        self.box.toolchain_error = "disk full"
        bad = self.box.handlers["coco_build_disk"]({"dskPath": "a.dsk", "files": files})
        self.assertTrue(bad.get("isError"))
        self.assertEqual(text_of(bad), "disk full")

    def test_memory_tools(self) -> None:
        read = self.box.handlers["coco_read_memory"]({"address": "0400", "length": 16})
        self.assertFalse(read.get("isError"))
        self.assertEqual(
            self.box.requests[-1],
            {"cmd": "read_mem", "params": {"address": "0400", "length": 16}},
        )
        self.assertEqual(json.loads(text_of(read))["data"], "41 42")
        normalized = self.box.handlers["coco_read_memory"]({"address": "0x400", "length": 1})
        self.assertFalse(normalized.get("isError"))
        self.assertEqual(self.box.requests[-1]["params"]["address"], "0400")
        self.assertEqual(self.box.requests[-1]["params"]["length"], 1)
        before_invalid = len(self.box.requests)
        zero = self.box.handlers["coco_read_memory"]({"address": "0400", "length": 0})
        huge = self.box.handlers["coco_read_memory"]({"address": "0400", "length": 65537})
        wide = self.box.handlers["coco_read_memory"]({"address": "10000", "length": 1})
        self.assertTrue(zero.get("isError"))
        self.assertTrue(huge.get("isError"))
        self.assertTrue(wide.get("isError"))
        self.assertEqual(len(self.box.requests), before_invalid)
        before = len(self.box.requests)
        self.box.handlers["coco_write_memory"]({"address": "0400", "data": "41 42"})
        self.assertEqual(
            self.box.requests[-1],
            {"cmd": "write_mem", "params": {"address": "0400", "data": "41 42"}},
        )
        self.assertGreater(len(self.box.requests), before)

    def test_save_and_load_state(self) -> None:
        missing = json.loads(text_of(self.box.handlers["coco_save_state"]({"name": "checkpoint"})))
        self.assertTrue(missing["scheduled"])
        self.assertFalse(missing["fileFound"])
        (self.box.config.state_dir / "checkpoint.sta").write_text("sta", encoding="utf-8")
        present = json.loads(text_of(self.box.handlers["coco_save_state"]({"name": "checkpoint"})))
        self.assertTrue(present["scheduled"])
        self.assertTrue(present["fileFound"])
        self.assertRegex(str(present["file"]), r"checkpoint")
        loaded = json.loads(text_of(self.box.handlers["coco_load_state"]({"name": "checkpoint"})))
        self.assertTrue(loaded["scheduled"])
        self.assertEqual(self.box.requests[-1]["cmd"], "load_state")
        self.assertEqual(self.box.requests[-1]["params"]["name"], "checkpoint")
        for name in ("", "a/b", r"a\b", "../x"):
            before = len(self.box.requests)
            saved = self.box.handlers["coco_save_state"]({"name": name})
            loaded_bad = self.box.handlers["coco_load_state"]({"name": name})
            self.assertTrue(saved.get("isError"))
            self.assertTrue(loaded_bad.get("isError"))
            self.assertEqual(len(self.box.requests), before)

    def test_coco_load_state_fails_fast_without_mame(self) -> None:
        before = len(self.box.requests)
        result = self.box.handlers["coco_load_state"]({"name": "never-saved"})
        self.assertTrue(result.get("isError"))
        self.assertRegex(text_of(result), r"never-saved")
        self.assertFalse(any(req["cmd"] == "load_state" for req in self.box.requests))
        self.assertEqual(len(self.box.requests), before)


if __name__ == "__main__":
    unittest.main()
