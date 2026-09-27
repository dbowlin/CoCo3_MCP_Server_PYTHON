"""ToolShed decb helpers for building Disk BASIC images."""

from __future__ import annotations

import subprocess
from typing import Any, Callable, Mapping, Sequence


Runner = Callable[[str, list[str]], Mapping[str, Any]]


def plan_decb_steps(req: Mapping[str, Any]) -> list[dict[str, list[str]]]:
    dsk_path = str(req["dskPath"])
    files: Sequence[Mapping[str, Any]] = req.get("files") or []
    steps: list[dict[str, list[str]]] = [{"args": ["dskini", "-3", dsk_path]}]
    for file in files:
        kind = file.get("kind")
        if kind not in ("bas", "bin", "data"):
            raise ValueError(f"unknown coco file kind: {kind}")
        coco_name = str(file.get("cocoName") or "")
        if not coco_name or any(ch in coco_name for ch in ",/\\"):
            raise ValueError(f"invalid coco name: {coco_name}")
        destination = f"{dsk_path},{coco_name}"
        host_path = str(file["hostPath"])
        if kind == "bas":
            steps.append({"args": ["copy", "-t", host_path, destination]})
        else:
            steps.append({"args": ["copy", host_path, destination]})
    return steps


def _default_runner(cwd: str | None = None) -> Runner:
    def run(command: str, args: list[str]) -> dict[str, Any]:
        completed = subprocess.run(
            [command, *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            check=False,
        )
        return {
            "code": completed.returncode if completed.returncode is not None else 1,
            "stdout": completed.stdout or "",
            "stderr": completed.stderr or "",
        }

    return run


class Toolchain:
    def __init__(self, decb_path: str, runner: Runner, cwd: str | None = None) -> None:
        self._decb_path = decb_path
        self._runner = runner
        self._cwd = cwd

    def build_disk(self, req: Mapping[str, Any]) -> dict[str, Any]:
        planned = plan_decb_steps(req)
        steps: list[str] = []
        for step in planned:
            result = self._runner(self._decb_path, step["args"])
            code = int(result.get("code", 1))
            if code != 0:
                stderr = str(result.get("stderr") or "").strip()
                stdout = str(result.get("stdout") or "").strip()
                message = stderr or stdout or f"decb exited {code}"
                raise RuntimeError(message)
            steps.append(" ".join(step["args"]))
        return {"dskPath": req["dskPath"], "steps": steps}


def create_toolchain(
    decb_path: str,
    runner: Runner | None = None,
    cwd: str | None = None,
) -> Toolchain:
    active = runner if runner is not None else _default_runner(cwd)
    return Toolchain(decb_path, active, cwd)
