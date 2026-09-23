"""Bounded source extraction. Only copied inputs and public HTTP(S) URLs are read."""

from __future__ import annotations

import hashlib
import html
import ipaddress
import json
import os
import re
import socket
import zipfile
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from threading import Event
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener, urlopen

from docx import Document
from docx.opc.exceptions import PackageNotFoundError
from pypdf import PdfReader
from pypdf.errors import PdfReadError

from .workspace import Workspace

MAX_DOWNLOAD = 2_000_000
MAX_SOURCE_CHARS = 12_000
MAX_CONTEXT_CHARS = 100_000
HEADERS = {"User-Agent": "DocHarness/0.1 (weekly reading list)", "Accept": "text/html,text/plain,text/markdown,application/pdf"}


def public_url(url: str) -> str:
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("Only public HTTP(S) URLs without embedded credentials are allowed.")
    if parsed.port not in (None, 80, 443):
        raise ValueError("Only standard web ports are allowed.")
    host = parsed.hostname.rstrip(".").lower()
    if host in {"localhost", "localhost.localdomain"} or host.endswith((".local", ".internal")):
        raise ValueError("Local network hosts cannot be fetched.")
    try:
        addresses = {entry[4][0] for entry in socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)}
    except socket.gaierror as error:
        raise ValueError(f"Cannot resolve source host: {host}") from error
    if not addresses or any(not ipaddress.ip_address(address).is_global for address in addresses):
        raise ValueError("Private, reserved, and loopback hosts cannot be fetched.")
    return url


class PublicRedirects(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        return super().redirect_request(request, fp, code, msg, headers, public_url(newurl))


class HtmlToMarkdown(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skip = 0
        self.link: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "nav", "header", "footer", "aside", "svg", "form"}:
            self.skip += 1
        if self.skip:
            return
        if tag in {"p", "div", "section", "article", "br", "li", "blockquote"}:
            self.parts.append("\n" if tag == "br" else "\n\n")
        if tag in {"h1", "h2", "h3"}:
            self.parts.append("\n\n" + "#" * int(tag[1]) + " ")
        if tag == "li":
            self.parts.append("- ")
        if tag == "a":
            self.link = dict(attrs).get("href")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "nav", "header", "footer", "aside", "svg", "form"}:
            self.skip = max(0, self.skip - 1)
        if tag == "a" and not self.skip:
            self.link = None

    def handle_data(self, data: str) -> None:
        if not self.skip:
            self.parts.append(data)

    def text(self) -> str:
        text = html.unescape("".join(self.parts)).replace("\r", "")
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n[ \t]+", "\n", text)
        return re.sub(r"\n{3,}", "\n\n", text).strip()


def html_to_markdown(raw: str) -> str:
    parser = HtmlToMarkdown()
    parser.feed(raw)
    return parser.text()


def fetch_url(url: str) -> str:
    public_url(url)
    request = Request(url, headers=HEADERS)
    opener = build_opener(PublicRedirects())
    try:
        with opener.open(request, timeout=25) as response:
            public_url(response.url)
            content_type = response.headers.get_content_type()
            if content_type not in {"text/html", "text/plain", "text/markdown", "application/pdf"}:
                raise ValueError(f"Unsupported response type: {content_type}")
            raw = response.read(MAX_DOWNLOAD + 1)
            if len(raw) > MAX_DOWNLOAD:
                raise ValueError("Web page exceeds the 2 MB download limit.")
            if content_type == "application/pdf":
                raise ValueError("Web PDFs must be downloaded and added as local files.")
            encoding = response.headers.get_content_charset() or "utf-8"
    except HTTPError as error:
        raise ValueError(f"Source returned HTTP {error.code}.") from error
    except (URLError, TimeoutError) as error:
        raise ValueError(f"Could not reach source: {url}") from error
    decoded = raw.decode(encoding, errors="replace")
    return html_to_markdown(decoded) if content_type == "text/html" else decoded.strip()


def read_file(path: Path) -> str:
    if path.stat().st_size > 8_000_000:
        raise ValueError("Local file exceeds the 8 MB per-file limit.")
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        text = "\n\n".join(page.extract_text() or "" for page in PdfReader(path).pages[:60])
    elif suffix == ".docx":
        with zipfile.ZipFile(path) as archive:
            if sum(item.file_size for item in archive.infolist()) > 25_000_000:
                raise ValueError("Expanded Word document exceeds the 25 MB limit.")
        text = "\n\n".join(p.text for p in Document(path).paragraphs)
    else:
        text = path.read_text(encoding="utf-8-sig")
        if suffix in {".html", ".htm"}:
            text = html_to_markdown(text)
    if not text.strip():
        raise ValueError("No selectable text found; OCR is not included.")
    return text


def web_search(query: str, limit: int = 5) -> list[dict]:
    key = os.getenv("TAVILY_API_KEY")
    if not key:
        raise ValueError("Set TAVILY_API_KEY in your environment to search the web.")
    if not query.strip() or not 1 <= limit <= 5:
        raise ValueError("Enter a search query and request 1 to 5 results.")
    body = json.dumps({"query": query, "max_results": limit, "search_depth": "basic", "include_answer": False}).encode()
    request = Request(
        "https://api.tavily.com/search",
        data=body,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=20) as response:
            results = json.load(response).get("results", [])
    except HTTPError as error:
        raise ValueError(f"Search returned HTTP {error.code}.") from error
    except (URLError, TimeoutError) as error:
        raise ValueError("Web search is unavailable.") from error
    return [{"title": item.get("title", ""), "url": item["url"], "snippet": item.get("content", "")[:280]} for item in results[:limit]]


@dataclass
class IndexedSource:
    label: str
    reference: str
    content: str


def index_sources(workspace: Workspace, emit, cancel: Event, refresh: bool = False) -> tuple[list[IndexedSource], list[str]]:
    sources = workspace.sources()
    if not sources:
        raise ValueError("Add a file or URL before building a reading list.")
    indexed: list[IndexedSource] = []
    errors: list[str] = []
    remaining = MAX_CONTEXT_CHARS
    for number, item in enumerate(sources, 1):
        if cancel.is_set():
            raise InterruptedError("Indexing was interrupted.")
        label = item["label"]
        emit("step", f"Indexing {number}/{len(sources)}: {label}")
        try:
            if item["kind"] == "file":
                text = read_file(item["path"])
                reference = label
            else:
                url = item["url"]
                cache = workspace.cache / (hashlib.sha256(url.encode()).hexdigest() + ".md")
                if cache.is_file() and not refresh:
                    text = cache.read_text(encoding="utf-8")
                else:
                    text = fetch_url(url)
                    if not text.strip():
                        raise ValueError("No readable text found.")
                    from .workspace import atomic_text

                    atomic_text(cache, text[:MAX_SOURCE_CHARS])
                reference = url
            if not text.strip():
                raise ValueError("No readable text found.")
            if remaining <= 0:
                raise ValueError("The 100,000-character context budget has been reached.")
            content = text[: min(MAX_SOURCE_CHARS, remaining)]
            remaining -= len(content)
            indexed.append(IndexedSource(label, reference, content))
        except (ValueError, OSError, RuntimeError, PdfReadError, PackageNotFoundError) as error:
            errors.append(f"{label}: {error}")
            emit("error", errors[-1])
    if not indexed:
        raise ValueError("All sources failed to index: " + "; ".join(errors))
    return indexed, errors
