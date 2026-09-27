"""MCP tool handlers for CoCo 3 / MAME control."""

from __future__ import annotations

import base64
import json
import re
import time
from pathlib import Path
from typing import Any, Callable, Mapping, MutableMapping, Protocol

from coco3_mcp.config import AppConfig

PING_TIMEOUT_MS = 15_000
SNAPSHOT_TIMEOUT_MS = 5_000
STATE_TIMEOUT_MS = 2_000

TOOL_INFO: dict[str, dict[str, str]] = {
    "coco_start": {
        "description": (
            "Spawn local official MAME coco3 with the disk controller and wait until the Lua bridge answers ping."
        ),
    },
    "coco_stop": {
        "description": "Stop the MAME process tree and close the bridge listener.",
    },
    "coco_status": {
        "description": "Report whether MAME is running, whether the bridge answered, and the mounted flop1 image.",
    },
    "coco_mount_flop": {
        "description": (
            "Mount a disk image on flop1 or flop2. Prefer paths like storage/disks/game.dsk "
            "(resolved from the MCP root). Drives come from manager.machine.images."
        ),
    },
    "coco_unmount_flop": {
        "description": "Unload the disk image from flop1 or flop2.",
    },
    "coco_type": {
        "description": (
            "Post one natural-keyboard string. pressEnter defaults to true and appends {ENTER} "
            "when it is not already present, then waits until the queue is empty and not posting."
        ),
    },
    "coco_snapshot": {
        "description": (
            "Capture the CoCo screen to snapshots/current.png and return the PNG. "
            "Falls back to the newest PNG in the snapshot directory."
        ),
    },
    "coco_soft_reset": {
        "description": "Soft-reset the emulated CoCo. This does not hard-reset MAME.",
    },
    "coco_list_images": {
        "description": (
            "List MAME image devices, including flop1 and flop2, with tag, briefname, filename, and exists."
        ),
    },
    "coco_build_disk": {
        "description": (
            "Build a 35-track Disk BASIC image with ToolShed decb. Prefer storage/disks for output "
            "and storage/host/bas|bin|data for inputs. BASIC is tokenized; BIN and data are copied unchanged."
        ),
    },
    "coco_read_memory": {
        "description": (
            "Read bytes from the current 64K MMU window, not physical RAM. "
            "$0400 is the 32-column text screen only in the CoCo 1/2-compatible map."
        ),
    },
    "coco_write_memory": {
        "description": "Write bytes into the current 64K MMU window, not physical RAM.",
    },
    "coco_save_state": {
        "description": (
            "Schedule a MAME save into the state directory. The save is asynchronous; "
            "fileFound reports whether the file appeared."
        ),
    },
    "coco_load_state": {
        "description": (
            "Schedule a MAME state load. Fails immediately if no matching file exists in the state "
            "directory; otherwise the load is asynchronous and the result is reported as scheduled."
        ),
    },
}


class ToolServer(Protocol):
    def register_tool(
        self,
        name: str,
        description: str,
        input_schema: dict[str, Any],
        handler: Callable[[dict[str, Any]], dict[str, Any]],
    ) -> None: ...


def text_result(text: str, is_error: bool = False) -> dict[str, Any]:
    result: dict[str, Any] = {"content": [{"type": "text", "text": text}]}
    if is_error:
        result["isError"] = True
    return result


def _message_of(error: BaseException) -> str:
    return str(error)


def _normalize_address(input_value: Any) -> str:
    text = str(input_value or "").strip().lower()
    if text.startswith("0x"):
        text = text[2:]
    if not re.fullmatch(r"[0-9a-f]+", text):
        raise ValueError(f"bad address {input_value}")
    value = int(text, 16)
    if value < 0 or value > 0xFFFF:
        raise ValueError(f"bad address {input_value}")
    return f"{value:04X}"


def _address_value(hex_addr: str) -> int:
    return int(hex_addr, 16)


def _normalize_length(input_value: Any, address: int) -> int:
    try:
        if isinstance(input_value, bool):
            raise ValueError("bool")
        if isinstance(input_value, int):
            length = input_value
        else:
            as_num = float(input_value)
            if not as_num.is_integer():
                raise ValueError("non-int")
            length = int(as_num)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"bad length {input_value}") from exc
    if length < 1 or length > 65536:
        raise ValueError(f"bad length {input_value}")
    if address + length - 1 > 0xFFFF:
        raise ValueError(f"bad length {input_value}")
    return length


def _valid_state_name(name: Any) -> bool:
    return isinstance(name, str) and len(name) > 0 and "/" not in name and "\\" not in name


def _drive_of(args: Mapping[str, Any]) -> str:
    drive = args.get("drive") if isinstance(args.get("drive"), str) else "flop1"
    if drive not in ("flop1", "flop2"):
        raise ValueError("drive must be flop1 or flop2")
    return drive


def _resolve_disk_path(config: AppConfig, raw: str) -> str:
    text = raw.strip()
    path = Path(text)
    if path.is_absolute():
        return str(path)
    norm = text.replace("\\", "/")
    if norm == "storage" or norm.startswith("storage/"):
        return str((config.root_dir / text).resolve())
    return str(path.resolve())


def _poll_ping(bridge: Any, timeout_ms: int) -> str | None:
    deadline = time.time() + timeout_ms / 1000.0
    last = "ping timeout"
    while time.time() < deadline:
        remaining_ms = max(1, int((deadline - time.time()) * 1000))
        try:
            response = bridge.request("ping", {}, min(1000, remaining_ms))
            if response.get("ok"):
                return None
            last = str(response.get("error") or last)
        except Exception as exc:  # noqa: BLE001 — surface last bridge error
            last = _message_of(exc)
        if time.time() >= deadline:
            break
        time.sleep(0.05)
    return last


def _wait_for_file(file: Path, timeout_ms: int) -> bool:
    deadline = time.time() + timeout_ms / 1000.0
    while time.time() <= deadline:
        try:
            if file.is_file() and file.stat().st_size > 0:
                return True
        except OSError:
            pass
        if time.time() > deadline:
            break
        time.sleep(0.05)
    return False


def _newest_png(directory: Path, started: float) -> Path | None:
    try:
        names = list(directory.iterdir())
    except OSError:
        return None
    best: tuple[Path, float] | None = None
    for entry in names:
        if not entry.name.lower().endswith(".png"):
            continue
        try:
            info = entry.stat()
            if info.st_size <= 0 or info.st_mtime < started - 1.0:
                continue
            if best is None or info.st_mtime >= best[1]:
                best = (entry, info.st_mtime)
        except OSError:
            continue
    return best[0] if best else None


def _wait_for_newest_png(directory: Path, started: float, timeout_ms: int) -> Path | None:
    deadline = time.time() + timeout_ms / 1000.0
    while time.time() <= deadline:
        found = _newest_png(directory, started)
        if found is not None:
            return found
        if time.time() > deadline:
            break
        time.sleep(0.05)
    return None


def _find_state_file(directory: Path, name: str, timeout_ms: int) -> Path | None:
    deadline = time.time() + timeout_ms / 1000.0
    while time.time() <= deadline:
        try:
            for entry in directory.iterdir():
                if entry.name == name or entry.name.startswith(f"{name}."):
                    return entry
        except OSError:
            pass
        if time.time() > deadline:
            break
        time.sleep(0.05)
    return None


def _handlers() -> dict[str, Callable[[MutableMapping[str, Any], Mapping[str, Any]], dict[str, Any]]]:
    def coco_start(deps: MutableMapping[str, Any], _args: Mapping[str, Any]) -> dict[str, Any]:
        running = deps["mame"].status()
        if running["running"]:
            error = _poll_ping(deps["bridge"], PING_TIMEOUT_MS)
            if error:
                return text_result(error, True)
            return text_result(
                json.dumps(
                    {
                        "ok": True,
                        "alreadyRunning": True,
                        "pid": running["pid"],
                        "bridge": True,
                    }
                )
            )
        try:
            deps["bridge"].start()
            started = deps["mame"].start()
            error = _poll_ping(deps["bridge"], PING_TIMEOUT_MS)
            if error:
                deps["mame"].stop()
                deps["bridge"].stop()
                return text_result(error, True)
            deps["logger"].log(f"coco_start pid {started.get('pid', 'unknown')}")
            return text_result(
                json.dumps(
                    {
                        "ok": True,
                        "alreadyRunning": False,
                        "pid": started.get("pid"),
                        "bridge": True,
                    }
                )
            )
        except Exception as exc:  # noqa: BLE001
            try:
                deps["mame"].stop()
            except Exception:  # noqa: BLE001
                pass
            try:
                deps["bridge"].stop()
            except Exception:  # noqa: BLE001
                pass
            return text_result(_message_of(exc), True)

    def coco_stop(deps: MutableMapping[str, Any], _args: Mapping[str, Any]) -> dict[str, Any]:
        deps["mame"].stop()
        deps["bridge"].stop()
        deps["logger"].log("coco_stop")
        return text_result(json.dumps({"ok": True}))

    def coco_status(deps: MutableMapping[str, Any], _args: Mapping[str, Any]) -> dict[str, Any]:
        status = deps["mame"].status()
        body: dict[str, Any] = {
            "running": status["running"],
            "pid": status["pid"],
            "bridge": False,
        }
        if not status["running"]:
            return text_result(json.dumps(body))
        try:
            ping = deps["bridge"].request("ping", {}, 500)
            if not ping.get("ok"):
                return text_result(json.dumps(body))
            details = deps["bridge"].request("status", {}, 500)
            if details.get("ok") and isinstance(details.get("result"), dict):
                record = details["result"]
                return text_result(
                    json.dumps(
                        {
                            "running": True,
                            "pid": status["pid"],
                            "bridge": True,
                            "driver": record.get("driver"),
                            "flop1": record.get("flop1"),
                            "posting": record.get("posting"),
                            "empty": record.get("empty"),
                        }
                    )
                )
            body["bridge"] = True
        except Exception:  # noqa: BLE001
            body["bridge"] = False
        return text_result(json.dumps(body))

    def coco_mount_flop(deps: MutableMapping[str, Any], args: Mapping[str, Any]) -> dict[str, Any]:
        try:
            raw_path = str(args.get("path") or "").strip()
            if not raw_path:
                raise ValueError("path is required")
            drive = _drive_of(args)
            response = deps["bridge"].request(
                "mount",
                {"briefname": drive, "path": _resolve_disk_path(deps["config"], raw_path)},
            )
            if not response.get("ok"):
                return text_result(str(response.get("error")), True)
            return text_result(json.dumps(response.get("result")))
        except Exception as exc:  # noqa: BLE001
            return text_result(_message_of(exc), True)

    def coco_unmount_flop(deps: MutableMapping[str, Any], args: Mapping[str, Any]) -> dict[str, Any]:
        try:
            drive = _drive_of(args)
            response = deps["bridge"].request("unmount", {"briefname": drive})
            if not response.get("ok"):
                return text_result(str(response.get("error")), True)
            return text_result(json.dumps(response.get("result")))
        except Exception as exc:  # noqa: BLE001
            return text_result(_message_of(exc), True)

    def coco_type(deps: MutableMapping[str, Any], args: Mapping[str, Any]) -> dict[str, Any]:
        try:
            press_enter = args.get("pressEnter") is not False
            text = str(args.get("text") or "")
            if press_enter and not text.endswith("{ENTER}"):
                text += "{ENTER}"
            queued = deps["bridge"].request("type", {"text": text})
            if not queued.get("ok"):
                return text_result(str(queued.get("error")), True)
            deadline = time.time() + PING_TIMEOUT_MS / 1000.0
            while time.time() < deadline:
                idle = deps["bridge"].request("wait_idle", {}, 1000)
                if not idle.get("ok"):
                    return text_result(str(idle.get("error")), True)
                result = idle.get("result") or {}
                if isinstance(result, dict) and result.get("idle") is True:
                    return text_result(json.dumps({"queued": True, "text": text}))
                time.sleep(0.05)
            return text_result("timed out waiting for keyboard idle", True)
        except Exception as exc:  # noqa: BLE001
            return text_result(_message_of(exc), True)

    def coco_snapshot(deps: MutableMapping[str, Any], _args: Mapping[str, Any]) -> dict[str, Any]:
        try:
            target = deps["config"].snapshot_dir / "current.png"
            started = time.time()
            deps["config"].snapshot_dir.mkdir(parents=True, exist_ok=True)
            if target.exists():
                target.unlink()
            response = deps["bridge"].request(
                "snapshot",
                {
                    "path": str(target),
                    "snapshotDirectory": str(deps["config"].snapshot_dir),
                },
                SNAPSHOT_TIMEOUT_MS,
            )
            if not response.get("ok"):
                return text_result(str(response.get("error")), True)
            result = response.get("result") or {}
            method = result.get("method") if isinstance(result, dict) else None
            if method == "video":
                file = _wait_for_newest_png(
                    deps["config"].snapshot_dir, started, SNAPSHOT_TIMEOUT_MS
                )
            else:
                result_path = (
                    Path(str(result["path"]))
                    if isinstance(result, dict) and isinstance(result.get("path"), str)
                    else target
                )
                file = result_path if _wait_for_file(result_path, SNAPSHOT_TIMEOUT_MS) else None
            if file is None:
                return text_result("snapshot file missing", True)
            bytes_data = Path(file).read_bytes()
            if len(bytes_data) == 0:
                return text_result("snapshot file missing", True)
            return {
                "content": [
                    {
                        "type": "image",
                        "data": base64.b64encode(bytes_data).decode("ascii"),
                        "mimeType": "image/png",
                    },
                    {"type": "text", "text": str(file)},
                ]
            }
        except Exception as exc:  # noqa: BLE001
            return text_result(_message_of(exc), True)

    def coco_soft_reset(deps: MutableMapping[str, Any], _args: Mapping[str, Any]) -> dict[str, Any]:
        try:
            response = deps["bridge"].request("soft_reset", {})
            if not response.get("ok"):
                return text_result(str(response.get("error")), True)
            return text_result(json.dumps(response.get("result")))
        except Exception as exc:  # noqa: BLE001
            return text_result(_message_of(exc), True)

    def coco_list_images(deps: MutableMapping[str, Any], _args: Mapping[str, Any]) -> dict[str, Any]:
        try:
            response = deps["bridge"].request("list_images", {})
            if not response.get("ok"):
                return text_result(str(response.get("error")), True)
            return text_result(json.dumps(response.get("result")))
        except Exception as exc:  # noqa: BLE001
            return text_result(_message_of(exc), True)

    def coco_build_disk(deps: MutableMapping[str, Any], args: Mapping[str, Any]) -> dict[str, Any]:
        request = {
            "dskPath": str(args.get("dskPath") or ""),
            "files": args.get("files") if isinstance(args.get("files"), list) else [],
        }
        try:
            result = deps["toolchain"].build_disk(request)
            return text_result(json.dumps(result))
        except Exception as exc:  # noqa: BLE001
            return text_result(_message_of(exc), True)

    def coco_read_memory(deps: MutableMapping[str, Any], args: Mapping[str, Any]) -> dict[str, Any]:
        try:
            address = _normalize_address(args.get("address"))
            length = _normalize_length(args.get("length"), _address_value(address))
            response = deps["bridge"].request("read_mem", {"address": address, "length": length})
            if not response.get("ok"):
                return text_result(str(response.get("error")), True)
            return text_result(json.dumps(response.get("result")))
        except Exception as exc:  # noqa: BLE001
            return text_result(_message_of(exc), True)

    def coco_write_memory(deps: MutableMapping[str, Any], args: Mapping[str, Any]) -> dict[str, Any]:
        try:
            address = _normalize_address(args.get("address"))
            data = str(args.get("data") or "")
            response = deps["bridge"].request("write_mem", {"address": address, "data": data})
            if not response.get("ok"):
                return text_result(str(response.get("error")), True)
            return text_result(json.dumps(response.get("result")))
        except Exception as exc:  # noqa: BLE001
            return text_result(_message_of(exc), True)

    def coco_save_state(deps: MutableMapping[str, Any], args: Mapping[str, Any]) -> dict[str, Any]:
        try:
            if not _valid_state_name(args.get("name")):
                return text_result("invalid state name", True)
            name = str(args["name"])
            response = deps["bridge"].request("save_state", {"name": name})
            if not response.get("ok"):
                return text_result(str(response.get("error")), True)
            deps["config"].state_dir.mkdir(parents=True, exist_ok=True)
            file = _find_state_file(deps["config"].state_dir, name, STATE_TIMEOUT_MS)
            return text_result(
                json.dumps(
                    {
                        "scheduled": True,
                        "name": name,
                        "fileFound": file is not None,
                        "file": str(file) if file is not None else None,
                    }
                )
            )
        except Exception as exc:  # noqa: BLE001
            return text_result(_message_of(exc), True)

    def coco_load_state(deps: MutableMapping[str, Any], args: Mapping[str, Any]) -> dict[str, Any]:
        try:
            if not _valid_state_name(args.get("name")):
                return text_result("invalid state name", True)
            name = str(args["name"])
            # machine:load(filename) schedules asynchronously — verify the file exists first.
            found = _find_state_file(deps["config"].state_dir, name, 0)
            if found is None:
                return text_result(f'no saved state named "{name}"', True)
            response = deps["bridge"].request("load_state", {"name": name})
            if not response.get("ok"):
                return text_result(str(response.get("error")), True)
            return text_result(json.dumps({"scheduled": True, "name": name}))
        except Exception as exc:  # noqa: BLE001
            return text_result(_message_of(exc), True)

    return {
        "coco_start": coco_start,
        "coco_stop": coco_stop,
        "coco_status": coco_status,
        "coco_mount_flop": coco_mount_flop,
        "coco_unmount_flop": coco_unmount_flop,
        "coco_type": coco_type,
        "coco_snapshot": coco_snapshot,
        "coco_soft_reset": coco_soft_reset,
        "coco_list_images": coco_list_images,
        "coco_build_disk": coco_build_disk,
        "coco_read_memory": coco_read_memory,
        "coco_write_memory": coco_write_memory,
        "coco_save_state": coco_save_state,
        "coco_load_state": coco_load_state,
    }


INPUT_SCHEMAS: dict[str, dict[str, Any]] = {
    "coco_start": {"type": "object", "properties": {}},
    "coco_stop": {"type": "object", "properties": {}},
    "coco_status": {"type": "object", "properties": {}},
    "coco_mount_flop": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": (
                    "Disk image path. Prefer storage/disks/name.dsk (from MCP root) or an absolute path"
                ),
            },
            "drive": {
                "type": "string",
                "enum": ["flop1", "flop2"],
                "description": "Disk drive. Defaults to flop1",
            },
        },
        "required": ["path"],
    },
    "coco_unmount_flop": {
        "type": "object",
        "properties": {
            "drive": {
                "type": "string",
                "enum": ["flop1", "flop2"],
                "description": "Disk drive. Defaults to flop1",
            }
        },
    },
    "coco_type": {
        "type": "object",
        "properties": {
            "text": {
                "type": "string",
                "description": "Text to post, including optional {ENTER} or {BREAK} codes",
            },
            "pressEnter": {
                "type": "boolean",
                "description": (
                    "Append {ENTER} when the text does not already end with it. Defaults to true"
                ),
            },
        },
        "required": ["text"],
    },
    "coco_snapshot": {"type": "object", "properties": {}},
    "coco_soft_reset": {"type": "object", "properties": {}},
    "coco_list_images": {"type": "object", "properties": {}},
    "coco_build_disk": {
        "type": "object",
        "properties": {
            "dskPath": {
                "type": "string",
                "description": "Output .dsk path (prefer storage/disks/name.dsk)",
            },
            "files": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "hostPath": {
                            "type": "string",
                            "description": "Host file (prefer storage/host/bas|bin|data/...)",
                        },
                        "cocoName": {"type": "string"},
                        "kind": {"type": "string", "enum": ["bas", "bin", "data"]},
                    },
                    "required": ["hostPath", "cocoName", "kind"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["dskPath", "files"],
    },
    "coco_read_memory": {
        "type": "object",
        "properties": {
            "address": {
                "type": "string",
                "description": "Hex address in the current 64K MMU window, such as 0400 or 0x0400",
            },
            "length": {
                "type": "integer",
                "description": "Number of bytes, from 1 through 65536",
            },
        },
        "required": ["address", "length"],
    },
    "coco_write_memory": {
        "type": "object",
        "properties": {
            "address": {
                "type": "string",
                "description": "Hex address in the current 64K MMU window",
            },
            "data": {"type": "string", "description": "Space-separated hex bytes"},
        },
        "required": ["address", "data"],
    },
    "coco_save_state": {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "State name stored under the state directory"},
        },
        "required": ["name"],
    },
    "coco_load_state": {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "State name stored under the state directory"},
        },
        "required": ["name"],
    },
}


def create_tool_handlers(
    deps: MutableMapping[str, Any],
) -> dict[str, Callable[[Mapping[str, Any]], dict[str, Any]]]:
    bound: dict[str, Callable[[Mapping[str, Any]], dict[str, Any]]] = {}
    handlers = _handlers()
    for name in TOOL_INFO:
        handler = handlers.get(name)
        if handler is None:
            raise RuntimeError(f"missing handler {name}")

        def make(h: Callable[..., dict[str, Any]] = handler) -> Callable[[Mapping[str, Any]], dict[str, Any]]:
            return lambda args: h(deps, args or {})

        bound[name] = make()
    return bound


def register_tools(server: ToolServer, deps: MutableMapping[str, Any]) -> None:
    bound = create_tool_handlers(deps)
    for name, info in TOOL_INFO.items():
        server.register_tool(
            name,
            info["description"],
            INPUT_SCHEMAS.get(name, {"type": "object", "properties": {}}),
            bound[name],
        )
