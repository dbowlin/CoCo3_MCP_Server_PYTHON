"""Section 1 — logger writes stderr + logs/mcp.log, never stdout."""

from __future__ import annotations

import io
import re
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from coco3_mcp.logger import create_logger


class LoggerTests(unittest.TestCase):
    def test_logger_writes_same_line_to_stderr_and_file_never_stdout(self) -> None:
        with tempfile.TemporaryDirectory(prefix="coco-log-") as tmp:
            log_dir = Path(tmp) / "nested" / "logs"
            err = io.StringIO()
            out = io.StringIO()
            with redirect_stderr(err), redirect_stdout(out):
                logger = create_logger(log_dir)
                logger.log("hello")
            self.assertEqual(logger.log_path, log_dir / "mcp.log")
            self.assertRegex(
                err.getvalue(),
                r"^\[\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z\] hello\n$",
            )
            self.assertEqual(logger.log_path.read_text(encoding="utf-8"), err.getvalue())
            self.assertEqual(out.getvalue(), "")


if __name__ == "__main__":
    unittest.main()
