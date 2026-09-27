"""Run the CoCo 3 MCP server on localhost HTTP. No IDE required.

    python -m coco3_mcp.serve
"""

from __future__ import annotations

import os
import sys

from coco3_mcp.__main__ import create_app, project_root
from coco3_mcp.client import probe
from coco3_mcp.config import load_dotenv
from coco3_mcp.endpoint import bind_from_env, endpoint_url
from coco3_mcp.http_server import serve_http


def main() -> int:
    root = project_root()
    file_env = load_dotenv(root / ".env")
    merged = {**file_env, **{k: v for k, v in os.environ.items()}}
    try:
        host, port = bind_from_env(merged)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    url = endpoint_url(host, port)
    if probe(host, port):
        print(f"coco3-mcp-bridge already listening on {url}", file=sys.stderr)
        return 0
    deps = create_app()
    deps["logger"].log(f"mcp http listening on {url}")
    print(f"coco3-mcp-bridge listening on {url}", file=sys.stderr)
    try:
        serve_http(deps, host, port)
    except OSError as exc:
        print(f"could not listen on {url}: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
