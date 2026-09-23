import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from textual.widgets import Input, Static

from doc_harness.foundry import Completion
from doc_harness.tui import ReadingApp


class FakeFoundry:
    def complete(self, messages, emit, cancel):
        text = "# Weekly Reading\n\n## Ideas\n\n" + "A practical insight from the notes [1]. " * 46
        emit("answer", text)
        return Completion(text)

    def close(self):
        pass


class TuiTests(unittest.IsolatedAsyncioTestCase):
    async def test_composer_is_visible_focused_and_receives_keystrokes(self):
        with tempfile.TemporaryDirectory() as directory:
            for size in ((120, 40), (90, 28)):
                with self.subTest(size=size):
                    app = ReadingApp(Path(directory) / f"weekly-{size[0]}")
                    async with app.run_test(size=size) as pilot:
                        await pilot.pause()
                        composer = app.query_one("#composer", Input)
                        self.assertGreaterEqual(composer.region.y, 1)
                        self.assertLessEqual(composer.region.bottom, app.size.height - 1)
                        self.assertIs(app.focused, composer)
                        await pilot.press("a")
                        self.assertEqual(composer.value, "a")

    async def test_raw_ui_accepts_workspace_commands(self):
        with tempfile.TemporaryDirectory() as directory:
            app = ReadingApp(Path(directory) / "weekly")
            async with app.run_test(size=(120, 40)) as pilot:
                await pilot.pause()
                composer = app.query_one("#composer", Input)
                composer.value = "/format pdf"
                await pilot.press("enter")
                await pilot.pause()
                self.assertEqual(app.workspace.state["settings"]["format"], "pdf")
                self.assertIn("PDF", str(app.query_one("#settings", Static).render()))
                self.assertFalse(app.busy)

    async def test_build_approval_flow_in_full_screen_ui(self):
        with tempfile.TemporaryDirectory() as directory, patch("doc_harness.tui.Foundry", FakeFoundry):
            app = ReadingApp(Path(directory) / "weekly")
            (app.workspace.inputs / "note.md").write_text("A useful insight for this week.", encoding="utf-8")
            async with app.run_test(size=(120, 40)) as pilot:
                await pilot.pause()
                app.query_one("#composer", Input).value = "/words 200"
                await pilot.press("enter")
                app.query_one("#composer", Input).value = "/build"
                await pilot.press("enter")
                for _ in range(100):
                    await pilot.pause(0.05)
                    if not app.busy:
                        break
                self.assertFalse(app.busy)
                self.assertEqual(app.workspace.state["stage"], "Approval required")
                app.query_one("#composer", Input).value = "/approve"
                await pilot.press("enter")
                for _ in range(100):
                    await pilot.pause(0.05)
                    if not app.busy:
                        break
                self.assertFalse(app.busy)
                self.assertEqual(app.workspace.state["stage"], "Exported")
                self.assertEqual(len(list(app.workspace.output.glob("*.md"))), 1)
