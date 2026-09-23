import tempfile
import unittest
from pathlib import Path

from docx import Document
from pypdf import PdfReader

from doc_harness.exporters import write_docx, write_pdf


SAMPLE = "# Weekly Reading\n\n## Key Ideas\n\nUseful source [1].\n\n## Sources\n\n[1] Example — https://example.com\n"


class ExporterTests(unittest.TestCase):
    def test_docx_pdf_contain_readable_content(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            word = folder / "reading.docx"
            pdf = folder / "reading.pdf"
            write_docx(SAMPLE, word)
            write_pdf(SAMPLE, pdf)
            self.assertIn("Useful source [1].", "\n".join(p.text for p in Document(word).paragraphs))
            self.assertIn("Useful source [1].", PdfReader(pdf).pages[0].extract_text())
