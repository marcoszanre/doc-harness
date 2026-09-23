"""Launch Doc Harness in a true interactive terminal."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .tui import ReadingApp


def main() -> int:
    parser = argparse.ArgumentParser(description="Full-screen weekly reading list harness.")
    parser.add_argument(
        "--workspace", type=Path,
        help="Open or create this workspace directly. Without it, the TUI asks where to work.",
    )
    args = parser.parse_args()
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        parser.error("The raw terminal UI needs an interactive TTY; launch it in a terminal.")
    workspace = args.workspace
    while True:
        result = ReadingApp(workspace).run()
        if result != "restart":
            return 0
        workspace = None


if __name__ == "__main__":
    raise SystemExit(main())
