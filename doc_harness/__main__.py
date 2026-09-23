"""Launch Reading Harness in a true interactive terminal."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .foundry import save_local_endpoint
from .tui import ReadingApp


def main() -> int:
    parser = argparse.ArgumentParser(description="Reading Harness: a full-screen weekly reading collection.")
    parser.add_argument(
        "--workspace", type=Path,
        help="Open or create this workspace directly. Without it, the TUI asks where to work.",
    )
    parser.add_argument(
        "--set-foundry-endpoint", metavar="URL",
        help="Save your Foundry OpenAI v1 base endpoint in a private user-local file.",
    )
    args = parser.parse_args()
    if args.set_foundry_endpoint:
        path = save_local_endpoint(args.set_foundry_endpoint)
        print(f"Foundry endpoint saved locally in {path}. No credentials were stored.")
        return 0
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
