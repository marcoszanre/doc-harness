"""Small, user-invocable workflow guides; no agent tool execution."""

from importlib.resources import files

SKILLS = {
    "guide": "Choose the next step from the current workspace state.",
    "collect": "Add local files or public links to the workspace.",
    "compose": "Choose Markdown, PDF, or Word and prepare the full-text collection.",
    "review": "Preview, revise the summary, and approve the final document.",
}


def read_skill(name: str) -> str:
    if name not in SKILLS:
        raise ValueError(f"Unknown skill: {name}. Available: {', '.join(SKILLS)}.")
    return files("doc_harness").joinpath("skills", name, "SKILL.md").read_text(encoding="utf-8")
