"""Spawn and stop the local MAME coco3 process."""

from __future__ import annotations

import os
import subprocess
import threading
from pathlib import Path
from typing import Any, Callable, Protocol

from coco3_mcp.config import AppConfig, write_bridge_port_file


def build_mame_args(config: AppConfig) -> list[str]:
    return [
        "coco3",
        "-window",
        "-skip_gameinfo",
        "-natural",
        # CoCo 3 has a mouse port; without these MAME captures the host cursor.
        "-nomouse",
        "-mouse_device",
        "none",
        "-ext",
        "fdc",
        "-ramsize",
        config.coco_ram,
        "-rompath",
        config.mame_rom_path,
        "-autoboot_script",
        str(config.bridge_lua_path),
        "-autoboot_delay",
        "0",
        "-snapshot_directory",
        str(config.snapshot_dir),
        "-state_directory",
        str(config.state_dir),
    ]


class Spawned(Protocol):
    pid: int | None
    killed: bool
    exit_code: int | None

    def kill(self, signal: str | None = None) -> bool: ...
    def on(self, event: str, listener: Callable[[int | None], None]) -> None: ...


Spawner = Callable[[str, list[str], dict[str, Any]], Spawned]


class _PopenChild:
    def __init__(self, process: subprocess.Popen[bytes]) -> None:
        self._process = process
        self.killed = False
        self._listeners: list[Callable[[int | None], None]] = []
        self._settled = False
        self._lock = threading.Lock()
        threading.Thread(target=self._wait, daemon=True).start()

    @property
    def pid(self) -> int | None:
        return self._process.pid

    @property
    def exit_code(self) -> int | None:
        return self._process.poll()

    def kill(self, signal: str | None = None) -> bool:
        try:
            self._process.terminate() if signal == "SIGTERM" else self._process.kill()
            self.killed = True
            return True
        except OSError:
            return False

    def on(self, event: str, listener: Callable[[int | None], None]) -> None:
        if event == "exit":
            self._listeners.append(listener)

    def _wait(self) -> None:
        code = self._process.wait()
        self._settle(code)

    def _settle(self, code: int | None) -> None:
        with self._lock:
            if self._settled:
                return
            self._settled = True
            listeners = list(self._listeners)
        for listener in listeners:
            listener(code)


def _default_spawn(command: str, args: list[str], options: dict[str, Any]) -> Spawned:
    stdio = options.get("stdio")
    stdin = subprocess.DEVNULL
    stdout = subprocess.DEVNULL
    stderr = subprocess.DEVNULL
    if isinstance(stdio, (list, tuple)) and len(stdio) >= 3:
        if stdio[0] == "ignore":
            stdin = subprocess.DEVNULL
        if isinstance(stdio[1], int):
            stdout = stdio[1]
        if isinstance(stdio[2], int):
            stderr = stdio[2]
    creationflags = 0
    if options.get("windows_hide") and os.name == "nt":
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    process = subprocess.Popen(
        [command, *args],
        cwd=options.get("cwd"),
        env=options.get("env"),
        stdin=stdin,
        stdout=stdout,
        stderr=stderr,
        creationflags=creationflags,
    )
    return _PopenChild(process)


class MameController:
    def __init__(
        self,
        config: AppConfig,
        spawner: Spawner = _default_spawn,
        platform: str | None = None,
    ) -> None:
        self._config = config
        self._spawner = spawner
        self._platform = platform if platform is not None else ("win32" if os.name == "nt" else "linux")
        self._child: Spawned | None = None
        self._log_fd: int | None = None
        self._last_exit: int | None = None
        self._intentional = False
        self._listeners: list[Callable[[int | None], None]] = []

    def build_args(self) -> list[str]:
        return build_mame_args(self._config)

    def start(self) -> dict[str, Any]:
        if not self._config.mame_path:
            raise RuntimeError("MAME_PATH is not set")
        if not self._config.mame_rom_path:
            raise RuntimeError("MAME_ROMPATH is not set")
        if self._child is not None:
            return {
                "started": False,
                "alreadyRunning": True,
                "pid": self._child.pid,
            }
        self._intentional = False
        write_bridge_port_file(self._config)
        self._config.log_dir.mkdir(parents=True, exist_ok=True)
        log_path = self._config.log_dir / "mame.log"
        fd = os.open(str(log_path), os.O_WRONLY | os.O_CREAT | os.O_APPEND)
        self._log_fd = fd
        env = {**os.environ, "BRIDGE_PORT": str(self._config.bridge_port)}
        spawned = self._spawner(
            self._config.mame_path,
            build_mame_args(self._config),
            {
                "cwd": str(Path(self._config.mame_path).parent),
                "env": env,
                "stdio": ["ignore", fd, fd],
                "windows_hide": True,
            },
        )
        self._child = spawned
        self._last_exit = None

        def on_exit(code: int | None) -> None:
            self._last_exit = code
            if self._child is spawned:
                self._child = None
            self._close_log()
            if not self._intentional:
                for listener in list(self._listeners):
                    listener(code)

        spawned.on("exit", on_exit)
        return {"started": True, "alreadyRunning": False, "pid": spawned.pid}

    def stop(self) -> None:
        if self._child is None:
            return
        self._intentional = True
        current = self._child
        pid = current.pid
        if self._platform == "win32" and pid is not None:
            done = threading.Event()

            def on_kill_exit(_code: int | None) -> None:
                done.set()

            killer = self._spawner(
                "taskkill",
                ["/PID", str(pid), "/T", "/F"],
                {"windows_hide": True},
            )
            killer.on("exit", on_kill_exit)
            done.wait(timeout=30)
        else:
            current.kill("SIGTERM")
        if self._child is current:
            self._child = None
        self._close_log()

    def status(self) -> dict[str, Any]:
        return {
            "running": self._child is not None,
            "pid": self._child.pid if self._child is not None else None,
            "exitCode": None if self._child is not None else self._last_exit,
        }

    def on_unexpected_exit(self, cb: Callable[[int | None], None]) -> None:
        self._listeners.append(cb)

    def _close_log(self) -> None:
        if self._log_fd is None:
            return
        try:
            os.close(self._log_fd)
        except OSError:
            pass
        self._log_fd = None


def create_mame_controller(
    config: AppConfig,
    spawner: Spawner = _default_spawn,
    platform: str | None = None,
) -> MameController:
    return MameController(config, spawner, platform)
