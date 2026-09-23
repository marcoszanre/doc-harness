import tempfile
import unittest
import hashlib
from pathlib import Path
from threading import Event
from unittest.mock import patch

from doc_harness.sources import EXTRACTION_CACHE_VERSION, html_to_markdown, index_sources, public_url
from doc_harness.workspace import Workspace


class SourceTests(unittest.TestCase):
    def test_html_excludes_navigation_and_scripts(self):
        text = html_to_markdown("<nav>MENU</nav><script>BAD()</script><article><h1>Reading</h1><p>Some notes.</p></article>")
        self.assertIn("# Reading", text)
        self.assertNotIn("MENU", text)
        self.assertNotIn("BAD()", text)

    def test_article_body_excludes_share_tags_and_related_posts(self):
        html = (
            "<main><h1>Article Title</h1><div class='entry-content'>"
            "<p>The whole original article.</p><h2>A useful section</h2>"
            "<p>More complete source text.</p></div>"
            "<div><h2>Share</h2><p>Link copied!</p>"
            "<h2>Tags</h2><h2>Related posts</h2></div></main>"
        )
        text = html_to_markdown(html)
        self.assertIn("# Article Title", text)
        self.assertIn("## A useful section", text)
        self.assertIn("More complete source text.", text)
        self.assertNotIn("Share", text)
        self.assertNotIn("Related posts", text)

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
            with self.assertRaisesRegex(ValueError, "Every source is required"):
                index_sources(workspace, lambda *args: events.append(args), Event())
            self.assertIn("empty.txt", str(events))

    @patch("doc_harness.sources.fetch_url", return_value="# Real Article\n\nComplete text.")
    def test_article_extraction_upgrade_ignores_old_cached_page(self, fetch):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Workspace.create(Path(directory) / "week")
            url = "https://example.org/blog/post"
            workspace.add_url(url)
            old = workspace.cache / (hashlib.sha256(url.encode()).hexdigest() + ".md")
            old.write_text("## Share\n\nOld noisy cache.", encoding="utf-8")
            sources, errors = index_sources(workspace, lambda *_: None, Event())
            self.assertFalse(errors)
            self.assertIn("Complete text.", sources[0].content)
            self.assertNotIn("Share", sources[0].content)
            self.assertTrue((workspace.cache / f"{old.stem}-v{EXTRACTION_CACHE_VERSION}.md").exists())
            fetch.assert_called_once_with(url)
