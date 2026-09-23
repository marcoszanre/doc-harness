"""Extract multiple local files and public links from a single user message."""

from __future__ import annotations

import re
from pathlib import Path

from .workspace import INPUT_SUFFIXES

URL = re.compile(r"https?://[^\s\"'<>;,]+", re.I)
FILE = re.compile(
    r"(?i)(?:[A-Z]:[\\/]|\\\\)[^\r\n\"';]*?\.(?:pdf|docx|md|txt|html|htm)"
    r"(?=$|[\s;,\"'.])"
)


def extract_sources(message: str) -> list[str]:
    matches = [*URL.finditer(message), *FILE.finditer(message)]
    matches.sort(key=lambda item: item.start())
    results: list[str] = []
    for match in matches:
        item = match.group()
        if match.re == URL:
            item = item.rstrip(".,")
            if item.endswith(")") and item.count(")") > item.count("("):
                item = item[:-1]
        if item and item not in results:
            results.append(item)
    if results:
        return results

    for part in re.split(r"[;\r\n]+", message):
        item = part.strip().strip('"').strip("'")
        if not item or len(item) > 240 or ":" in item or '"' in item or "'" in item:
            continue
        path = Path(item)
        if path.suffix.lower() in INPUT_SUFFIXES and path.is_file() and item not in results:
            results.append(item)
    return results


def only_sources(message: str, sources: list[str]) -> bool:
    remaining = message
    for source in sources:
        remaining = remaining.replace(source, "", 1)
    return not remaining.strip(" \t\r\n;,'\"[]()")
