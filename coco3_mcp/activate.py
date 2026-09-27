"""Find local tools, publish the HTTP endpoint, and start the server.

Run: python -m coco3_mcp.activate
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Callable, Mapping

from coco3_mcp.client import probe as probe_server
from coco3_mcp.endpoint import (
    DEFAULT_HOST,
    DEFAULT_PORT,
    endpoint_document,
    endpoint_url,
)

MAME_NAMES = ("mame.exe", "mame64.exe", "mame")
DECB_NAMES = ("decb.exe", "decb")


def app_root() -> Path:
    return Path(__file__).resolve().parent.parent


def sibling_search_roots(root: Path) -> list[Path]:
    sibling = root.parent / "CoCo3_MCP_Server"
    if sibling.is_dir():
        return [sibling.resolve()]
    return []


def _first_file(folders: list[Path], names: tuple[str, ...]) -> Path | None:
    for folder in folders:
        for name in names:
            candidate = folder / name
            if candidate.is_file():
                return candidate.resolve()
    return None


def _mame_folders(roots: list[Path]) -> list[Path]:
    folders: list[Path] = []
    for base in roots:
        folders.append(base / "mame")
        folders.append(base / "MCP" / "mame")
    return folders


def _decb_folders(roots: list[Path]) -> list[Path]:
    folders: list[Path] = []
    for base in roots:
        folders.append(base / "decb")
        folders.append(base / "toolshed")
        folders.append(base / "MCP" / "toolshed")
    return folders


def _which(names: tuple[str, ...]) -> Path | None:
    for name in names:
        found = shutil.which(name)
        if found:
            return Path(found).resolve()
    return None


def discover_tools(root: Path, extra_roots: list[Path] | None = None) -> dict[str, str]:
    roots = [root.resolve(), *[path.resolve() for path in (extra_roots or [])]]
    mame = _first_file(_mame_folders(roots), MAME_NAMES) or _which(MAME_NAMES)
    rom = ""
    if mame is not None:
        beside = mame.parent / "roms"
        if beside.is_dir():
            rom = str(beside.resolve())
    if not rom:
        for base in roots:
            for folder in (base / "mame" / "roms", base / "MCP" / "mame" / "roms"):
                if folder.is_dir():
                    rom = str(folder.resolve())
                    break
            if rom:
                break
    decb = _first_file(_decb_folders(roots), DECB_NAMES) or _which(DECB_NAMES)
    return {
        "mame_path": str(mame) if mame else "",
        "mame_rom_path": rom,
        "decb_path": str(decb) if decb else "",
    }


def _env_value(root: Path, target: str, placeholder: str) -> str:
    if not target:
        return placeholder
    path = Path(target).resolve()
    try:
        relative = path.relative_to(root.resolve())
    except ValueError:
        return str(path)
    return str(relative)


def render_env(root: Path, discovered: Mapping[str, str]) -> str:
    lines = [
        "# Written by python -m coco3_mcp.activate",
        f"MAME_PATH={_env_value(root, discovered.get('mame_path', ''), r'mame\mame.exe')}",
        f"MAME_ROMPATH={_env_value(root, discovered.get('mame_rom_path', ''), r'mame\roms')}",
        f"DECB_PATH={_env_value(root, discovered.get('decb_path', ''), r'decb\decb.exe')}",
        "BRIDGE_PORT=18765",
        "COCO_RAM=512K",
        f"MCP_HOST={DEFAULT_HOST}",
        f"MCP_PORT={DEFAULT_PORT}",
        "",
    ]
    return "\n".join(lines)


def merge_cursor_config(existing: dict | None, *, python: str, cwd: str) -> dict:
    data = dict(existing) if isinstance(existing, dict) else {}
    servers = data.get("mcpServers")
    if not isinstance(servers, dict):
        servers = {}
    else:
        servers = dict(servers)
    servers["coco3"] = {
        "command": python,
        "args": ["-m", "coco3_mcp"],
        "cwd": cwd,
    }
    data["mcpServers"] = servers
    return data


def _read_json(path: Path) -> dict | None:
    try:
        loaded = json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError:
        backup = path.with_name(path.name + ".bak")
        backup.write_bytes(path.read_bytes())
        return None
    if not isinstance(loaded, dict):
        return None
    return loaded


def _write_mcp(path: Path, python: str, cwd: str) -> None:
    existing = _read_json(path) if path.is_file() else None
    merged = merge_cursor_config(existing, python=python, cwd=cwd)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(merged, indent=2) + "\n", encoding="utf-8")


def ensure_storage(root: Path) -> None:
    for relative in (
        "storage/disks",
        "storage/host/bas",
        "storage/host/bin",
        "storage/host/data",
        "mame/roms",
        "logs",
        "snapshots",
        "states",
        "work",
    ):
        (root / relative).mkdir(parents=True, exist_ok=True)


def _write_endpoint(path: Path, document: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")


def activate(
    root: Path,
    *,
    python: str,
    user_mcp: Path | None,
    project_mcp: Path | None,
    extra_roots: list[Path] | None = None,
    public_endpoint: Path | None = None,
) -> dict[str, str]:
    root = root.resolve()
    discovered = discover_tools(root, extra_roots)
    env_path = root / ".env"
    if env_path.is_file():
        (root / ".env.bak").write_text(env_path.read_text(encoding="utf-8"), encoding="utf-8")
    env_path.write_text(render_env(root, discovered), encoding="utf-8")
    ensure_storage(root)
    cwd = str(root)
    document = endpoint_document(
        root=root,
        python=python,
        host=DEFAULT_HOST,
        port=DEFAULT_PORT,
    )
    _write_endpoint(root / "server.json", document)
    if public_endpoint is not None:
        _write_endpoint(public_endpoint, document)
    written: list[str] = []
    for path in (user_mcp, project_mcp):
        if path is None:
            continue
        _write_mcp(path, python, cwd)
        written.append(str(path))
    return {
        "env": str(env_path),
        "url": document["url"],
        "mcp": ",".join(written),
        **discovered,
    }


def ensure_listening(
    host: str,
    port: int,
    spawn: Callable[[], None],
    *,
    probe: Callable[[str, int], bool] | None = None,
    timeout_s: float = 5.0,
) -> str:
    check = probe if probe is not None else probe_server
    if check(host, port):
        return "already"
    spawn()
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if check(host, port):
            return "started"
        time.sleep(0.05)
    return "failed"


def spawn_listener(python: str, cwd: Path) -> None:
    log_path = cwd / "logs" / "serve.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_handle = open(log_path, "ab")
    kwargs: dict = {
        "cwd": str(cwd),
        "stdin": subprocess.DEVNULL,
        "stdout": log_handle,
        "stderr": log_handle,
    }
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | getattr(
            subprocess, "CREATE_NO_WINDOW", 0
        )
    else:
        kwargs["start_new_session"] = True
    try:
        subprocess.Popen([python, "-m", "coco3_mcp.serve"], **kwargs)
    finally:
        log_handle.close()


def main() -> int:
    root = app_root()
    python = sys.executable
    result = activate(
        root,
        python=python,
        user_mcp=Path.home() / ".cursor" / "mcp.json",
        project_mcp=root / ".cursor" / "mcp.json",
        extra_roots=sibling_search_roots(root),
        public_endpoint=Path.home() / ".coco3-mcp" / "server.json",
    )
    status = ensure_listening(
        DEFAULT_HOST,
        DEFAULT_PORT,
        lambda: spawn_listener(python, root),
    )
    print("CoCo 3 MCP is installed and activated.", file=sys.stderr)
    print(f"  app:    {root}", file=sys.stderr)
    print(f"  python: {python}", file=sys.stderr)
    print(f"  env:    {result['env']}", file=sys.stderr)
    print(f"  url:    {endpoint_url(DEFAULT_HOST, DEFAULT_PORT)}", file=sys.stderr)
    if status == "failed":
        print("  server: not listening — run coco3-mcp.cmd", file=sys.stderr)
        return 1
    print(f"  server: {status}", file=sys.stderr)
    if result["mame_path"]:
        print(f"  mame:   {result['mame_path']}", file=sys.stderr)
    else:
        print("  mame:   not found — put mame.exe in mame\\ and run install.cmd again", file=sys.stderr)
    if result["mame_rom_path"]:
        print(f"  roms:   {result['mame_rom_path']}", file=sys.stderr)
    else:
        print("  roms:   not found — put coco3.zip in mame\\roms", file=sys.stderr)
    if result["decb_path"]:
        print(f"  decb:   {result['decb_path']}", file=sys.stderr)
    else:
        print("  decb:   not found — only needed for coco_build_disk", file=sys.stderr)
    print("Any program can POST JSON-RPC to the url above. No IDE required.", file=sys.stderr)
    print("Then call coco_start. Do not start MAME yourself.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
