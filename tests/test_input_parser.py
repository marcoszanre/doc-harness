import tempfile
import unittest
from pathlib import Path

from doc_harness.input_parser import extract_sources, only_sources


class InputParserTests(unittest.TestCase):
    def test_two_quoted_paths_and_one_url_in_order(self):
        text = (
            'Add "C:\\Users\\you\\Downloads\\weekly article.pdf"; '
            'https://example.org/blog; "C:\\Users\\you\\Downloads\\more notes.docx"'
        )
        self.assertEqual(
            extract_sources(text),
            [
                "C:\\Users\\you\\Downloads\\weekly article.pdf",
                "https://example.org/blog",
                "C:\\Users\\you\\Downloads\\more notes.docx",
            ],
        )
        self.assertFalse(only_sources(text, extract_sources(text)))

    def test_plain_semicolon_separated_links(self):
        text = "https://example.org/one; https://example.org/two"
        self.assertEqual(len(extract_sources(text)), 2)
        self.assertTrue(only_sources(text, extract_sources(text)))

    def test_existing_relative_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            first = Path(directory) / "one.md"
            second = Path(directory) / "two.txt"
            first.write_text("one", encoding="utf-8")
            second.write_text("two", encoding="utf-8")
            self.assertEqual(extract_sources(f"{first}; {second}"), [str(first), str(second)])
