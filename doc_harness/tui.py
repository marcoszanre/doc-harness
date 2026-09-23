"""Custom full-screen raw terminal interface; never uses a cooked input prompt."""

from __future__ import annotations

import asyncio
import re
from pathlib import Path
from threading import Event
from urllib.parse import urlsplit

from azure.core.exceptions import AzureError
from openai import OpenAIError
from rich.text import Text
from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.suggester import Suggester
from textual.widgets import Button, Footer, Header, Input, ProgressBar, RichLog, Select, Static

from .chat import chat
from .exporters import export
from .foundry import Foundry
from .skills import SKILLS, read_skill
from .sources import web_search
from .workflow import build, revise
from .workspace import INPUT_SUFFIXES, Workspace

HELP = (
    "1. Paste a local file path or public URL and press Enter.\n"
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
    "/status  /cancel (Ctrl+X)  /quit (Ctrl+Q)\n"
    "Any other message goes to the chat assistant. The composer locks while generating."
)


class ComposerSuggester(Suggester):
    COMMANDS = (
        "/add ", "/build", "/preview", "/approve", "/format pdf",
        "/format docx", "/format markdown", "/help", "/search ", "/pick ",
        "/refresh", "/revise ", "/new ", "/open ", "/remove ", "/words ",
        "/limit ", "/todo ", "/todos", "/done ", "/skills", "/skill collect ",
        "/skill compose pdf", "/skill review ", "/commands", "/status", "/quit",
    )

    def __init__(self) -> None:
        super().__init__(use_cache=False, case_sensitive=True)

    async def get_suggestion(self, value: str) -> str | None:
        if not value:
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


class ReadingApp(App):
    TITLE = "DOC HARNESS"
    SUB_TITLE = "From everything you read to one useful document"
    CSS = """
    Screen { background: #0a1122; color: #e5edff; }
    Header { background: #12294e; color: #f1f6ff; }
    Footer { background: #12294e; }
    #body { height: 1fr; min-height: 0; overflow: hidden; }
    #shell { height: 1fr; min-height: 0; overflow: hidden; }
    #workspace-panel { width: 34%; min-width: 30; height: 100%; border: round #3971bc; background: #101d35; padding: 1 2; }
    #main-panel { width: 1fr; height: 100%; padding: 0 1; overflow: hidden; }
    .label { color: #77aef8; text-style: bold; margin-top: 1; }
    .info { color: #e4eeff; }
    #sources { height: 1fr; overflow-y: auto; }
    #tasks { height: 9; overflow-y: auto; }
    #activity { height: 1fr; min-height: 4; border: round #3971bc; background: #101d35; padding: 0 1; }
    #thinking { height: 1fr; min-height: 4; border: round #725da8; background: #161b36; padding: 0 1; overflow-y: auto; }
    #live-answer { height: 1fr; min-height: 4; border: round #3971bc; background: #101d35; padding: 0 1; overflow-y: auto; }
    #conversation { height: 2fr; min-height: 5; border: round #3971bc; background: #101d35; padding: 0 1; }
    #actions { height: 3; padding: 0 1; background: #101d35; }
    #actions Button { width: 12; margin-right: 1; }
    #format-picker { width: 19; margin-right: 1; }
    #composer-row { height: 3; padding: 0 1; background: #101d35; }
    #composer { width: 100%; background: #182945; border: round #4d91ee; color: #ffffff; }
    #stop { background: #8e3a55; color: #ffffff; }
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
        self.active_kind = ""

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Vertical(id="body"):
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
            with Horizontal(id="actions"):
                yield Select(
                    [("MARKDOWN", "markdown"), ("PDF", "pdf"), ("WORD", "docx")],
                    value=self.workspace.state["settings"]["format"],
                    allow_blank=False,
                    id="format-picker",
                )
                yield Button("BUILD", id="build")
                yield Button("PREVIEW", id="preview", disabled=True)
                yield Button("EXPORT", id="approve", disabled=True)
                yield Button("STOP", id="stop", disabled=True)
            with Horizontal(id="composer-row"):
                yield ComposerInput(
                    placeholder="Paste a file path or URL and press Enter; / offers commands; other text is chat",
                    suggester=ComposerSuggester(),
                    id="composer",
                )
        yield Footer()

    def on_mount(self) -> None:
        self.refresh_panels()
        self._log("SYSTEM", "Paste a file path or URL and press Enter. Then use BUILD, PREVIEW and EXPORT.")
        self._guide()
        self.query_one("#composer", Input).focus()

    def _guide(self) -> None:
        count = len(self.workspace.sources())
        if self.workspace.state["stage"] == "Exported":
            message = (
                f"Done. Your complete collection is at {self.workspace.state.get('last_output')}. "
                "Paste another source whenever you want to start a new edition."
            )
        elif not count:
            message = (
                f"Let's start. Your workspace is {self.workspace.root}. "
                "Paste the path to a file or a public article URL below and press Enter. "
                "To use another folder, say 'use folder C:\\path\\to\\my-reading'."
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

    def _add_source(self, raw: str) -> None:
        item = raw.strip().strip('"').strip("'")
        parsed = urlsplit(item)
        if parsed.scheme in {"http", "https"} and parsed.netloc:
            self.workspace.add_url(item)
            description = "link"
        elif (
            re.match(r"^(?:[A-Za-z]:[\\/]|[~.][\\/]|\\\\)", item)
            or Path(item).is_file()
            or Path(item).suffix.lower() in INPUT_SUFFIXES
        ):
            self.workspace.add_file(item)
            description = "file"
        else:
            raise ValueError("Paste a local .pdf/.docx/.md/.txt/.html file path or a public http(s) URL.")
        self._log("SYSTEM", f"Added {description}: {item}")
        self._chat_log("GUIDE", (
            f"Added that {description}. Add another source the same way, or say "
            "'make a PDF' / 'make a Word document' when you're ready."
        ))

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
        picker = self.query_one("#format-picker", Select)
        if picker.value != settings["format"]:
            picker.value = settings["format"]
        todos = workspace.state["todos"]
        self.query_one("#tasks", Static).update(Text(
            "\n".join(f"{i}. {'[x]' if task['done'] else '[ ]'} {task['title']}" for i, task in enumerate(todos, 1))
            if todos else "No tasks yet. Use /todo TITLE."
        ))
        self.query_one("#build", Button).disabled = self.busy
        self.query_one("#preview", Button).disabled = self.busy or not workspace.state.get("pending")
        pending = workspace.state.get("pending")
        self.query_one("#approve", Button).disabled = (
            self.busy or not pending or bool(pending["review"]["issues"])
        )
        picker.disabled = self.busy

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
        self.active_kind = kind
        self.cancel = Event()
        self.reasoning = ""
        self.answer = ""
        self.query_one("#thinking", Static).update("Waiting for model output...")
        self.query_one("#live-answer", Static).update("Waiting for model output...")
        self.query_one("#composer", Input).disabled = True
        self.query_one("#stop", Button).disabled = False
        self.query_one("#progress", ProgressBar).update(progress=0)
        self.refresh_panels()
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
        if not failed and self.active_kind in {"build", "refresh", "export"}:
            self._guide()

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

    def action_help(self) -> None:
        self._chat_log("COMMANDS", HELP)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "build":
            self._start("build")
        elif event.button.id == "preview":
            self._command("/preview", "")
        elif event.button.id == "approve":
            self._start("export")
        elif event.button.id == "stop":
            self.action_interrupt()

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id != "format-picker" or event.value not in {"markdown", "pdf", "docx"}:
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
        try:
            if text.startswith("/") and not Path(text.strip('"').strip("'")).is_file():
                command, _, argument = text.partition(" ")
                self._command(command.lower(), argument.strip().strip('"').strip("'"))
            else:
                self._handle_text(text)
        except (ValueError, OSError, RuntimeError) as error:
            self._log("ERROR", str(error))
        self.refresh_panels()

    def _handle_text(self, text: str) -> None:
        value = text.strip().strip('"').strip("'")
        lower = value.lower()
        if (
            urlsplit(value).scheme in {"http", "https"}
            or re.match(r"^(?:[A-Za-z]:[\\/]|[~.][\\/]|\\\\)", value)
            or Path(value).is_file()
            or Path(value).suffix.lower() in INPUT_SUFFIXES
        ):
            self._add_source(value)
            return
        attachment = re.match(
            r"^(?:please )?(?:add|include|import|adicionar|incluir)(?: this| esse| esta| o| a)?"
            r"(?: file| article| link| pdf| url| arquivo| artigo)?\s+(.+)$",
            value, flags=re.I,
        )
        if attachment:
            candidate = attachment.group(1).strip().strip('"').strip("'")
            if urlsplit(candidate).scheme in {"http", "https"} or re.match(r"^[A-Za-z]:[\\/]", candidate):
                self._add_source(candidate)
                return
        folder = re.match(
            r"^(?:use|create|open|switch to|usar|criar|abrir)(?: a| my| uma)? "
            r"(?:folder|workspace|pasta)\s+(.+)$", value, flags=re.I,
        )
        if folder:
            self.workspace = Workspace.create(folder.group(1).strip().strip('"').strip("'"))
            self.suggestions = []
            self._guide()
            return
        if lower in {"start", "let's start", "lets start", "help", "begin", "comecar", "começar", "bora iniciar", "oi"}:
            self._guide()
            return
        result = re.match(r"^(?:add|include|pick|adicionar|incluir) (?:result|resultado) (\d+)$", lower)
        if result:
            self._command("/pick", result.group(1))
            return
        if lower in {"show skills", "list skills", "mostrar skills"}:
            self._command("/skills", "")
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
        self._chat_log("YOU", text)
        self._start("chat", text)

    def _run_skill(self, request: str) -> None:
        raw_name, _, argument = request.strip().partition(" ")
        name = raw_name.lower()
        if name not in SKILLS:
            raise ValueError(f"Available skills: {', '.join(SKILLS)}. Try /skill collect PATH.")
        if name == "collect" and argument:
            self._add_source(argument)
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
        elif command in {"/add", "/add-file", "/add-url"}:
            self._add_source(argument)
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
        elif command == "/skills":
            self._chat_log("SKILLS", "\n".join(f"{name}: {description}" for name, description in SKILLS.items()))
        elif command == "/skill":
            self._run_skill(argument)
        elif command == "/status":
            self._log("SYSTEM", f"Stage: {workspace.state['stage']} | Latest: {workspace.state.get('last_output', 'none')}")
        elif command == "/cancel":
            self.action_interrupt()
        else:
            raise ValueError("Unknown command. Press F1 for help.")
