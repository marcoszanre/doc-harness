"""Custom full-screen raw terminal interface; never uses a cooked input prompt."""

from __future__ import annotations

import asyncio
import difflib
import re
from pathlib import Path
from threading import Event
from urllib.parse import urlsplit

from azure.core.exceptions import AzureError
from openai import OpenAIError
from rich.markdown import Markdown as RichMarkdown
from rich.text import Text
from rich.theme import Theme
from textual import events, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.suggester import Suggester
from textual.widgets import Button, Collapsible, Input, ProgressBar, Select, Static

from .chat import chat
from .clipboard import read_clipboard_text
from .exporters import export
from .foundry import Completion, Foundry
from .input_parser import extract_sources, only_sources
from .skills import SKILLS, read_skill
from .sources import web_search
from .workflow import build, revise
from .workspace import INPUT_SUFFIXES, Workspace

HELP = (
    "1. Paste one or several local file paths or public URLs and press Enter.\n"
    "   Separate sources with semicolons, or paste them on separate lines.\n"
    "2. Choose a format. Use BUILD -> PREVIEW -> EXPORT.\n"
    "You can also say 'make a PDF', 'use folder C:\\my-reading', or 'change the summary ...'.\n"
    "Type / for autocomplete, or /skills for expert shortcuts. /commands lists every command."
)
ADVANCED_HELP = (
    "/new PATH  /open PATH  /add PATH_OR_URL\n"
    "/search QUERY  /pick N  /remove N  /format markdown|pdf|docx\n"
    "/words N  /limit KB|off  /build  /refresh  /preview  /revise FEEDBACK\n"
    "/approve  /reject  /todos  /todo TITLE  /done N\n"
    "/skill collect|compose|review [argument]  /skills\n"
    "/status  /restart  /cancel (Ctrl+X)  /quit (Ctrl+Q)\n"
    "Any other message goes to the chat assistant. The composer locks while generating."
)


class ComposerSuggester(Suggester):
    COMMANDS = (
        "/add ", "/build", "/preview", "/approve", "/format pdf",
        "/format docx", "/format markdown", "/help", "/search ", "/pick ",
        "/refresh", "/revise ", "/new ", "/open ", "/remove ", "/words ",
        "/limit ", "/todo ", "/todos", "/done ", "/skills", "/skill collect ",
        "/skill compose pdf", "/skill review ", "/commands", "/status", "/restart", "/quit",
    )

    def __init__(self) -> None:
        super().__init__(use_cache=False, case_sensitive=True)

    async def get_suggestion(self, value: str) -> str | None:
        if not value:
            return None
        if ";" in value or "\n" in value or re.search(r"\shttps?://", value):
            return None
        for prefix in ("/add ", "/add-file ", "/new ", "/open ", "/skill collect "):
            if value.lower().startswith(prefix) and value[len(prefix):]:
                return await asyncio.to_thread(self._path_suggestion, value, len(prefix))
        if value.startswith("/"):
            for command in self.COMMANDS:
                if command.lower().startswith(value.lower()) and command != value:
                    return value + command[len(value):]
            return None
        if re.match(r'^[\'"]?(?:[A-Za-z]:[\\/]|[~.][\\/]|\\\\)', value):
            return await asyncio.to_thread(self._path_suggestion, value, 0)
        return None

    @staticmethod
    def _path_suggestion(value: str, offset: int) -> str | None:
        raw = value[offset:]
        quote = raw[0] if raw[:1] in {"'", '"'} else ""
        path_text = raw[1:] if quote else raw
        if not path_text or (quote and path_text.endswith(quote)):
            return None
        candidate = Path(path_text).expanduser()
        directory = candidate if path_text.endswith(("\\", "/")) else candidate.parent
        prefix = "" if path_text.endswith(("\\", "/")) else candidate.name
        if not directory.is_dir():
            return None
        if candidate.is_dir() and prefix and candidate.name.casefold() == prefix.casefold():
            return value + "\\"
        try:
            for path in sorted(directory.iterdir(), key=lambda item: item.name.casefold()):
                if path.name.casefold().startswith(prefix.casefold()) and path.name != prefix:
                    suffix = path.name[len(prefix):]
                    return value + suffix + ("\\" if path.is_dir() else quote)
        except OSError:
            return None
        return None


class ComposerInput(Input):
    BINDINGS = [Binding("tab", "cursor_right", "Accept completion", show=False)]

    def on_mouse_down(self, event: events.MouseDown) -> None:
        if event.button != 3:
            return
        event.prevent_default()
        event.stop()
        try:
            text = read_clipboard_text()
        except (OSError, RuntimeError, ValueError) as error:
            self.app.notify(str(error), severity="warning")
            return
        self.focus()
        self.post_message(events.Paste(text))

    def _on_paste(self, event: events.Paste) -> None:
        lines = [line.strip() for line in event.text.splitlines() if line.strip()]
        if lines:
            text = "; ".join(lines) if len(lines) > 1 else event.text.splitlines()[0]
            if self.selection.is_empty:
                self.insert_text_at_cursor(text)
            else:
                self.replace(text, *self.selection)
        event.prevent_default()
        event.stop()


class ReadingApp(App):
    TITLE = "Doc Harness"
    CSS = """
    Screen { background: #101114; color: #d1d6df; }
    #body { height: 1fr; min-height: 0; }
    #settings { height: 1; padding: 0 2; background: #191c22; color: #bec6d0; }
    #workspace-path { height: 1; padding: 0 2; background: #14161b; color: #9eabbc; }
    #progress { height: 1; display: none; }
    #timeline { height: 1fr; background: #101114; scrollbar-size: 1 1; }
    #thread { width: 100%; height: auto; padding: 1 3; }
    #workspace-details { height: auto; max-height: 12; overflow-y: auto; background: #171a1f; color: #b9c2d1; }
    #sources, #tasks { height: auto; padding: 0 2; }
    .role { height: auto; color: #aab5c3; text-style: bold; margin: 1 0 0 0; }
    .role-user { color: #adbbe2; }
    .message { height: auto; padding: 0 1; margin: 0 0 1 0; color: #d6dae2; }
    .message-user { background: #191d24; padding: 1 2; }
    .event { height: auto; padding: 0 1; margin: 0 0 1 0; color: #aeb7c5; }
    .event-error { color: #d99c98; }
    .event-done { color: #a9c4ad; }
    .model-notes { height: auto; margin: 0 0 1 0; background: #181a20; color: #abb4c2; }
    .model-notes Static { height: auto; max-height: 18; overflow-y: auto; padding: 0 1; }
    #workspace-choice { height: 3; padding: 0 2; background: #14161b; }
    #workspace-choice Button { width: 20; margin-right: 1; background: #252c38; color: #d2d8e1; border: none; }
    #actions { height: 3; padding: 0 2; background: #14161b; }
    #actions Button { width: 11; margin-right: 1; background: #252b34; color: #c8d1dc; border: none; }
    #actions Button:focus { background: #3b4b64; }
    #format-picker { width: 16; margin-right: 1; }
    #composer-row { height: 3; padding: 0 2; background: #14161b; }
    #composer { width: 100%; background: #21252d; border: solid #4c5766; color: #f0f2f5; }
    #stop { color: #dab0ab; }
    #footer-row { height: 1; background: #14161b; }
    #hint { width: 1fr; padding: 0 2; color: #939eae; }
    #usage { width: auto; padding: 0 2; color: #b1c3d8; }
    """
    BINDINGS = [
        Binding("ctrl+x", "interrupt", "Stop", priority=True),
        Binding("ctrl+r", "restart", "Restart", priority=True),
        Binding("ctrl+q", "quit", "Quit", priority=True),
        Binding("f1", "help", "Help"),
    ]

    def __init__(self, root: Path | None, suggested_root: Path | None = None) -> None:
        super().__init__()
        self.suggested_root = suggested_root or Path.home() / "doc-harness-workspaces" / "weekly"
        self.workspace = Workspace.create(root) if root is not None else None
        self.choosing_workspace = root is None
        self.awaiting_folder_path = False
        self.pending_imports: list[str] = []
        self.busy = False
        self.cancel = Event()
        self.suggestions: list[dict] = []
        self.reasoning = ""
        self.answer = ""
        self.active_kind = ""
        self._live_answer: Static | None = None
        self._model_notes: Static | None = None
        self._notes_panel: Collapsible | None = None
        self._render_pending = False
        self._last_sources: tuple = ()

    def compose(self) -> ComposeResult:
        with Vertical(id="body"):
            yield Static(id="settings")
            yield Static(id="workspace-path")
            with Collapsible(title="View sources and tasks", collapsed=True, id="workspace-details"):
                yield Static(id="sources")
                yield Static(id="tasks")
            yield ProgressBar(total=4, show_eta=False, id="progress")
            with VerticalScroll(id="timeline"):
                yield Vertical(id="thread")
            with Horizontal(id="workspace-choice"):
                yield Button("Use weekly folder", id="use-suggested")
                yield Button("Choose a folder", id="new-folder")
            with Horizontal(id="actions"):
                yield Select(
                    [("Markdown", "markdown"), ("PDF", "pdf"), ("Word", "docx")],
                    value=self.workspace.state["settings"]["format"] if self.workspace else "markdown",
                    allow_blank=False,
                    id="format-picker",
                )
                yield Button("Build", id="build")
                yield Button("Preview", id="preview", disabled=True)
                yield Button("Export", id="approve", disabled=True)
                yield Button("Stop", id="stop", disabled=True)
            with Horizontal(id="composer-row"):
                yield ComposerInput(
                    placeholder="Ask a question, or paste one or more file paths / URLs...",
                    suggester=ComposerSuggester(),
                    id="composer",
                )
            with Horizontal(id="footer-row"):
                yield Static("Enter send  |  Tab complete  |  Ctrl+R restart  |  Ctrl+X stop  |  F1 help", id="hint")
                yield Static(id="usage")

    def on_mount(self) -> None:
        self.console.push_theme(Theme({
            "markdown.link": "#a9bed8",
            "markdown.link_url": "underline #a9bed8",
        }))
        self.refresh_panels()
        self._guide()
        self.query_one("#composer", Input).focus()
        self.set_interval(2.0, self._sync_folder_view)

    def _source_signature(self) -> tuple:
        if self.workspace is None:
            return ()
        try:
            return tuple(
                (item["kind"], item["label"],
                 item["path"].stat().st_mtime_ns if item["kind"] == "file" else item["url"])
                for item in self.workspace.sources()
            )
        except FileNotFoundError:
            return ()

    def _sync_folder_view(self) -> None:
        if self.workspace is not None and not self.busy and self._source_signature() != self._last_sources:
            self.refresh_panels()
            self._log("SYSTEM", "Sources changed in the working folder; the list is up to date.")

    def _require_workspace(self) -> Workspace:
        if self.workspace is None:
            raise ValueError("Choose a working folder before adding sources or building.")
        return self.workspace

    def _select_workspace(self, folder: Path | str, create: bool = True) -> None:
        target = Path(folder).expanduser().resolve()
        existed = (target / ".doc-harness.json").is_file()
        self.workspace = Workspace.create(folder) if create else Workspace(folder)
        self.choosing_workspace = False
        self.awaiting_folder_path = False
        self.refresh_panels()
        self._chat_log(
            "Assistant",
            f"{'Opened' if existed else 'Created'} working folder: `{self.workspace.root}`.\n\n"
            f"`inputs/` holds your local sources; `output/` holds the final document.\n\n"
            f"{self._source_status()}",
        )
        if self.pending_imports:
            pending = self.pending_imports
            self.pending_imports = []
            self._add_sources(pending)

    def _source_status(self) -> str:
        if self.workspace is None:
            return "No working folder is selected yet. Choose one to see its sources."
        sources = self.workspace.sources()
        if not sources:
            return "There are no sources in this workspace yet. Paste a file path or public URL to add one."
        entries = [
            f"{number}. **{'Local file' if item['kind'] == 'file' else 'Web link'}:** "
            f"{item['label']}"
            for number, item in enumerate(sources, 1)
        ]
        return f"**{len(sources)} sources configured** in `{self.workspace.root.name}`:\n\n" + "\n".join(entries)

    def _guide(self) -> None:
        if self.workspace is None:
            existing = self.suggested_root / ".doc-harness.json"
            if existing.is_file():
                try:
                    count = len(Workspace(self.suggested_root).sources())
                    message = (
                        f"I found an existing working folder at `{self.suggested_root}` "
                        f"with **{count} source(s)**. Select **Use weekly folder** to continue, "
                        "or **Choose a folder** to work elsewhere."
                    )
                except (ValueError, OSError) as error:
                    message = (
                        f"The suggested folder at `{self.suggested_root}` cannot be opened: {error}. "
                        "Select **Choose a folder** and provide another location."
                    )
            else:
                message = (
                    f"Where should I keep your reading collection? "
                    f"Select **Use weekly folder** for `{self.suggested_root}`, "
                    "or **Choose a folder** and paste a directory path. "
                    "I won't create one until you decide."
                )
            self._chat_log("Assistant", message)
            return
        count = len(self.workspace.sources())
        if self.workspace.state["stage"] == "Exported":
            message = (
                f"Done. Your complete collection is at {self.workspace.state.get('last_output')}. "
                "Paste another source whenever you want to start a new edition."
            )
        elif not count:
            message = (
                f"Let's start. I created a working folder named **{self.workspace.root.name}**. "
                "Paste a file path or public article URL to add your first source. "
                "Prefer a different folder? Say `use folder C:\\path\\to\\my-reading`."
            )
        elif self.workspace.state.get("pending"):
            message = (
                f"I have a draft with all {count} source texts. Select PREVIEW to read it, "
                "then EXPORT to create one file. Say 'change the summary ...' if you want a revision."
            )
        else:
            message = (
                f"Your workspace has {count} source(s). Paste another file or link, "
                "or say 'make a PDF', 'make a Word document', or 'create the collection'."
            )
        self._chat_log("GUIDE", message)

    def _add_source(self, raw: str, announce: bool = True) -> bool:
        workspace = self._require_workspace()
        item = raw.strip().strip('"').strip("'")
        parsed = urlsplit(item)
        if parsed.scheme in {"http", "https"} and parsed.netloc:
            if item in workspace.state["sources"]:
                if announce:
                    self._chat_log("Assistant", "That link is already in your workspace.")
                return False
            workspace.add_url(item)
            description = "link"
        elif (
            re.match(r"^(?:[A-Za-z]:[\\/]|[~.][\\/]|\\\\)", item)
            or Path(item).is_file()
        ):
            existing = any(
                source["kind"] == "file" and source["label"] == Path(item).name
                for source in workspace.sources()
            )
            try:
                workspace.add_file(item)
            except FileNotFoundError as error:
                path = Path(item).expanduser()
                try:
                    neighbors = [
                        child.name for child in path.parent.iterdir()
                        if child.is_file() and child.suffix.lower() == path.suffix.lower()
                    ] if path.parent.is_dir() else []
                except OSError:
                    neighbors = []
                similar = difflib.get_close_matches(path.name, neighbors, n=3, cutoff=0.55)
                hint = f" Did you mean: {', '.join(similar)}?" if similar else ""
                raise ValueError(f"File not found: {path}.{hint}") from error
            if existing:
                if announce:
                    self._chat_log("Assistant", f"`{Path(item).name}` is already in your workspace.")
                return False
            description = "file"
        else:
            raise ValueError("Paste a local .pdf/.docx/.md/.txt/.html file path or a public http(s) URL.")
        if announce:
            label = Path(item).name if description == "file" else item
            self._chat_log(
                "Assistant", f"Added **{label}**. {len(workspace.sources())} source(s) ready. "
                "Add another, or press **Build** when ready.",
            )
        return True

    def _add_sources(self, sources: list[str]) -> None:
        if not sources:
            raise ValueError("No file paths or public URLs were found in that message.")
        added = 0
        errors: list[str] = []
        for source in sources:
            try:
                added += self._add_source(source, announce=False)
            except (ValueError, OSError) as error:
                errors.append(str(error))
        if added:
            message = f"Added **{added} of {len(sources)}** source(s). "
            message += f"{len(self._require_workspace().sources())} total in this folder."
            if errors:
                message += f" **{len(errors)} failed**; see the error below."
            self._chat_log("Assistant", message)
        elif not errors:
            self._chat_log("Assistant", "Those sources are already in this workspace.")
        for error in errors:
            self._log("ERROR", error)

    def _scroll_if_at_end(self) -> None:
        timeline = self.query_one("#timeline", VerticalScroll)
        if timeline.is_vertical_scroll_end or timeline.max_scroll_y == 0:
            timeline.anchor()

    def _log(self, label: str, message: str) -> None:
        style = {
            "ERROR": "#d99c98", "STEP": "#aab4c2",
            "SYSTEM": "#b8c6d7", "DONE": "#a9c4ad",
        }.get(label, "#aab4c2")
        marker = "!" if label == "ERROR" else "-" if label == "STEP" else "+"
        self._scroll_if_at_end()
        self.query_one("#thread", Vertical).mount(
            Static(Text(f"{marker} {message}", style=style),
                   classes="event" + (" event-error" if label == "ERROR" else " event-done" if label == "DONE" else "")),
        )

    def _chat_log(self, label: str, message: str) -> Static:
        user = label == "YOU"
        body = Static(Text(message) if user else RichMarkdown(message),
                      classes="message" + (" message-user" if user else ""))
        self._scroll_if_at_end()
        self.query_one("#thread", Vertical).mount(
            Static(Text("You" if user else label.title()), classes="role" + (" role-user" if user else "")),
            body,
        )
        return body

    def refresh_panels(self) -> None:
        workspace = self.workspace
        if workspace is None:
            self._refresh_usage()
            self.query_one("#settings", Static).update(Text("doc harness   /   choose a working folder", style="#b9c7d7"))
            self.query_one("#workspace-path", Static).update(Text(
                f"Suggested folder: {self.suggested_root}", style="#aab8c7"
            ))
            self.query_one("#sources", Static).update(Text("No folder selected."))
            self.query_one("#tasks", Static).update(Text("No folder selected."))
            self.query_one("#workspace-details", Collapsible).title = "Sources — choose a working folder"
            self.query_one("#workspace-choice", Horizontal).display = True
            self.query_one("#actions", Horizontal).display = False
            return
        self.query_one("#workspace-choice", Horizontal).display = False
        self.query_one("#actions", Horizontal).display = True
        self._refresh_usage()
        sources = workspace.sources()
        self._last_sources = self._source_signature()
        source_lines = [f"{n}. {'File' if item['kind'] == 'file' else 'Link'}: {item['label']}"
                        for n, item in enumerate(sources, 1)]
        self.query_one("#sources", Static).update(Text(
            "Full source list\n" + ("\n".join(source_lines) if source_lines else "No sources yet.")
        ))
        self.query_one("#workspace-details", Collapsible).title = (
            f"Sources ({len(sources)})  |  Tasks ({len(workspace.state['todos'])})  —  click to expand"
        )
        settings = workspace.state["settings"]
        title = Text("doc harness", style="bold #bfc7d6")
        title.append(
            f"   {settings['format'].upper()}  /  {workspace.state['stage']}",
            style="#b2bdcc",
        )
        self.query_one("#settings", Static).update(title)
        self.query_one("#workspace-path", Static).update(Text(
            f"Working folder: {workspace.root}", style="#aab8c7"
        ))
        picker = self.query_one("#format-picker", Select)
        if picker.value != settings["format"]:
            picker.value = settings["format"]
        todos = workspace.state["todos"]
        self.query_one("#tasks", Static).update(Text(
            "Tasks\n" + ("\n".join(
                f"{i}. {'[x]' if task['done'] else '[ ]'} {task['title']}" for i, task in enumerate(todos, 1)
            ) if todos else "No tasks yet.")
        ))
        self.query_one("#build", Button).disabled = self.busy
        self.query_one("#preview", Button).disabled = self.busy or not workspace.state.get("pending")
        pending = workspace.state.get("pending")
        self.query_one("#approve", Button).disabled = (
            self.busy or not pending or bool(pending["review"]["issues"])
        )
        picker.disabled = self.busy

    def _refresh_usage(self) -> None:
        totals = self.workspace.state["usage"] if self.workspace else None
        if totals and totals["requests"] > totals["unreported"]:
            label = f"In {totals['input']:,}  Out {totals['output']:,}"
            if totals["unreported"]:
                label += f"  ({totals['unreported']} unavailable)"
        elif totals and totals["unreported"]:
            label = f"In --  Out --  ({totals['unreported']} unavailable)"
        else:
            label = "In --  Out --  (next request)"
        self.query_one("#usage", Static).update(Text(label))

    def _record_usage(self, result: Completion) -> None:
        workspace = self._require_workspace()
        totals = workspace.state["usage"]
        totals["requests"] += 1
        if result.input_tokens is None or result.output_tokens is None:
            totals["unreported"] += 1
        else:
            totals["input"] += result.input_tokens
            totals["output"] += result.output_tokens
        workspace.save()
        self._refresh_usage()

    def _event(self, kind: str, text: str) -> None:
        if kind == "reasoning":
            self.reasoning = (self.reasoning + text)[-6000:]
            if self._model_notes is None:
                self._model_notes = Static(Text(self.reasoning))
                self._notes_panel = Collapsible(
                    self._model_notes, title="Model signal (unverified)", collapsed=True,
                    classes="model-notes",
                )
                self.query_one("#thread", Vertical).mount(self._notes_panel)
            self._model_notes.update(Text(self.reasoning))
        elif kind == "answer":
            self.answer += text
            if self._live_answer and not self._render_pending:
                self._render_pending = True
                self.set_timer(0.05, self._flush_answer)
        else:
            if text.startswith("Writing and reviewing introduction"):
                self.answer = ""
                if self._live_answer:
                    self._live_answer.update(RichMarkdown("_Writing the edition summary..._"))
            self._log("ERROR" if kind == "error" else "STEP", text)
            progress = self.query_one("#progress", ProgressBar)
            if "Indexing" in text:
                progress.update(progress=1)
            elif "Writing" in text:
                progress.update(progress=2)
            elif "Quality gate" in text:
                progress.update(progress=3)

    def _flush_answer(self) -> None:
        self._render_pending = False
        if self._live_answer and self.answer:
            self._scroll_if_at_end()
            self._live_answer.update(RichMarkdown(self.answer))

    def _start(self, kind: str, payload: str = "") -> None:
        self._require_workspace()
        if self.busy:
            self._log("SYSTEM", "Finish or interrupt the active operation first.")
            return
        self.busy = True
        self.active_kind = kind
        self.cancel = Event()
        self.reasoning = ""
        self.answer = ""
        self._render_pending = False
        self._model_notes = None
        self._notes_panel = None
        self._live_answer = (
            self._chat_log("Assistant", "_Working..._")
            if kind in {"build", "refresh", "chat", "revise"} else None
        )
        self.query_one("#composer", Input).disabled = True
        self.query_one("#stop", Button).disabled = False
        progress = self.query_one("#progress", ProgressBar)
        progress.display = kind in {"build", "refresh", "export"}
        progress.update(progress=0)
        self.refresh_panels()
        self._run_operation(kind, payload)

    def _finished(self, message: str, failed: bool = False) -> None:
        self.busy = False
        self._flush_answer()
        self.query_one("#composer", Input).disabled = False
        self.query_one("#stop", Button).disabled = True
        self.query_one("#composer", Input).focus()
        self.query_one("#progress", ProgressBar).display = False
        if self._live_answer and not self.answer:
            self._live_answer.update(RichMarkdown("_No model response._" if failed else "_Completed._"))
        self._log("ERROR" if failed else "DONE", message)
        self.refresh_panels()
        if not failed and self.active_kind in {"build", "refresh", "export"}:
            self._guide()

    @work(thread=True, exit_on_error=False)
    def _run_operation(self, kind: str, payload: str) -> None:
        model = None
        try:
            if kind in {"build", "refresh", "chat", "revise"}:
                model = Foundry()
                model.on_usage = lambda result: self.call_from_thread(self._record_usage, result)
            emit = lambda category, text: self.call_from_thread(self._event, category, text)
            if kind in {"build", "refresh"}:
                result = build(self.workspace, model, emit, self.cancel, refresh=kind == "refresh")
                summary = f"Full-text collection ready: {result.word_count}-word edition summary. "
                summary += f"{len(result.issues)} blocker(s); {len(result.warnings)} warning(s). "
                summary += "Select PREVIEW, then EXPORT; or ask to change the summary."
                if result.issues or result.warnings:
                    for item in result.issues + result.warnings:
                        emit("error", item)
            elif kind == "chat":
                answer = chat(self.workspace, model, payload, emit, self.cancel)
                summary = f"Assistant finished ({len(answer.split())} words)."
            elif kind == "revise":
                result = revise(self.workspace, model, payload, emit, self.cancel)
                summary = f"Summary revision ready: {result.word_count} words, {len(result.issues)} blocker(s), {len(result.warnings)} warning(s)."
                for item in result.issues + result.warnings:
                    emit("error", item)
            elif kind == "search":
                self.suggestions = web_search(payload)
                for n, suggestion in enumerate(self.suggestions, 1):
                    emit("step", f"{n}. {suggestion['title']} — {suggestion['url']}")
                self.call_from_thread(
                    self._chat_log, "GUIDE",
                    "Here are the results:\n"
                    + "\n".join(f"{n}. {s['title']} — {s['url']}" for n, s in enumerate(self.suggestions, 1))
                    + "\nSay 'add result 1' to include a link.",
                )
                summary = "Pick an article by saying 'add result 1'."
            else:
                result = export(self.workspace)
                summary = f"Reading list exported: {result}"
                self.call_from_thread(self.query_one("#progress", ProgressBar).update, progress=4)
            self.call_from_thread(self._finished, summary)
        except (ValueError, OSError, RuntimeError, InterruptedError, OpenAIError, AzureError) as error:
            self.workspace.state["stage"] = "Interrupted" if isinstance(error, InterruptedError) else "Error"
            self.workspace.save()
            self.call_from_thread(self._finished, str(error), True)
        finally:
            if model:
                model.close()

    def action_interrupt(self) -> None:
        if self.busy:
            self.cancel.set()
            self._log("SYSTEM", "Stop requested; waiting for the current network operation to yield.")

    def action_restart(self) -> None:
        if self.busy:
            self._log("ERROR", "Stop the current operation before restarting.")
            return
        self.exit(result="restart")

    def action_help(self) -> None:
        self._chat_log("COMMANDS", HELP)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        try:
            if event.button.id == "use-suggested":
                self._select_workspace(self.suggested_root)
            elif event.button.id == "new-folder":
                self.awaiting_folder_path = True
                self._chat_log("Assistant", "Paste the full path to the folder you want to use. "
                               "I will create it if it does not exist.")
                self.query_one("#composer", Input).focus()
            elif event.button.id == "build":
                self._start("build")
            elif event.button.id == "preview":
                self._command("/preview", "")
            elif event.button.id == "approve":
                self._start("export")
            elif event.button.id == "stop":
                self.action_interrupt()
        except (ValueError, OSError, RuntimeError) as error:
            self._log("ERROR", str(error))
        self.refresh_panels()

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id != "format-picker" or event.value not in {"markdown", "pdf", "docx"}:
            return
        if self.workspace is None:
            return
        if event.value != self.workspace.state["settings"]["format"]:
            self.workspace.set_format(event.value)
            self._chat_log("GUIDE", f"Output selected: {event.value.upper()}. The source texts will stay complete.")
            self.refresh_panels()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        event.input.value = ""
        if not text or self.busy:
            return
        self.query_one("#timeline", VerticalScroll).anchor()
        candidates = extract_sources(text)
        shown = (
            "Add these sources:\n" + "\n".join(f"  {number}. {source}" for number, source in enumerate(candidates, 1))
            if len(candidates) > 1 and only_sources(text, candidates) else text
        )
        self._chat_log("YOU", shown)
        try:
            if self.workspace is None:
                self._handle_workspace_input(text)
                self.refresh_panels()
                return
            if (text.startswith("/") and not only_sources(text, extract_sources(text))
                    and not Path(text.strip('"').strip("'")).is_file()):
                command, _, argument = text.partition(" ")
                self._command(command.lower(), argument.strip().strip('"').strip("'"))
            else:
                self._handle_text(text)
        except (ValueError, OSError, RuntimeError) as error:
            self._log("ERROR", str(error))
        self.refresh_panels()

    @staticmethod
    def _plain_local_file(text: str) -> bool:
        if len(text) > 240 or any(character in text for character in ('"', "'", ":")):
            return False
        return Path(text).suffix.lower() in INPUT_SUFFIXES and Path(text).is_file()

    def _handle_workspace_input(self, text: str) -> None:
        value = text.strip().strip('"').strip("'")
        lower = value.lower()
        if lower in {"continue", "use weekly", "use suggested", "usar semanal", "usar sugerida"}:
            self._select_workspace(self.suggested_root)
            return
        if lower in {"/help", "/?"}:
            self.action_help()
            return
        if lower in {"/quit", "/exit"}:
            self.exit()
            return
        if lower in {"/restart", "restart", "reiniciar"}:
            self.action_restart()
            return
        if lower.startswith(("/new ", "/open ")):
            command, _, folder = value.partition(" ")
            self._select_workspace(folder, create=command.lower() == "/new")
            return
        folder = re.match(
            r"^(?:use|create|open|switch to|usar|criar|abrir)(?: a| my| uma)? "
            r"(?:folder|workspace|pasta)\s+(.+)$",
            value, flags=re.I,
        )
        if folder:
            self._select_workspace(folder.group(1).strip().strip('"').strip("'"))
            return
        candidates = extract_sources(value)
        if candidates and (only_sources(value, candidates) or re.search(
            r"\b(?:add|include|import|adicionar|incluir|adicione|inclua|"
            r"tbm|tambem|também|also)\b", lower,
        )):
            self.pending_imports.extend(
                candidate for candidate in candidates if candidate not in self.pending_imports
            )
            self._chat_log(
                "Assistant", f"I have **{len(self.pending_imports)} source(s)** ready. "
                "Choose a working folder first; I will add them there.",
            )
            return
        if self.awaiting_folder_path or re.match(r"^(?:[A-Z]:[\\/]|[~.][\\/]|\\\\)", value, re.I):
            self._select_workspace(value)
            return
        self._guide()

    def _handle_text(self, text: str) -> None:
        value = text.strip().strip('"').strip("'")
        lower = value.lower()
        candidates = extract_sources(value)
        if candidates and (only_sources(value, candidates) or re.search(
            r"\b(?:add|include|import|adicionar|incluir|adicione|inclua|"
            r"tbm|tambem|também|also)\b",
            lower,
        )):
            self._add_sources(candidates)
            return
        if self._plain_local_file(value):
            self._add_sources([value])
            return
        attachment = re.match(
            r"^(?:please )?(?:add|include|import|adicionar|incluir)(?: this| esse| esta| o| a)?"
            r"(?: file| article| link| pdf| url| arquivo| artigo)?\s+(.+)$",
            value, flags=re.I,
        )
        if attachment:
            candidate = attachment.group(1).strip().strip('"').strip("'")
            if urlsplit(candidate).scheme in {"http", "https"} or re.match(r"^[A-Za-z]:[\\/]", candidate):
                self._add_sources(extract_sources(candidate))
                return
        folder = re.match(
            r"^(?:use|create|open|switch to|usar|criar|abrir)(?: a| my| uma)? "
            r"(?:folder|workspace|pasta)\s+(.+)$", value, flags=re.I,
        )
        if folder:
            self._select_workspace(folder.group(1).strip().strip('"').strip("'"))
            return
        if lower in {"start", "let's start", "lets start", "help", "begin", "comecar", "começar", "bora iniciar", "oi"}:
            self._guide()
            return
        if lower in {"restart", "reiniciar", "recomeçar"}:
            self.action_restart()
            return
        result = re.match(r"^(?:add|include|pick|adicionar|incluir) (?:result|resultado) (\d+)$", lower)
        if result:
            self._command("/pick", result.group(1))
            return
        if lower in {"show skills", "list skills", "mostrar skills"}:
            self._command("/skills", "")
            return
        if lower in {"sources", "fontes", "files", "arquivos"} or (
            re.search(r"\b(?:sources?|fontes?|arquivos?|files?|links?)\b", lower)
            and re.search(
                r"\b(?:quais|qual|which|what|list|liste|listar|show|mostrar|"
                r"configured|configurad\w*|adicionad\w*|have|tenho)\b",
                lower,
            )
        ):
            self._chat_log("Assistant", self._source_status())
            return
        skill = re.match(r"^(?:use|usar)\s+skill\s+(.+)$", value, flags=re.I)
        if skill:
            self._run_skill(skill.group(1))
            return
        search = re.match(r"^(?:find|search for|search|buscar|pesquisar)(?: articles| links| artigos)?(?: about| sobre)? (.+)$", value, flags=re.I)
        if search:
            self._start("search", search.group(1))
            return
        if re.search(r"\b(?:pdf|word|docx|markdown)\b", lower) and re.search(
            r"\b(?:make|create|prepare|compile|generate|export|quero|criar|gerar|fazer|exportar)\b", lower
        ):
            fmt = "pdf" if "pdf" in lower else "docx" if "word" in lower or "docx" in lower else "markdown"
            if fmt != self.workspace.state["settings"]["format"]:
                self.workspace.set_format(fmt)
                self._chat_log("GUIDE", f"Selected {fmt.upper()}. I'll prepare a draft for your approval first.")
            if self.workspace.state.get("pending") and re.search(r"\b(?:export|save|exportar|salvar)\b", lower):
                self._start("export")
            elif self.workspace.sources():
                self._start("build")
            else:
                self._guide()
            return
        if re.search(r"\b(?:build|compile|prepare|generate|compilar|gerar|preparar)\b", lower) and self.workspace.sources():
            self._start("build")
            return
        if lower in {"preview", "show draft", "read draft", "visualizar", "mostrar rascunho"}:
            self._command("/preview", "")
            return
        if lower in {"approve", "export", "save", "aprovar", "exportar", "salvar"}:
            if self.workspace.state.get("pending"):
                self._start("export")
            else:
                self._guide()
            return
        change = re.match(r"^(?:change|revise|edit|alterar|revisar)(?: the| o| a)? (?:summary|resumo)\s+(.+)$", value, flags=re.I)
        if change and self.workspace.state.get("pending"):
            self._start("revise", change.group(1))
            return
        self._start("chat", text)

    def _run_skill(self, request: str) -> None:
        raw_name, _, argument = request.strip().partition(" ")
        name = raw_name.lower()
        if name not in SKILLS:
            raise ValueError(f"Available skills: {', '.join(SKILLS)}. Try /skill collect PATH.")
        if name == "collect" and argument:
            self._add_sources(extract_sources(argument))
        elif name == "compose" and argument.lower() in {"markdown", "pdf", "docx"}:
            self.workspace.set_format(argument.lower())
            self._start("build") if self.workspace.sources() else self._guide()
        elif name == "review" and argument in {"approve", "export"}:
            self._command("/approve", "")
        elif name == "review" and argument and argument != "preview":
            self._start("revise", argument)
        elif name == "review" and argument == "preview":
            self._command("/preview", "")
        else:
            self._chat_log(f"SKILL {name}", read_skill(name))

    def _command(self, command: str, argument: str) -> None:
        workspace = self.workspace
        if command in {"/help", "/?"}:
            self.action_help()
        elif command == "/commands":
            self._chat_log("ADVANCED COMMANDS", ADVANCED_HELP)
        elif command in {"/quit", "/exit"}:
            self.exit()
        elif command == "/restart":
            self.action_restart()
        elif command == "/new":
            if not argument:
                raise ValueError("Usage: /new PATH")
            self._select_workspace(Path(argument))
            self.suggestions = []
        elif command == "/open":
            self._select_workspace(Path(argument), create=False)
            self.suggestions = []
        elif command in {"/add", "/add-file", "/add-url"}:
            candidates = extract_sources(argument)
            if not candidates:
                raise ValueError("Provide a local file path or public URL to add.")
            self._add_sources(candidates)
        elif command == "/remove":
            self._log("SYSTEM", f"Removed: {self._require_workspace().remove_source(int(argument))}")
        elif command == "/search":
            self._start("search", argument)
        elif command == "/pick":
            index = int(argument)
            if not 1 <= index <= len(self.suggestions):
                raise ValueError("Search result number is out of range.")
            workspace.add_url(self.suggestions[index - 1]["url"])
            self._log("SYSTEM", f"Approved link: {self.suggestions[index - 1]['url']}")
        elif command == "/format":
            workspace.set_format(argument.lower())
        elif command == "/words":
            workspace.set_target_words(int(argument))
        elif command == "/limit":
            workspace.set_max_file_kb(None if argument.lower() == "off" else int(argument))
        elif command in {"/build", "/refresh"}:
            self._start(command[1:])
        elif command == "/preview":
            pending = workspace.state.get("pending")
            if not pending:
                raise ValueError("No draft. Use /build first.")
            draft = (workspace.cache / "draft.md").read_text(encoding="utf-8")
            self._chat_log("DRAFT (first 8,000 characters)", draft[:8000])
            self._log("SYSTEM", f"Full draft: {workspace.cache / 'draft.md'}")
        elif command == "/revise":
            self._start("revise", argument)
        elif command == "/approve":
            self._start("export")
        elif command == "/reject":
            workspace.invalidate()
            workspace.save()
            self._log("SYSTEM", "Draft rejected. Revise sources or settings and /build again.")
        elif command == "/todos":
            self._chat_log("TASKS", "\n".join(f"{n}. {t}" for n, t in enumerate(workspace.state["todos"], 1)) or "None")
        elif command == "/todo":
            workspace.add_todo(argument)
        elif command == "/done":
            workspace.set_todo(int(argument), True)
        elif command == "/skills":
            self._chat_log("SKILLS", "\n".join(f"{name}: {description}" for name, description in SKILLS.items()))
        elif command == "/skill":
            self._run_skill(argument)
        elif command == "/status":
            self._chat_log(
                "Assistant",
                self._source_status() + f"\n\nStage: {workspace.state['stage']}."
                f"\nWorkspace: `{workspace.root}`."
                f"\nLatest output: `{workspace.state.get('last_output', 'none')}`.",
            )
        elif command == "/cancel":
            self.action_interrupt()
        else:
            raise ValueError("Unknown command. Press F1 for help.")
