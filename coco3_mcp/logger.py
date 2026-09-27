"""File + stderr logger that never writes to stdout (MCP stdio safety)."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


@dataclass
class Logger:
    log_path: Path

    def log(self, message: str) -> None:
        now = datetime.now(timezone.utc)
        stamp = (
            now.strftime("%Y-%m-%dT%H:%M:%S.")
            + f"{now.microsecond // 1000:03d}Z"
        )
        line = f"[{stamp}] {message}\n"
        sys.stderr.write(line)
        sys.stderr.flush()
        with self.log_path.open("a", encoding="utf-8") as handle:
            handle.write(line)


def create_logger(log_dir: str | Path) -> Logger:
    directory = Path(log_dir)
    directory.mkdir(parents=True, exist_ok=True)
    return Logger(log_path=directory / "mcp.log")
