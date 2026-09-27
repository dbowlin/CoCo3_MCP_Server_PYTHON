"""Application configuration and .env loading."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


@dataclass(frozen=True)
class AppConfig:
    mame_path: str
    mame_rom_path: str
    decb_path: str
    bridge_port: int
    coco_ram: str
    root_dir: Path
    bridge_lua_path: Path
    bridge_port_file: Path
    snapshot_dir: Path
    state_dir: Path
    work_dir: Path
    log_dir: Path
    storage_dir: Path
    disks_dir: Path
    host_bas_dir: Path
    host_bin_dir: Path
    host_data_dir: Path


def _parse_port(raw: str | None) -> int:
    if raw is None or raw.strip() == "":
        return 18765
    text = raw.strip()
    if not re.fullmatch(r"\d+", text):
        raise ValueError(f"invalid BRIDGE_PORT: {raw}")
    port = int(text)
    if port < 1 or port > 65535:
        raise ValueError(f"invalid BRIDGE_PORT: {raw}")
    return port


def _resolve_tool_path(raw: str, root: Path) -> str:
    text = raw.strip()
    if not text:
        return ""
    path = Path(text)
    if path.is_absolute():
        return str(path)
    if "/" not in text and "\\" not in text and not text.startswith("."):
        return text
    return str((root / text).resolve())


def load_config(env: Mapping[str, str | None], root_dir: str | Path) -> AppConfig:
    root = Path(root_dir).resolve()
    bridge_lua_path = root / "scripts" / "bridge.lua"
    storage_dir = root / "storage"
    return AppConfig(
        mame_path=_resolve_tool_path(env.get("MAME_PATH") or "", root),
        mame_rom_path=_resolve_tool_path(env.get("MAME_ROMPATH") or "", root),
        decb_path=_resolve_tool_path(env.get("DECB_PATH") or "decb", root),
        bridge_port=_parse_port(env.get("BRIDGE_PORT")),
        coco_ram=env.get("COCO_RAM") or "512K",
        root_dir=root,
        bridge_lua_path=bridge_lua_path,
        bridge_port_file=bridge_lua_path.parent / "bridge.port",
        snapshot_dir=root / "snapshots",
        state_dir=root / "states",
        work_dir=root / "work",
        log_dir=root / "logs",
        storage_dir=storage_dir,
        disks_dir=storage_dir / "disks",
        host_bas_dir=storage_dir / "host" / "bas",
        host_bin_dir=storage_dir / "host" / "bin",
        host_data_dir=storage_dir / "host" / "data",
    )


def write_bridge_port_file(config: AppConfig) -> None:
    config.bridge_port_file.parent.mkdir(parents=True, exist_ok=True)
    config.bridge_port_file.write_text(f"{config.bridge_port}\n", encoding="utf-8")


def load_dotenv(file_path: str | Path) -> dict[str, str]:
    path = Path(file_path)
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    env: dict[str, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if line == "" or line.startswith("#"):
            continue
        eq = line.find("=")
        if eq <= 0:
            continue
        key = line[:eq].strip()
        value = line[eq + 1 :].strip()
        quoted = (
            (value.startswith('"') and value.endswith('"') and len(value) >= 2)
            or (value.startswith("'") and value.endswith("'") and len(value) >= 2)
        )
        if quoted:
            value = value[1:-1]
        env[key] = value
    return env
