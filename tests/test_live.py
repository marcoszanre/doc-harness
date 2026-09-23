"""Opt-in Azure integration: DOC_HARNESS_LIVE=1 python -m unittest tests.test_live."""

import os
import tempfile
import unittest
from pathlib import Path
from threading import Event

from doc_harness.exporters import export
from doc_harness.foundry import Foundry
from doc_harness.workflow import build
from doc_harness.workspace import Workspace


@unittest.skipUnless(os.getenv("DOC_HARNESS_LIVE") == "1", "No Azure calls in the default test suite")
class AzureIntegrationTests(unittest.TestCase):
    def test_two_sources_to_approved_markdown(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Workspace.create(Path(directory) / "weekly")
            (workspace.inputs / "monday.md").write_text(
                "# Monday\nThe Contoso engineering team used a pre-release checklist. "
                "The checklist caught missing documentation before deployment.",
                encoding="utf-8",
            )
            (workspace.inputs / "wednesday.md").write_text(
                "# Wednesday\nThe team rehearsed network retry scenarios. "
                "This exercise clarified when to retry and when to report an error.",
                encoding="utf-8",
            )
            workspace.set_target_words(200)
            model = Foundry()
            try:
                result = build(workspace, model, lambda *_: None, Event())
            finally:
                model.close()
            self.assertFalse(result.issues, result.issues)
            path = Path(export(workspace))
            text = path.read_text(encoding="utf-8")
            self.assertIn("monday.md", text)
            self.assertIn("wednesday.md", text)
