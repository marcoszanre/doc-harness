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
MAX_EXTRACTED_CHARS = 2_000_000
EXTRACTION_CACHE_VERSION = 2
HEADERS = {"User-Agent": "ReadingHarness/0.2 (weekly reading collection)", "Accept": "text/html,text/plain,text/markdown,application/pdf"}


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


class ArticleBody(HTMLParser):
    VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "wbr"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.body = HtmlToMarkdown()
        self.depth = 0
        self.title_depth = 0
        self.title_parts: list[str] = []
        self.title_seen = False
        self.found = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "h1" and not self.title_seen:
            self.title_seen = True
            self.title_depth = 1
        elif self.title_depth and tag not in self.VOID:
            self.title_depth += 1
        if not self.depth and tag == "div" and "entry-content" in (dict(attrs).get("class") or "").split():
            self.depth = 1
            self.found = True
            return
        if self.depth:
            self.body.handle_starttag(tag, attrs)
            if tag not in self.VOID:
                self.depth += 1

    def handle_endtag(self, tag: str) -> None:
        if self.title_depth:
            self.title_depth -= 1
        if self.depth:
            if self.depth > 1:
                self.body.handle_endtag(tag)
            self.depth -= 1

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self.depth:
            self.body.handle_starttag(tag, attrs)

    def handle_data(self, data: str) -> None:
        if self.title_depth:
            self.title_parts.append(data)
        if self.depth:
            self.body.handle_data(data)

    def text(self) -> str:
        body = self.body.text()
        title = " ".join("".join(self.title_parts).split())
        return f"# {title}\n\n{body}" if title and not body.startswith(f"# {title}") else body


def html_to_markdown(raw: str) -> str:
    article = ArticleBody()
    article.feed(raw)
    if article.found:
        return article.text()
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
        pages = PdfReader(path).pages
        text = "\n\n".join(page.extract_text() or "" for page in pages)
    elif suffix == ".docx":
        with zipfile.ZipFile(path) as archive:
            if sum(item.file_size for item in archive.infolist()) > 25_000_000:
                raise ValueError("Expanded Word document exceeds the 25 MB limit.")
        blocks = []
        for block in Document(path).iter_inner_content():
            if hasattr(block, "rows"):
                blocks.extend(" | ".join(cell.text for cell in row.cells) for row in block.rows)
            else:
                blocks.append(block.text)
        text = "\n\n".join(blocks)
    else:
        text = path.read_text(encoding="utf-8-sig")
        if suffix in {".html", ".htm"}:
            text = html_to_markdown(text)
    if not text.strip():
        raise ValueError("No selectable text found; OCR is not included.")
    if len(text) > MAX_EXTRACTED_CHARS:
        raise ValueError("Extracted text exceeds the 2 million character per-source limit.")
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
                cache = workspace.cache / (
                    f"{hashlib.sha256(url.encode()).hexdigest()}-v{EXTRACTION_CACHE_VERSION}.md"
                )
                if cache.is_file() and not refresh:
                    text = cache.read_text(encoding="utf-8")
                else:
                    text = fetch_url(url)
                    if not text.strip():
                        raise ValueError("No readable text found.")
                    from .workspace import atomic_text

                    if len(text) > MAX_EXTRACTED_CHARS:
                        raise ValueError("Extracted text exceeds the 2 million character per-source limit.")
                    atomic_text(cache, text)
                reference = url
            if not text.strip():
                raise ValueError("No readable text found.")
            if len(text) > MAX_EXTRACTED_CHARS:
                raise ValueError("Extracted text exceeds the 2 million character per-source limit.")
            indexed.append(IndexedSource(label, reference, text))
        except (ValueError, OSError, RuntimeError, PdfReadError, PackageNotFoundError) as error:
            errors.append(f"{label}: {error}")
            emit("error", errors[-1])
    if errors:
        raise ValueError("Every source is required; fix these extraction errors: " + "; ".join(errors))
    return indexed, errors
