import tempfile
import unittest
from pathlib import Path
from threading import Event

from doc_harness.exporters import export
from doc_harness.foundry import Completion
from doc_harness.workflow import build, review
from doc_harness.workspace import Workspace


class FakeModel:
    def __init__(self, answer):
        self.answer = answer
        self.calls = 0

    def complete(self, messages, emit, cancel, tools=None):
        self.calls += 1
        emit("answer", self.answer)
        return Completion(self.answer)


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.workspace = Workspace.create(Path(self.temp.name) / "weekly")
        (self.workspace.inputs / "one.md").write_text("# One\nAn important idea.\n", encoding="utf-8")
        (self.workspace.inputs / "two.md").write_text("# Two\nAnother important idea.\n", encoding="utf-8")

    def test_quality_gate_blocks_missing_citations(self):
        report = review("# Reading\n\nOnly [1] is here.\n\n## Wrap-up\n\nDone.", [1, 2], 200)
        self.assertTrue(report.issues)
        self.assertTrue(report.warnings)

    def test_build_requires_review_then_exports_markdown(self):
        paragraph = "This week brought two complementary themes [1] [2]. " * 27
        model = FakeModel(f"# Weekly Reading\n\n## Key Takeaways\n\n{paragraph}")
        events = []
        result = build(self.workspace, model, lambda *args: events.append(args), Event())
        self.assertFalse(result.issues)
        self.assertEqual(self.workspace.state["stage"], "Approval required")
        path = Path(export(self.workspace))
        self.assertTrue(path.is_file())
        text = path.read_text(encoding="utf-8")
        self.assertIn("An important idea.", text)
        self.assertIn("Another important idea.", text)
        self.assertIn("[Source 1: One](#source-1)", text)
        self.assertIn('id="source-2"', text)
        self.assertGreaterEqual(model.calls, 1)
        self.assertNotIn("pending", self.workspace.state)

    def test_changed_file_disallows_export(self):
        model = FakeModel("# Weekly\n\n## Notes\n\nA [1] and B [2].")
        build(self.workspace, model, lambda *_: None, Event())
        (self.workspace.inputs / "one.md").write_text("Changed content.", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "sources or settings changed"):
            export(self.workspace)

    def test_blocking_gate_disallows_export(self):
        model = FakeModel("# Weekly\n\n## Notes\n\nOnly [1] included.")
        result = build(self.workspace, model, lambda *_: None, Event())
        self.assertTrue(result.issues)
        with self.assertRaisesRegex(ValueError, "Quality gate blocked"):
            export(self.workspace)

    def test_file_size_limit_keeps_pending_approval(self):
        model = FakeModel("# Weekly\n\n## Notes\n\nBoth [1] and [2] are covered.")
        self.workspace.set_format("docx")
        self.workspace.set_max_file_kb(10)
        build(self.workspace, model, lambda *_: None, Event())
        with self.assertRaisesRegex(ValueError, "10 KB limit"):
            export(self.workspace)
        self.assertFalse(list(self.workspace.output.iterdir()))
        self.assertIn("pending", self.workspace.state)

    def test_modified_draft_cannot_remove_original_content(self):
        model = FakeModel("A complete weekly overview [1] [2].")
        build(self.workspace, model, lambda *_: None, Event())
        (self.workspace.cache / "draft.md").write_text("# Only a summary", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "reviewed draft changed"):
            export(self.workspace)
