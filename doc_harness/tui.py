"""Custom full-screen raw terminal interface; never uses a cooked input prompt."""

from __future__ import annotations

from pathlib import Path
from threading import Event

from azure.core.exceptions import AzureError
from openai import OpenAIError
from rich.text import Text
from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, Footer, Header, Input, ProgressBar, RichLog, Static

from .chat import chat
from .exporters import export
from .foundry import Foundry
from .sources import web_search
from .workflow import build, revise
from .workspace import Workspace

HELP = (
    "/new PATH  /open PATH  /add-file PATH  /add-url URL\n"
    "/search QUERY  /pick N  /remove N  /format markdown|pdf|docx\n"
    "/words N  /limit KB|off  /build  /refresh  /preview  /revise FEEDBACK\n"
    "/approve  /reject  /todos  /todo TITLE  /done N\n"
    "/status  /cancel (Ctrl+X)  /quit (Ctrl+Q)\n"
    "Anything without a slash is a chat message. A busy operation locks the composer."
)


class ReadingApp(App):
    TITLE = "DOC HARNESS"
    SUB_TITLE = "From everything you read to one useful document"
    CSS = """
    Screen { background: #0a1122; color: #e5edff; }
    Header { background: #12294e; color: #f1f6ff; }
    Footer { background: #12294e; }
    #shell { height: 1fr; min-height: 0; overflow: hidden; }
    #workspace-panel { width: 34%; min-width: 30; height: 100%; border: round #3971bc; background: #101d35; padding: 1 2; }
    #main-panel { width: 1fr; height: 100%; padding: 0 1 3 1; overflow: hidden; }
    .label { color: #77aef8; text-style: bold; margin-top: 1; }
    .info { color: #e4eeff; }
    #sources { height: 1fr; overflow-y: auto; }
    #tasks { height: 9; overflow-y: auto; }
    #activity { height: 1fr; min-height: 4; border: round #3971bc; background: #101d35; padding: 0 1; }
    #thinking { height: 1fr; min-height: 4; border: round #725da8; background: #161b36; padding: 0 1; overflow-y: auto; }
    #live-answer { height: 1fr; min-height: 4; border: round #3971bc; background: #101d35; padding: 0 1; overflow-y: auto; }
    #conversation { height: 2fr; min-height: 5; border: round #3971bc; background: #101d35; padding: 0 1; }
    #composer-row { dock: bottom; height: 3; }
    #composer { width: 1fr; background: #182945; border: round #4d91ee; color: #ffffff; }
    #stop { width: 12; margin-left: 1; background: #8e3a55; color: #ffffff; }
    #progress { height: 1; margin: 1 0; }
    """
    BINDINGS = [
        Binding("ctrl+x", "interrupt", "Stop", priority=True),
        Binding("ctrl+q", "quit", "Quit", priority=True),
        Binding("f1", "help", "Help"),
    ]

    def __init__(self, root: Path) -> None:
        super().__init__()
        self.workspace = Workspace.create(root)
        self.busy = False
        self.cancel = Event()
        self.suggestions: list[dict] = []
        self.reasoning = ""
        self.answer = ""

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal(id="shell"):
            with Vertical(id="workspace-panel"):
                yield Static("WORKSPACE", classes="label")
                yield Static(id="location", classes="info")
                yield Static("INPUTS  /  SOURCES", classes="label")
                yield Static(id="sources")
                yield Static("OUTPUT  /  SETTINGS", classes="label")
                yield Static(id="settings", classes="info")
                yield Static("TASK MANAGER", classes="label")
                yield Static(id="tasks")
            with Vertical(id="main-panel"):
                yield Static("PROCESS  /  EVENTS", classes="label")
                yield ProgressBar(total=4, show_eta=False, id="progress")
                yield RichLog(highlight=False, markup=False, wrap=True, id="activity")
                yield Static("MODEL SIGNAL  /  UNVERIFIED REASONING", classes="label")
                yield Static("Waiting for a model response.", id="thinking")
                yield Static("LIVE RESPONSE", classes="label")
                yield Static("Waiting for model output.", id="live-answer")
                yield Static("CONVERSATION  /  DRAFT PREVIEW", classes="label")
                yield RichLog(highlight=False, markup=False, wrap=True, id="conversation")
                with Horizontal(id="composer-row"):
                    yield Input(placeholder="Type a message or /help for commands", id="composer")
                    yield Button("STOP", id="stop", disabled=True)
        yield Footer()

    def on_mount(self) -> None:
        self.refresh_panels()
        self._log("SYSTEM", "Workspace ready. Add a file or URL, choose a format, then /build.")
        self.query_one("#composer", Input).focus()

    def _log(self, label: str, message: str) -> None:
        self.query_one("#activity", RichLog).write(Text(f"{label:>9}  {message}", style={
            "ERROR": "bold red", "STEP": "cyan", "SYSTEM": "green", "DONE": "bold green",
        }.get(label, "white")))

    def _chat_log(self, label: str, message: str) -> None:
        self.query_one("#conversation", RichLog).write(Text(f"{label}\n{message}\n", style="white"))

    def refresh_panels(self) -> None:
        workspace = self.workspace
        self.query_one("#location", Static).update(Text(str(workspace.root)))
        sources = workspace.sources()
        source_lines = [f"{n:>2}. [{item['kind']}] {item['label']}" for n, item in enumerate(sources, 1)]
        self.query_one("#sources", Static).update(Text("\n".join(source_lines) if source_lines else "Drop files into inputs/ or use /add-url."))
        settings = workspace.state["settings"]
        self.query_one("#settings", Static).update(Text(
            f"Format: {settings['format'].upper()}\nSummary: ~{settings['target_words']} words"
            f"\nFile limit: {settings['max_file_kb'] or 'off'} KB\n"
            f"Output: {workspace.output}\nStage: {workspace.state['stage']}"
        ))
        todos = workspace.state["todos"]
        self.query_one("#tasks", Static).update(Text(
            "\n".join(f"{i}. {'[x]' if task['done'] else '[ ]'} {task['title']}" for i, task in enumerate(todos, 1))
            if todos else "No tasks yet. Use /todo TITLE."
        ))

    def _event(self, kind: str, text: str) -> None:
        if kind == "reasoning":
            self.reasoning = (self.reasoning + text)[-6000:]
            self.query_one("#thinking", Static).update(Text(self.reasoning))
        elif kind == "answer":
            self.answer = (self.answer + text)[-12000:]
            self.query_one("#live-answer", Static).update(Text(self.answer))
        else:
            self._log("ERROR" if kind == "error" else "STEP", text)
            progress = self.query_one("#progress", ProgressBar)
            if "Indexing" in text:
                progress.update(progress=1)
            elif "Writing" in text:
                progress.update(progress=2)
            elif "Quality gate" in text:
                progress.update(progress=3)

    def _start(self, kind: str, payload: str = "") -> None:
        if self.busy:
            self._log("SYSTEM", "Finish or interrupt the active operation first.")
            return
        self.busy = True
        self.cancel = Event()
        self.reasoning = ""
        self.answer = ""
        self.query_one("#thinking", Static).update("Waiting for model output...")
        self.query_one("#live-answer", Static).update("Waiting for model output...")
        self.query_one("#composer", Input).disabled = True
        self.query_one("#stop", Button).disabled = False
        self.query_one("#progress", ProgressBar).update(progress=0)
        self._run_operation(kind, payload)

    def _finished(self, message: str, failed: bool = False) -> None:
        self.busy = False
        self.query_one("#composer", Input).disabled = False
        self.query_one("#stop", Button).disabled = True
        self.query_one("#composer", Input).focus()
        if self.answer and not failed:
            self._chat_log("MODEL RESPONSE", self.answer[-8000:])
        self._log("ERROR" if failed else "DONE", message)
        self.refresh_panels()

    @work(thread=True, exit_on_error=False)
    def _run_operation(self, kind: str, payload: str) -> None:
        model = None
        try:
            if kind in {"build", "refresh", "chat", "revise"}:
                model = Foundry()
            emit = lambda category, text: self.call_from_thread(self._event, category, text)
            if kind in {"build", "refresh"}:
                result = build(self.workspace, model, emit, self.cancel, refresh=kind == "refresh")
                summary = f"Full-text collection ready: {result.word_count}-word edition summary. "
                summary += f"{len(result.issues)} blocker(s); {len(result.warnings)} warning(s). "
                summary += "Use /preview, /revise SUMMARY_FEEDBACK or /approve."
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
                summary = "Use /pick N to add a result to your reading list."
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

    def action_help(self) -> None:
        self._chat_log("COMMANDS", HELP)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "stop":
            self.action_interrupt()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        event.input.value = ""
        if not text or self.busy:
            return
        if not text.startswith("/"):
            self._chat_log("YOU", text)
            self._start("chat", text)
            return
        command, _, argument = text.partition(" ")
        argument = argument.strip().strip('"')
        try:
            self._command(command.lower(), argument)
        except (ValueError, OSError, RuntimeError) as error:
            self._log("ERROR", str(error))
        self.refresh_panels()

    def _command(self, command: str, argument: str) -> None:
        workspace = self.workspace
        if command in {"/help", "/?"}:
            self.action_help()
        elif command in {"/quit", "/exit"}:
            self.exit()
        elif command == "/new":
            if not argument:
                raise ValueError("Usage: /new PATH")
            self.workspace = Workspace.create(Path(argument))
            self.suggestions = []
            self._log("SYSTEM", f"Active workspace: {self.workspace.root}")
        elif command == "/open":
            self.workspace = Workspace(Path(argument))
            self.suggestions = []
            self._log("SYSTEM", f"Opened: {self.workspace.root}")
        elif command == "/add-file":
            self._log("SYSTEM", f"Copied input: {workspace.add_file(argument)}")
        elif command == "/add-url":
            workspace.add_url(argument)
            self._log("SYSTEM", "Added link; the direct HTTP fetch runs during /build.")
        elif command == "/remove":
            self._log("SYSTEM", f"Removed: {workspace.remove_source(int(argument))}")
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
        elif command == "/status":
            self._log("SYSTEM", f"Stage: {workspace.state['stage']} | Latest: {workspace.state.get('last_output', 'none')}")
        elif command == "/cancel":
            self.action_interrupt()
        else:
            raise ValueError("Unknown command. Press F1 for help.")
