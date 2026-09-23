import tempfile
import unittest
from pathlib import Path
from threading import Event
from unittest.mock import patch

from doc_harness.sources import html_to_markdown, index_sources, public_url
from doc_harness.workspace import Workspace


class SourceTests(unittest.TestCase):
    def test_html_excludes_navigation_and_scripts(self):
        text = html_to_markdown("<nav>MENU</nav><script>BAD()</script><article><h1>Reading</h1><p>Some notes.</p></article>")
        self.assertIn("# Reading", text)
        self.assertNotIn("MENU", text)
        self.assertNotIn("BAD()", text)

    def test_rejects_private_and_unsafe_urls(self):
        with patch("doc_harness.sources.socket.getaddrinfo", return_value=[(None, None, None, None, ("127.0.0.1", 0))]):
            with self.assertRaises(ValueError):
                public_url("http://localhost/data")
            with self.assertRaises(ValueError):
                public_url("https://example.com/data")
        with self.assertRaises(ValueError):
            public_url("file:///etc/passwd")

    def test_partial_index_failure_is_reported(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Workspace.create(Path(directory) / "week")
            (workspace.inputs / "empty.txt").write_text("", encoding="utf-8")
            (workspace.inputs / "ok.md").write_text("# Weekly\nA useful story.", encoding="utf-8")
            events = []
            sources, errors = index_sources(workspace, lambda *args: events.append(args), Event())
            self.assertEqual(len(sources), 1)
            self.assertEqual(len(errors), 1)
            self.assertIn("empty.txt", errors[0])
