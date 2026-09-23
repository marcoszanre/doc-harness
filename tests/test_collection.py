import tempfile
import unittest
from pathlib import Path
from threading import Event
from unittest.mock import patch

from docx import Document
from pypdf import PdfReader
from reportlab.pdfgen import canvas

from doc_harness.exporters import export
from doc_harness.foundry import Completion
from doc_harness.workflow import build
from doc_harness.workspace import Workspace


class ShortIntroduction:
    def complete(self, messages, emit, cancel):
        return Completion("This edition combines a blog post [2] and a PDF article [1].")


class CollectionTests(unittest.TestCase):
    @patch("doc_harness.sources.fetch_url")
    def test_full_blog_and_pdf_are_in_one_linked_file(self, fetch):
        blog_tail = "BLOG_TAIL_MARKER"
        fetch.return_value = "# Web Article\n\n" + ("A complete blog paragraph with context. " * 400) + blog_tail
        with tempfile.TemporaryDirectory() as directory:
            workspace = Workspace.create(Path(directory) / "week")
            source_pdf = workspace.inputs / "article.pdf"
            page = canvas.Canvas(str(source_pdf))
            page.drawString(70, 760, "PDF_UNIQUE_TEXT: original article content from the PDF.")
            page.save()
            workspace.add_url("https://example.org/blog")
            workspace.set_format("pdf")
            workspace.set_target_words(100)
            review = build(workspace, ShortIntroduction(), lambda *_: None, Event())
            self.assertFalse(review.issues)
            draft = (workspace.cache / "draft.md").read_text(encoding="utf-8")
            self.assertIn(blog_tail, draft)
            self.assertIn("PDF_UNIQUE_TEXT", draft)
            self.assertIn("[Source 2: Web Article](#source-2)", draft)
            self.assertIn('id="source-1"', draft)
            self.assertIn("https://example.org/blog", draft.split("## Original Sources", 1)[1])
            pdf = Path(export(workspace))
            reader = PdfReader(pdf)
            body = "\n".join(page.extract_text() for page in reader.pages)
            self.assertIn("PDF_UNIQUE_TEXT", body)
            self.assertIn(blog_tail, body)
            self.assertTrue(reader.outline)
            links = [
                annotation.get_object()
                for page in reader.pages
                for annotation in (page.get("/Annots") or [])
            ]
            self.assertTrue(any(link.get("/Dest") for link in links))
            self.assertTrue(any("example.org/blog" in str(link.get("/A")) for link in links))

            workspace.set_format("docx")
            build(workspace, ShortIntroduction(), lambda *_: None, Event())
            word = Document(export(workspace))
            xml = word._element.xml
            self.assertIn('w:anchor="source-1"', xml)
            self.assertIn('w:name="source-2"', xml)
            self.assertIn("BLOG_TAIL_MARKER", xml)
            self.assertIn("https://example.org/blog", [rel.target_ref for rel in word.part.rels.values()])
