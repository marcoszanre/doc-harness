# Doc Harness

**Your week of reading, together in one navigable document.**

Doc Harness is a small Python learning project: collect local notes and public
articles in a working folder, ask an Azure Foundry model to write an **edition
summary**, then assemble the **complete extracted text of every source** into
one Markdown, PDF, or DOCX file. A hyperlinked table of contents navigates
to each article *inside the final file*. An original-sources section at the
end links to external URLs and identifies local input files. There
are no templates, browser automation, Google integration, or agent tool loop.
The only model/provider is **DeepSeek-V4-Pro on Azure Foundry**.

The full-screen Textual interface runs in the terminal's interactive/raw mode;
it is not a cooked `input()` prompt. It focuses on **one full-width scrolling
conversation** with rendered Markdown and compact, unobtrusive progress lines.
The working-folder path stays visible above the chat; sources and tasks live
behind a **single collapsed count** so long URLs do not dominate the screen.
model-provided reasoning, *when available*, is collapsed beneath the answer.
The full-width composer accepts pasted file paths, URLs, or ordinary requests.
Paste **several sources at once**, one per line or separated by semicolons.
Every submitted user message remains visible above the composer; assistant
replies render Markdown rather than exposing formatting characters.
The composer **wraps long text** and grows to a maximum of eight terminal
rows. **Enter sends**; **Shift+Enter** inserts a newline when the terminal
forwards it distinctly. Windows Terminal may send a legacy `ESC` + `Enter`
sequence for a custom Shift+Enter binding, which Textual normally reads as
plain Enter. Doc Harness recognizes that existing binding **only within this
app**, without editing terminal settings. **Ctrl+J** and the **New line**
button are reliable alternatives when a terminal cannot distinguish
Shift+Enter. Ctrl+Enter or Cmd+Enter also work when the terminal forwards
them distinctly. The footer displays the available shortcut.
Buttons cover common actions; the composer locks during generation and
**Ctrl+X** or **Stop** requests an interruption.

## Get started

Requires Python 3.11+ and a modern interactive terminal.

```powershell
git clone https://github.com/marcoszanre/doc-harness.git
cd doc-harness
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
az login
.\.venv\Scripts\python.exe -m doc_harness
```

Use `python3 -m venv .venv` and `.venv/bin/python` on macOS/Linux. On launch,
the app **asks where to work**. It suggests `~/doc-harness-workspaces/weekly`
if you want a default; it neither opens nor creates that folder until you
choose it. The fixed header displays the **full working-folder path** so you
can find `inputs/` and `output/`; those directories are not inside the
cloned Git repository unless you explicitly put them there.
To bypass the prompt and select a folder directly:

```powershell
.\.venv\Scripts\python.exe -m doc_harness --workspace "$HOME\Documents\reading-week"
```

Example session inside the TUI — **no commands to memorize**:

```text
C:\Users\you\Downloads\notes.pdf
https://example.org/article
make a PDF
```

You can also paste the first two lines **together** and press Enter once;
the input preserves both lines and adds both sources. Paste a path or link
and press Enter; each source appears in the workspace.
Choose PDF from the format selector or say "make a PDF". Use the **BUILD**,
**PREVIEW**, and **EXPORT** buttons. Say "use folder C:\my-reading" to switch
working folders, or "change the summary to focus on..." to revise the draft.
To find additional links, say "find articles about ...", then "add result 1".
The suggestion in the composer completes slash commands and local paths with
**Tab** or **Right Arrow**; commands are optional.

The footer displays **In** and **Out** token totals reported by Foundry for
completed model requests. Output includes generated reasoning tokens when
the model uses them. Totals persist in the working folder, but requests made
before this counter existed cannot be recovered. If a stream stops before
Foundry sends its final usage chunk, the footer marks the request as
unavailable rather than inventing a count.

Ask **"which sources are configured?"** (or **"quais sources estão
configurados?"**) to see the actual files and URLs in the active workspace.
This inventory is read directly from the folder, not guessed by the model.
Open the fixed **Sources and tasks** control to inspect them without leaving
the conversation. Use the mouse wheel or Page Up/Page Down
to scroll; incoming output follows the bottom until you scroll up to read.

**Right-click the composer on Windows** to paste clipboard text or files copied
in File Explorer. Ctrl+V and Shift+Insert remain available if your terminal
intercepts right-click to show its own context menu. This behavior belongs to
your Windows Terminal mouse settings, not to your workspace.

The approved file appears in your folder's `output/` directory. Its summary,
navigation, full article texts, and source references are all in that **one
file**, not separate exports or a list of links. Choose
`/format markdown` or `/format docx` instead for the other outputs. `/build`
indexes your sources and drafts the collection; `/preview` shows it; `/revise
Make the summary shorter` revises **only the edition summary**, never the
article texts; `/approve` exports after review. `/words` targets only the
summary, **not** the total document length. A smaller `/limit KB` cannot
silently shorten sources: export stops with an explicit size error instead.
Missing or invented citations in the summary block export. Other quality
warnings, such as summary length outside +/- 25% of your target, require
explicit approval.

## What's in a working folder?

```text
reading-week/
  inputs/             copied files or files you drop in directly
  cache/              complete extracted text, source snapshots, and reviewable draft.md
  output/             approved reading-list-YYYY-MM-DD.md/pdf/docx
  .doc-harness.json   settings, source links, chat, tasks, and stage
```

Supported input files: UTF-8 `.md`, `.txt`, `.html`, text-based `.pdf`, and
`.docx` (including table cells). Public HTML/text URLs are fetched directly,
reduced to readable text, and cached as Markdown; `/refresh` forces refetching.
The input limits are 8 MB per file, 2 MB per web download, 2 million
extracted characters per source, and 30 URLs. **Source texts are not truncated
for the final file**; only excerpts sent to the model *for its summary* are
bounded. If even one source cannot be read completely, the build fails rather
than producing an incomplete collection. Image-only PDFs need OCR elsewhere;
embedded pictures, diagrams, and the original PDF page layout are not
preserved. The output is a reformatted **text** compilation, not a pixel-exact
PDF merge. Removing a file via `/remove N` archives it in `cache/` instead of
deleting your copy.

## Commands

Press **F1** for a short guided start. The commands below are optional expert
shortcuts; `/commands` shows the complete list in the UI:

| Purpose | Commands |
|---|---|
| Working folders | `/new PATH`, `/open PATH`, `/status` |
| Sources | `/add-file PATH`, `/add-url URL`, `/remove N` |
| Tavily link search | `/search QUERY`, then `/pick N` to approve a result |
| Output | `/format markdown|pdf|docx`, `/words N` (summary), `/limit KB|off` |
| Human review | `/build`, `/refresh`, `/preview`, `/revise FEEDBACK`, `/approve`, `/reject` |
| Manual tasks | `/todo TITLE`, `/todos`, `/done N` |
| Help / restart / stop | `/help` or **F1**, `/restart` or **Ctrl+R**, `/cancel` or **Ctrl+X**, `/quit` or **Ctrl+Q** |

Embedded workflow skills are available with `/skills`: `guide`, `collect`,
`compose`, and `review`. Experts can invoke `/skill collect PATH_OR_URL`,
`/skill compose pdf|docx|markdown`, or `/skill review preview|approve|FEEDBACK`
directly. These small `SKILL.md` files describe the setup for each stage;
they do not add a tool-calling agent loop. Unrecognized free-form requests
go to plain chat with the same Foundry model, which guides you but does not
claim it performed an action.

Set `TAVILY_API_KEY` in your environment to enable `/search`; a found link
enters your folder only after `/pick N`. No key is included in this repository:

```powershell
$env:TAVILY_API_KEY = "<your Tavily key>"
```

## Model and safety

The default endpoint is
`https://harness-learning-resource.services.ai.azure.com/openai/v1/chat/completions`
with deployment `DeepSeek-V4-Pro`. The SDK uses Azure Foundry's
OpenAI-compatible Chat Completions API. Authenticate with `az login` and
appropriate deployment permissions, or provide `AZURE_AI_API_KEY` for the same
resource. For a different Foundry resource, change `ENDPOINT` in
`doc_harness/foundry.py`; keep its `/openai/v1/` suffix. **No fallback to a
different provider or model is implemented.**

Model-provided `reasoning_content` is displayed if returned, not persisted or
treated as verified reasoning. Sources are evidence, never instructions. The
model writes **only the summary**; Python deterministically appends all
extracted source text. The app checks summary citations and length, attempts
at most two summary revisions, then requires human approval. It also refuses
to export if the reviewed draft or source snapshots changed. These checks do
not prove factual accuracy: read the draft before sharing it. URLs to private,
loopback, and reserved addresses are rejected (including redirects); this
is not a hardened public-server sandbox.
Your extracted text is sent to Foundry, search queries go to Tavily when you
use `/search`, and approved documents stay local.

`/restart` returns to the working-folder chooser and clears the visible UI
session; it does **not** remove workspaces, sources, or approved files. Choosing
a folder shows its exact absolute path and whether it was created or opened.
For Word output, the navigation pane contains only the edition sections and
one heading per article; article-internal headings are readable subheadings
without flooding navigation. The Word table of contents uses direct links to
those article headings. When a blog exposes an article-body container, the
extractor omits surrounding Share, Tags, and Related posts UI. The next build
refreshes older cached extraction automatically. Existing exported files are
not overwritten: use Build -> Preview -> Export again for the improved DOCX.

## Test and contribute

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m compileall -q doc_harness
```

Offline tests use fake model responses. To run the opt-in real Foundry
integration test from PowerShell, set `$env:DOC_HARNESS_LIVE = "1"` and run
`python -m unittest discover -s tests -p test_live.py -v`. You need a working
Azure login and a deployed model; this makes billed API requests.

The code is organized by workspace, sources, Foundry adapter, workflow,
exporters, chat, optional workflow skills, and TUI so it can be read in that
order. This project is MIT licensed. Do not commit credentials or contents of
personal working folders.

API references: [Foundry reasoning and streaming](https://learn.microsoft.com/en-us/azure/ai-foundry/model-inference/how-to/use-chat-reasoning),
[Foundry Chat Completions v1](https://learn.microsoft.com/en-us/azure/foundry/openai/latest),
and [Textual thread workers](https://textual.textualize.io/guide/workers/).
