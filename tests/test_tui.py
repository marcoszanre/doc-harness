import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from textual.widgets import Button, Input, Select, Static

from doc_harness.foundry import Completion
from doc_harness.tui import ComposerSuggester, ReadingApp


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
                        self.assertGreaterEqual(composer.region.width, app.size.width - 4)
                        self.assertIs(app.focused, composer)
                        await pilot.press("a")
                        self.assertEqual(composer.value, "a")

    async def test_autocomplete_commands_and_local_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "article.md"
            path.write_text("A story", encoding="utf-8")
            suggestions = ComposerSuggester()
            self.assertEqual(await suggestions.get_suggestion("/bu"), "/build")
            self.assertEqual(
                await suggestions.get_suggestion(str(path.parent / "art")),
                str(path),
            )
            app = ReadingApp(Path(directory) / "week")
            async with app.run_test(size=(100, 32)) as pilot:
                await pilot.pause()
                composer = app.query_one("#composer", Input)
                composer.value = "/bu"
                await pilot.pause(0.1)
                await pilot.press("tab")
                self.assertEqual(composer.value, "/build")

    async def test_pasted_path_url_and_wrong_command_are_understood(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "my article.md"
            source.write_text("This week's complete article.", encoding="utf-8")
            second = Path(directory) / "other.md"
            second.write_text("A second complete article.", encoding="utf-8")
            app = ReadingApp(Path(directory) / "weekly")
            async with app.run_test(size=(120, 40)) as pilot:
                await pilot.pause()
                composer = app.query_one("#composer", Input)
                composer.value = f'"{source}"'
                await pilot.press("enter")
                self.assertEqual(len(app.workspace.sources()), 1)
                self.assertEqual(app.workspace.sources()[0]["kind"], "file")
                composer.value = "https://example.org/post"
                await pilot.press("enter")
                self.assertEqual(len(app.workspace.sources()), 2)
                self.assertEqual(app.workspace.sources()[1]["kind"], "url")
                composer.value = f'/add-url "{second}"'
                await pilot.press("enter")
                self.assertEqual(len(app.workspace.sources()), 3)
                self.assertEqual(app.workspace.sources()[1]["kind"], "file")
                app.query_one("#format-picker", Select).value = "pdf"
                await pilot.pause()
                self.assertEqual(app.workspace.state["settings"]["format"], "pdf")

    async def test_toolbar_build_preview_and_export(self):
        with tempfile.TemporaryDirectory() as directory, patch("doc_harness.tui.Foundry", FakeFoundry):
            app = ReadingApp(Path(directory) / "weekly")
            (app.workspace.inputs / "note.md").write_text("Notes.", encoding="utf-8")
            async with app.run_test(size=(100, 32)) as pilot:
                await pilot.pause()
                await pilot.click("#build")
                for _ in range(100):
                    await pilot.pause(0.05)
                    if not app.busy:
                        break
                self.assertEqual(app.workspace.state["stage"], "Approval required")
                self.assertFalse(app.query_one("#preview", Button).disabled)
                await pilot.click("#preview")
                await pilot.click("#approve")
                for _ in range(100):
                    await pilot.pause(0.05)
                    if not app.busy:
                        break
                self.assertEqual(app.workspace.state["stage"], "Exported")

    async def test_natural_language_and_expert_skills_share_the_workflow(self):
        with tempfile.TemporaryDirectory() as directory, patch("doc_harness.tui.Foundry", FakeFoundry):
            source = Path(directory) / "story.md"
            source.write_text("The complete story.", encoding="utf-8")
            app = ReadingApp(Path(directory) / "weekly")
            async with app.run_test(size=(110, 35)) as pilot:
                await pilot.pause()
                composer = app.query_one("#composer", Input)
                composer.value = f"/skill collect {source}"
                await pilot.press("enter")
                self.assertEqual(len(app.workspace.sources()), 1)
                composer.value = "make a PDF"
                await pilot.press("enter")
                for _ in range(100):
                    await pilot.pause(0.05)
                    if not app.busy:
                        break
                self.assertEqual(app.workspace.state["settings"]["format"], "pdf")
                self.assertEqual(app.query_one("#format-picker", Select).value, "pdf")
                self.assertEqual(app.workspace.state["stage"], "Approval required")
                composer.value = "/skill review approve"
                await pilot.press("enter")
                for _ in range(100):
                    await pilot.pause(0.05)
                    if not app.busy:
                        break
                self.assertEqual(app.workspace.state["stage"], "Exported")
                self.assertEqual(len(list(app.workspace.output.glob("*.pdf"))), 1)

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
