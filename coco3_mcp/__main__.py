"""Entry point: python -m coco3_mcp"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from coco3_mcp.bridge_server import create_bridge_server
from coco3_mcp.config import load_config, load_dotenv, write_bridge_port_file
from coco3_mcp.logger import create_logger
from coco3_mcp.mame_process import create_mame_controller
from coco3_mcp.mcp_server import run_stdio_server
from coco3_mcp.toolchain import create_toolchain


def project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def create_app() -> dict:
    root = project_root()
    file_env = load_dotenv(root / ".env")
    merged = {**file_env, **{k: v for k, v in os.environ.items()}}
    config = load_config(merged, root)
    for directory in (
        config.log_dir,
        config.snapshot_dir,
        config.state_dir,
        config.work_dir,
        config.storage_dir,
        config.disks_dir,
        config.host_bas_dir,
        config.host_bin_dir,
        config.host_data_dir,
    ):
        directory.mkdir(parents=True, exist_ok=True)
    write_bridge_port_file(config)
    logger = create_logger(config.log_dir)
    mame = create_mame_controller(config)
    bridge = create_bridge_server(
        config.bridge_port,
        lambda line, error: logger.log(
            f"bridge received malformed line: {line} ({error})"
        ),
    )

    def on_unexpected(code: int | None) -> None:
        logger.log(f"mame exited unexpectedly code={code}")
        try:
            bridge.stop()
        except Exception as exc:  # noqa: BLE001
            logger.log(f"bridge stop after mame exit failed: {exc}")

    mame.on_unexpected_exit(on_unexpected)
    deps = {
        "config": config,
        "mame": mame,
        "bridge": bridge,
        "toolchain": create_toolchain(config.decb_path, cwd=str(config.root_dir)),
        "logger": logger,
    }
    return deps


def main() -> int:
    deps = create_app()
    print("coco3-mcp-bridge listening on stdio", file=sys.stderr)
    run_stdio_server(deps)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
