# Reading Harness

**One place for everything you read. One document worth revisiting.**

Reading Harness is a local-first Python learning project. Give it the articles
and notes you followed this week—a blog post, a text-based PDF, a Word file,
or a Markdown note—and it assembles their **complete extracted text** into a
single navigable reading collection. DeepSeek-V4-Pro on Microsoft Foundry writes
only the edition summary; Python preserves and assembles the sources. You
review the draft before exporting it as **Markdown, PDF, or Word**.

**Build once, export again without another model call.** After approving a
draft, switch the output format and select **Export**. A new file is rendered
from the same approved text; no new summary, source indexing, or tokens are
needed. Change the sources or target summary length, and **Build** creates a
fresh edition instead.

## Quick start

Requires Python 3.11+, an interactive terminal, and access to a deployed
DeepSeek-V4-Pro model on Microsoft Foundry. Install Azure CLI for `az login`,
or use an API key instead. No account-specific endpoint or credential is
included in this repository.

```powershell
git clone https://github.com/marcoszanre/reading-harness.git
cd reading-harness
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
az login
$env:READING_HARNESS_FOUNDRY_ENDPOINT = "<your Foundry OpenAI v1 base endpoint>"
.\.venv\Scripts\reading-harness.exe
```

The endpoint value is your resource's **OpenAI v1 base endpoint**. If you have
the full Chat Completions URL, the app accepts that too. Azure CLI /
`DefaultAzureCredential` authenticates by default; alternatively, set
`AZURE_AI_API_KEY` in your environment. Do not commit keys or local settings.
To store the endpoint **only on your computer** instead of entering it every
shell session:

```powershell
.\.venv\Scripts\reading-harness.exe --set-foundry-endpoint "<your endpoint>"
```

That command saves the endpoint under your home directory, **outside the Git
repository**, and does not store an API key. On macOS or Linux, use
`python3 -m venv .venv` and `.venv/bin/reading-harness`.

## Your first collection

1. On launch, **choose** a working folder. The app never silently creates one;
   it shows the exact path before importing anything.
2. Paste one or several local file paths and public article URLs into the
   composer. You can paste multiple lines at once, use `;` separators, or
   right-click on Windows to paste text or files copied in File Explorer.
3. Pick **Markdown**, **PDF**, or **Word**, then select **Build**. Source errors
   stop the build rather than silently omitting an article.
4. Select **Preview** to read the draft. Request changes to the *summary* if
   needed. Once the citation and length gate is satisfied, select **Export**.
5. Want another format? Change the picker and select **Export** again. The
   approved draft is reused. To incorporate new sources, select **Build**.

Each result is one file in your working folder's `output/`: an edition
summary, a clickable in-document table of contents, the complete extracted
article texts, and original-source references at the end. The old file is
never overwritten when you export another format.

The input is a full-width, scrollable conversation—not a cooked command
prompt. **Enter sends**; **Shift+Enter** adds a line when the terminal sends
it distinctly. Reading Harness also recognizes an existing Windows Terminal
Shift+Enter binding that sends `ESC` + `Enter`, **without changing Terminal
settings**. **Ctrl+J** or the **New line** button work when the terminal
cannot distinguish the modified key. The footer reports input and output
tokens supplied by Foundry, not estimated cost.

For expert shortcuts, use `/skills` or F1. `/restart` (Ctrl+R) returns to
the folder chooser **without deleting your files**. `/search QUERY` suggests
public links through Tavily; adding one still requires your `/pick N` approval
and a `TAVILY_API_KEY` environment variable.

## What happens under the hood?

```text
working folder
    inputs/  +  approved links
           |
           v
  bounded text extraction  ->  cache/source snapshots
           |                         |
           | short excerpts          | full extracted text
           v                         |
  Foundry Chat Completions            |
  DeepSeek-V4-Pro: edition summary    |
           |                         |
           v                         v
  citation + length review  ->  draft.md  ->  human approval
                                           |
                                  Markdown / PDF / Word
```

The available tools are deliberate and small: local PDF/DOCX/Markdown/text
extraction, bounded HTTP fetch, optional Tavily link search, a visible todo
list, citation/length review, and three document exporters. **No function
tools are passed to the model**: the model writes the summary, while Python
validates inputs and runs the workflow. There is no Playwright browser,
Google Docs integration, or MCP server. The todo list supports
create/list/mark-done, **not** full CRUD. Files are read only after you add
them as sources; cache and output writes are controlled by the workflow.
There are no general-purpose model-facing `read_file`, `write_file`, or
`report_done` tools.

| Component | Responsibility |
|---|---|
| `workspace.py` | Working-folder state, source catalog, safe imports, and approval fingerprints. |
| `sources.py` | Bounded local and web extraction; cache of complete source text. |
| `foundry.py` | Configurable Foundry Chat Completions client, streaming, and reported token usage. |
| `workflow.py` | Edition summary, citation checks, source snapshots, and revisions. |
| `exporters.py` | One approved draft, three local formats, clickable navigation. |
| `tui.py` | Raw terminal conversation, folder chooser, approvals, and progress. |
| `skills/` | Four short, optional guides for collecting, composing, reviewing, and onboarding. |

The `guide`, `collect`, `compose`, and `review` skills are short, bundled
workflow guides and optional `/skill` shortcuts, **not** a dynamic skill
installer. The internal Python module and workspace metadata file retain
their original `doc_harness` / `.doc-harness.json` names for compatibility;
the public project and command are **Reading Harness**.

## Boundaries

- Inputs: UTF-8 text, Markdown, HTML, text-based PDFs, DOCX, and public HTML
  or text URLs. Image-only PDFs need OCR elsewhere. Embedded pictures and
  original page layout are **not** reproduced; this is a text compilation,
  not a pixel-perfect PDF merge.
- Limits: 8 MB per local file, 2 MB per web download, 2 million extracted
  characters per source, and 30 URL sources. Only bounded excerpts are sent
  to the model; the final document includes the full extracted source text.
- External pages are untrusted evidence, never instructions. URL checks
  reject local/private addresses and nonstandard ports, including redirects.
  This is a local learning tool, **not** a hardened public service.
- The quality gate checks citations and target **summary** length, not the
  accuracy of every factual claim. Read the draft and ensure you have the
  rights to share each source. Your extracted excerpts go to Foundry;
  Tavily receives queries only when you use web search.
- Reported token totals include completed model requests. The app cannot
  reconstruct usage from older versions, and an interrupted stream may not
  include its final usage report. Exporting an already approved draft in a
  different format does **not** call the model.

## Development

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m compileall -q doc_harness
```

Tests use fake responses by default and do not require a Foundry deployment.
The opt-in live test makes billed requests. In PowerShell:

```powershell
$env:DOC_HARNESS_LIVE = "1"
.\.venv\Scripts\python.exe -m unittest discover -s tests -p test_live.py -v
```

The project uses
`azure-identity`, `openai`, `textual`, `python-docx`, `reportlab`, and `pypdf`;
there is no browser automation or server to deploy.

Contributions are welcome. The project is MIT licensed.
