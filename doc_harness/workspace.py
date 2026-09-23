"""Durable workspace and task state; the model never receives write access."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import hashlib
from pathlib import Path
from urllib.parse import urlsplit

FORMATS = ("markdown", "pdf", "docx")
INPUT_SUFFIXES = {".md", ".txt", ".html", ".htm", ".pdf", ".docx"}


def atomic_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".doc-harness-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(text)
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


class Workspace:
    def __init__(self, root: Path | str) -> None:
        self.root = Path(root).expanduser().resolve()
        self.state_path = self.root / ".doc-harness.json"
        if not self.state_path.is_file():
            raise ValueError(f"Not a Doc Harness workspace: {self.root}. Use /new first.")
        self.inputs = self.root / "inputs"
        self.cache = self.root / "cache"
        self.output = self.root / "output"
        for folder in (self.inputs, self.cache, self.output):
            if not folder.is_dir() or folder.is_symlink() or not folder.resolve().is_relative_to(self.root):
                raise ValueError(f"Workspace folder is missing or points outside the workspace: {folder}")
        self.state = json.loads(self.state_path.read_text(encoding="utf-8"))
        if self.state.get("version") != 1 or not isinstance(self.state.get("sources"), list):
            raise ValueError("Unsupported or damaged workspace state.")

    @classmethod
    def create(cls, root: Path | str) -> Workspace:
        target = Path(root).expanduser().resolve()
        target.mkdir(parents=True, exist_ok=True)
        state_path = target / ".doc-harness.json"
        if state_path.exists():
            return cls(target)
        for name in ("inputs", "cache", "output"):
            (target / name).mkdir(exist_ok=True)
        atomic_text(
            state_path,
            json.dumps(
                {
                    "version": 1,
                    "sources": [],
                    "todos": [],
                    "chat": [],
                    "settings": {"format": "markdown", "target_words": 250, "max_file_kb": None},
                    "stage": "Ready",
                },
                indent=2,
            ),
        )
        return cls(target)

    def save(self) -> None:
        atomic_text(self.state_path, json.dumps(self.state, indent=2, ensure_ascii=False))

    def invalidate(self) -> None:
        self.state.pop("pending", None)
        self.state["stage"] = "Ready"

    def fingerprint(self) -> str:
        inputs = [
            (item["path"].name, item["path"].stat().st_size, item["path"].stat().st_mtime_ns)
            for item in self.sources() if item["kind"] == "file"
        ]
        data = [inputs, self.state["sources"], self.state["settings"]]
        return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()

    def add_file(self, source: Path | str) -> Path:
        path = Path(source).expanduser().resolve(strict=True)
        if not path.is_file() or path.suffix.lower() not in INPUT_SUFFIXES:
            raise ValueError("Supported files: .md, .txt, .html, .pdf, .docx.")
        if path.stat().st_size > 8_000_000:
            raise ValueError("Input exceeds the 8 MB per-file limit.")
        target = self.inputs / path.name
        if target.resolve() != path:
            if target.exists():
                if target.stat().st_size == path.stat().st_size and (
                    hashlib.sha256(target.read_bytes()).digest()
                    == hashlib.sha256(path.read_bytes()).digest()
                ):
                    return target
                raise FileExistsError(
                    f"An input named {target.name} already exists with different content."
                )
            shutil.copyfile(path, target)
        self.invalidate()
        self.save()
        return target

    def add_url(self, url: str) -> None:
        url = url.strip()
        parsed = urlsplit(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("Use an absolute http(s) URL.")
        if url in self.state["sources"]:
            raise ValueError("This URL is already in the reading list.")
        if len(self.state["sources"]) >= 30:
            raise ValueError("The reading list supports at most 30 URLs.")
        self.state["sources"].append(url)
        self.invalidate()
        self.save()

    def remove_source(self, number: int) -> str:
        sources = self.sources()
        if number < 1 or number > len(sources):
            raise ValueError("Source number is out of range.")
        source = sources[number - 1]
        if source["kind"] == "file":
            archived = self.cache / ("removed-" + source["path"].name)
            if archived.exists():
                raise FileExistsError(f"Archive already contains {archived.name}; move it first.")
            source["path"].replace(archived)
            removed = source["path"].name
        else:
            url = source["url"]
            self.state["sources"] = [item for item in self.state["sources"] if item != url]
            removed = url
        self.invalidate()
        self.save()
        return removed

    def sources(self) -> list[dict]:
        files = []
        for path in sorted(self.inputs.iterdir()):
            if path.is_file() and not path.is_symlink() and path.suffix.lower() in INPUT_SUFFIXES:
                files.append({"kind": "file", "path": path, "label": path.name})
        urls = [{"kind": "url", "url": url, "label": url} for url in self.state["sources"]]
        return files + urls

    def set_format(self, value: str) -> None:
        if value not in FORMATS:
            raise ValueError(f"Choose one of: {', '.join(FORMATS)}.")
        self.state["settings"]["format"] = value
        self.invalidate()
        self.save()

    def set_target_words(self, value: int) -> None:
        if not 100 <= value <= 2_000:
            raise ValueError("Edition summary must be between 100 and 2,000 words.")
        self.state["settings"]["target_words"] = value
        self.invalidate()
        self.save()

    def set_max_file_kb(self, value: int | None) -> None:
        if value is not None and not 10 <= value <= 50_000:
            raise ValueError("Maximum file size must be between 10 and 50,000 KB.")
        self.state["settings"]["max_file_kb"] = value
        self.invalidate()
        self.save()

    def add_todo(self, title: str) -> None:
        if not title.strip() or len(title) > 120:
            raise ValueError("A task needs a title of at most 120 characters.")
        self.state["todos"].append({"title": title.strip(), "done": False})
        self.save()

    def set_todo(self, number: int, done: bool) -> None:
        if number < 1 or number > len(self.state["todos"]):
            raise ValueError("Task number is out of range.")
        self.state["todos"][number - 1]["done"] = done
        self.save()
