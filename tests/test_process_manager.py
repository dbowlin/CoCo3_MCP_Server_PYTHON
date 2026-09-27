"""Section 2 — MAME process controller."""

from __future__ import annotations

import tempfile
import threading
import unittest
from pathlib import Path
from typing import Any, Callable

from coco3_mcp.config import load_config
from coco3_mcp.mame_process import build_mame_args, create_mame_controller


class FakeChild:
    def __init__(self, pid: int) -> None:
        self.pid = pid
        self.killed = False
        self.exit_code: int | None = None
        self.signal: str | None = None
        self._listeners: list[Callable[[int | None], None]] = []

    def kill(self, signal: str | None = None) -> bool:
        self.killed = True
        self.signal = signal
        return True

    def on(self, event: str, listener: Callable[[int | None], None]) -> None:
        if event == "exit":
            self._listeners.append(listener)

    def emit_exit(self, code: int | None) -> None:
        self.exit_code = code
        for listener in list(self._listeners):
            listener(code)


class ProcessManagerTests(unittest.TestCase):
    def test_windows_spawns_once_logs_and_taskkills(self) -> None:
        with tempfile.TemporaryDirectory(prefix="coco-mame-") as tmp:
            root = Path(tmp)
            mame_path = root / "mame" / "mame.exe"
            cfg = load_config(
                {
                    "MAME_PATH": str(mame_path),
                    "MAME_ROMPATH": str(root / "roms"),
                    "BRIDGE_PORT": "18765",
                },
                root,
            )
            calls: list[dict[str, Any]] = []
            child: FakeChild | None = None

            def spawn(command: str, args: list[str], options: dict[str, Any]) -> FakeChild:
                nonlocal child
                calls.append({"command": command, "args": args, "options": options})
                if command == "taskkill":
                    killer = FakeChild(0)
                    threading.Timer(0, lambda: killer.emit_exit(0)).start()
                    return killer
                child = FakeChild(4242)
                return child

            mame = create_mame_controller(cfg, spawn, platform="win32")
            unexpected: list[int | None] = []
            mame.on_unexpected_exit(lambda code: unexpected.append(code))

            self.assertEqual(mame.start(), {"started": True, "alreadyRunning": False, "pid": 4242})
            self.assertEqual(mame.status(), {"running": True, "pid": 4242, "exitCode": None})
            self.assertEqual(calls[0]["command"], str(mame_path))
            self.assertEqual(calls[0]["args"], build_mame_args(cfg))
            self.assertEqual(calls[0]["options"]["cwd"], str(mame_path.parent))
            self.assertEqual(calls[0]["options"]["env"]["BRIDGE_PORT"], "18765")
            self.assertTrue(calls[0]["options"]["windows_hide"])
            self.assertEqual(calls[0]["options"]["stdio"][0], "ignore")
            self.assertIsInstance(calls[0]["options"]["stdio"][1], int)
            self.assertIsInstance(calls[0]["options"]["stdio"][2], int)
            self.assertTrue((root / "logs" / "mame.log").exists())

            self.assertEqual(mame.start(), {"started": False, "alreadyRunning": True, "pid": 4242})
            self.assertEqual(sum(1 for call in calls if call["command"] == str(mame_path)), 1)

            assert child is not None
            child.emit_exit(1)
            self.assertEqual(mame.status(), {"running": False, "pid": None, "exitCode": 1})
            self.assertEqual(unexpected, [1])

            self.assertTrue(mame.start()["started"])
            before_stop = len(calls)
            mame.stop()
            kill = next(call for call in calls if call["command"] == "taskkill")
            self.assertEqual(kill["args"], ["/PID", "4242", "/T", "/F"])
            self.assertFalse(mame.status()["running"])
            child.emit_exit(0)
            self.assertEqual(unexpected, [1])
            mame.stop()
            self.assertEqual(len(calls), before_stop + 1)

    def test_posix_stop_sends_sigterm(self) -> None:
        with tempfile.TemporaryDirectory(prefix="coco-mame-posix-") as tmp:
            root = Path(tmp)
            cfg = load_config(
                {"MAME_PATH": str(root / "mame"), "MAME_ROMPATH": str(root / "roms")},
                root,
            )
            child: FakeChild | None = None
            calls: list[str] = []

            def spawn(command: str, args: list[str], options: dict[str, Any]) -> FakeChild:
                nonlocal child
                calls.append(command)
                child = FakeChild(7)
                return child

            mame = create_mame_controller(cfg, spawn, platform="linux")
            mame.start()
            mame.stop()
            self.assertEqual(child.signal if child else None, "SIGTERM")
            self.assertNotIn("taskkill", calls)
            self.assertFalse(mame.status()["running"])

    def test_start_throws_when_mame_path_empty(self) -> None:
        mame = create_mame_controller(
            load_config({}, Path("empty-mame").resolve()),
            lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("spawned")),
            platform="win32",
        )
        with self.assertRaisesRegex(RuntimeError, "MAME_PATH"):
            mame.start()


if __name__ == "__main__":
    unittest.main()
