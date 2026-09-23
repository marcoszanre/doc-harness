"""A small conversational companion, without model tools or extra providers."""

from threading import Event

from .foundry import Foundry
from .skills import read_skill
from .workspace import Workspace


def chat(workspace: Workspace, model: Foundry, prompt: str, emit, cancel: Event) -> str:
    history = workspace.state["chat"][-12:]
    source_names = [f"{item['kind']}: {item['label']}" for item in workspace.sources()]
    stage = workspace.state["stage"]
    messages = [
        {"role": "system", "content": (
            "You are a concise conversational guide for a reading collection. "
            f"Current workspace: {workspace.root}. Source list (authoritative): "
            f"{source_names or 'none'}. Stage: {stage}. "
            "Use the actual source list; never say that the workspace is empty when it is not. "
            "If an operation needs to happen, explain the next simple action; never claim "
            "to have fetched, read, exported, or changed something you did not do. "
            "Answer in the user's language. Do not overwhelm novices with slash commands. "
            + read_skill("guide").split("---", 2)[-1]
        )},
        *history,
        {"role": "user", "content": prompt},
    ]
    answer = model.complete(messages, emit, cancel).content
    workspace.state["chat"] = [
        *history,
        {"role": "user", "content": prompt},
        {"role": "assistant", "content": answer},
    ][-12:]
    workspace.save()
    return answer
