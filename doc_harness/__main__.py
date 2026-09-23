"""Launch Doc Harness in a true interactive terminal."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .tui import ReadingApp


def main() -> int:
    parser = argparse.ArgumentParser(description="Full-screen weekly reading list harness.")
    parser.add_argument(
        "--workspace", type=Path, default=Path.home() / "doc-harness-workspaces" / "weekly",
        help="Workspace to open or create (default: ~/doc-harness-workspaces/weekly).",
    )
    args = parser.parse_args()
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        parser.error("The raw terminal UI needs an interactive TTY; launch it in a terminal.")
    ReadingApp(args.workspace).run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
