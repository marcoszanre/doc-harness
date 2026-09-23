"""Three exporters from one approved Markdown draft, with bounded local writes."""

from __future__ import annotations

import html
import os
import re
import tempfile
from datetime import date
from pathlib import Path

from docx import Document
from docx.shared import Inches, Pt
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate

from .workspace import Workspace


def lines(markdown: str):
    for line in markdown.splitlines():
        text = line.strip()
        if not text:
            continue
        level = len(text) - len(text.lstrip("#"))
        if level in (1, 2, 3) and text[level:level + 1] == " ":
            yield ("heading", level, text[level:].strip())
        elif text.startswith(("- ", "* ")):
            yield ("bullet", 0, text[2:])
        else:
            yield ("paragraph", 0, text)


def plain(text: str) -> str:
    return re.sub(r"(?<!\w)[*`_]+|[*`_]+(?!\w)", "", text)


def _temp_output(path: Path, create) -> None:
    fd, name = tempfile.mkstemp(prefix=".doc-harness-", suffix=path.suffix, dir=path.parent)
    os.close(fd)
    temporary = Path(name)
    try:
        create(temporary)
        if not temporary.is_file() or temporary.stat().st_size == 0:
            raise ValueError("Exporter produced an empty file.")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def write_docx(markdown: str, path: Path) -> None:
    doc = Document()
    section = doc.sections[0]
    section.top_margin = Inches(0.85)
    section.bottom_margin = Inches(0.85)
    doc.styles["Normal"].font.name = "Aptos"
    doc.styles["Normal"].font.size = Pt(10.5)
    for kind, level, text in lines(markdown):
        text = plain(text)
        if kind == "heading":
            doc.add_heading(text, level=level)
        elif kind == "bullet":
            doc.add_paragraph(text, style="List Bullet")
        else:
            doc.add_paragraph(text)
    doc.save(path)


def _pdf_font() -> str:
    candidates = [
        Path(os.environ.get("WINDIR", "C:\\Windows")) / "Fonts" / "arial.ttf",
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    ]
    for candidate in candidates:
        if candidate.is_file():
            pdfmetrics.registerFont(TTFont("DocHarness", str(candidate)))
            return "DocHarness"
    return "Helvetica"


def write_pdf(markdown: str, path: Path) -> None:
    font = _pdf_font()
    base = ParagraphStyle(
        "Body", parent=getSampleStyleSheet()["BodyText"], fontName=font,
        fontSize=10, leading=15, textColor=colors.HexColor("#233047"), spaceAfter=9,
    )
    styles = {
        1: ParagraphStyle("Title", parent=base, fontSize=22, leading=27, spaceBefore=5, spaceAfter=20, textColor=colors.HexColor("#18264A")),
        2: ParagraphStyle("Heading", parent=base, fontSize=14, leading=19, spaceBefore=14, spaceAfter=9, textColor=colors.HexColor("#2155BC")),
        3: ParagraphStyle("Subheading", parent=base, fontSize=11, leading=16, spaceBefore=10, spaceAfter=6, textColor=colors.HexColor("#2155BC")),
    }
    story = []
    for kind, level, text in lines(markdown):
        text = plain(text)
        chunks = []
        position = 0
        for match in re.finditer(r"https?://[^\s<>]+", text):
            url = match.group().rstrip(".,)")
            chunks.append(html.escape(text[position:match.start()]))
            chunks.append(f'<link href="{html.escape(url, quote=True)}" color="#2155BC">{html.escape(url)}</link>')
            position = match.start() + len(url)
        chunks.append(html.escape(text[position:]))
        safe = "".join(chunks)
        if kind == "heading":
            story.append(Paragraph(safe, styles[level]))
        else:
            story.append(Paragraph(("&bull; " if kind == "bullet" else "") + safe, base))
    if not story:
        raise ValueError("The draft has no content.")
    doc = SimpleDocTemplate(str(path), pagesize=(595, 842), rightMargin=55, leftMargin=55, topMargin=55, bottomMargin=55)
    doc.build(story)


def export(workspace: Workspace) -> str:
    pending = workspace.state.get("pending")
    if not pending:
        raise ValueError("No draft is waiting for approval. Run /build first.")
    if pending["fingerprint"] != workspace.fingerprint():
        workspace.invalidate()
        workspace.save()
        raise ValueError("The sources or settings changed since the draft. Run /build again.")
    if pending["review"]["issues"]:
        raise ValueError("Quality gate blocked export: " + "; ".join(pending["review"]["issues"]) + ". Use /revise.")
    draft = (workspace.cache / "draft.md").read_text(encoding="utf-8")
    fmt = workspace.state["settings"]["format"]
    extension = {"markdown": ".md", "pdf": ".pdf", "docx": ".docx"}[fmt]
    stem = f"reading-list-{date.today().isoformat()}"
    path = workspace.output / f"{stem}{extension}"
    number = 2
    while path.exists():
        path = workspace.output / f"{stem}-{number}{extension}"
        number += 1

    def write(temporary: Path) -> None:
        if fmt == "markdown":
            temporary.write_text(draft, encoding="utf-8")
        elif fmt == "pdf":
            write_pdf(draft, temporary)
        else:
            write_docx(draft, temporary)
        max_kb = workspace.state["settings"]["max_file_kb"]
        if max_kb is not None and temporary.stat().st_size > max_kb * 1024:
            raise ValueError(f"Output exceeds the configured {max_kb} KB limit.")

    _temp_output(path, write)
    result = str(path)
    workspace.state["stage"] = "Exported"
    workspace.state["last_output"] = result
    workspace.state.pop("pending")
    workspace.save()
    return result
