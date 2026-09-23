import tempfile
import unittest
from pathlib import Path

from doc_harness.workspace import Workspace


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.workspace = Workspace.create(self.root / "weekly")

    def test_reopen_source_and_settings(self):
        source = self.root / "note.md"
        source.write_text("One useful note.", encoding="utf-8")
        self.workspace.add_file(source)
        self.workspace.add_url("https://example.com/article")
        self.workspace.set_format("docx")
        reopened = Workspace(self.workspace.root)
        self.assertEqual(len(reopened.sources()), 2)
        self.assertEqual(reopened.state["settings"]["format"], "docx")

    def test_remove_archives_input_without_deleting(self):
        source = self.root / "note.txt"
        source.write_text("my notes", encoding="utf-8")
        self.workspace.add_file(source)
        self.workspace.remove_source(1)
        self.assertTrue(source.exists())
        self.assertTrue((self.workspace.cache / "removed-note.txt").exists())
        self.assertFalse(self.workspace.sources())

    def test_settings_invalidate_approval(self):
        self.workspace.state["pending"] = {"fingerprint": "stale"}
        self.workspace.set_target_words(400)
        self.assertNotIn("pending", self.workspace.state)
        with self.assertRaises(ValueError):
            self.workspace.set_max_file_kb(2)

    def test_readding_the_same_file_does_not_fail_or_duplicate(self):
        source = self.root / "source.md"
        source.write_text("A complete source.", encoding="utf-8")
        self.workspace.add_file(source)
        self.workspace.add_file(source)
        self.assertEqual(len(self.workspace.sources()), 1)

    def test_existing_workspace_without_usage_is_migrated_in_memory(self):
        self.workspace.state.pop("usage")
        self.workspace.save()
        reopened = Workspace(self.workspace.root)
        self.assertEqual(reopened.state["usage"]["requests"], 0)
