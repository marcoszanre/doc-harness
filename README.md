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
it is not a cooked `input()` prompt. It shows sources, tasks, progress, a
streamed response, and model-provided reasoning *when available*. The composer
locks during generation; **Ctrl+X** or **STOP** requests an interruption.

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

Use `python3 -m venv .venv` and `.venv/bin/python` on macOS/Linux. The default
working folder is `~/doc-harness-workspaces/weekly`, outside the repository.
To choose another folder:

```powershell
.\.venv\Scripts\python.exe -m doc_harness --workspace "$HOME\Documents\reading-week"
```

Example session inside the TUI:

```text
/add-file C:\Users\you\Downloads\notes.pdf
/add-url https://example.org/article
/format pdf
/words 250
/build
/preview
/approve
```

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

| Purpose | Commands |
|---|---|
| Working folders | `/new PATH`, `/open PATH`, `/status` |
| Sources | `/add-file PATH`, `/add-url URL`, `/remove N` |
| Tavily link search | `/search QUERY`, then `/pick N` to approve a result |
| Output | `/format markdown|pdf|docx`, `/words N` (summary), `/limit KB|off` |
| Human review | `/build`, `/refresh`, `/preview`, `/revise FEEDBACK`, `/approve`, `/reject` |
| Manual tasks | `/todo TITLE`, `/todos`, `/done N` |
| Help / stop | `/help` or **F1**, `/cancel` or **Ctrl+X**, `/quit` or **Ctrl+Q** |

Text without a slash is plain chat with the same Foundry model. Chat has **no
tools**: it can help plan your reading list but cannot browse, read your
files, add sources, or export a document.

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
exporters, chat, and TUI so it can be read in that order. This project is MIT
licensed. Do not commit credentials or contents of personal working folders.

API references: [Foundry reasoning and streaming](https://learn.microsoft.com/en-us/azure/ai-foundry/model-inference/how-to/use-chat-reasoning),
[Foundry Chat Completions v1](https://learn.microsoft.com/en-us/azure/foundry/openai/latest),
and [Textual thread workers](https://textual.textualize.io/guide/workers/).
