"""Azure Foundry Chat Completions adapter with streaming output."""

from __future__ import annotations

import os
from dataclasses import dataclass
from threading import Event
from typing import Any, Callable

from azure.identity import DefaultAzureCredential, get_bearer_token_provider
from openai import OpenAI

ENDPOINT = "https://harness-learning-resource.services.ai.azure.com/openai/v1/"
DEPLOYMENT = "DeepSeek-V4-Pro"
EventSink = Callable[[str, str], None]


@dataclass
class Completion:
    content: str


class Foundry:
    def __init__(self, client: Any = None) -> None:
        self.credential = None
        if client is None:
            key = os.getenv("AZURE_AI_API_KEY")
            if key:
                client = OpenAI(base_url=ENDPOINT, api_key=key, timeout=120, max_retries=0)
            else:
                self.credential = DefaultAzureCredential(
                    exclude_interactive_browser_credential=True,
                )
                token = get_bearer_token_provider(self.credential, "https://ai.azure.com/.default")
                client = OpenAI(base_url=ENDPOINT, api_key=token, timeout=120, max_retries=0)
        self.client = client

    def close(self) -> None:
        if self.credential:
            self.credential.close()
        self.client.close()

    def complete(
        self,
        messages: list[dict],
        emit: EventSink,
        cancel: Event,
    ) -> Completion:
        request: dict[str, Any] = {
            "model": DEPLOYMENT,
            "messages": messages,
            "stream": True,
            "max_completion_tokens": 6000,
        }
        content: list[str] = []
        finish_reason = None
        with self.client.chat.completions.create(**request) as stream:
            for chunk in stream:
                if cancel.is_set():
                    raise InterruptedError("Model generation was interrupted.")
                for choice in chunk.choices:
                    if choice.finish_reason:
                        finish_reason = choice.finish_reason
                    delta = choice.delta.model_dump(exclude_none=True)
                    thought = delta.get("reasoning_content")
                    if thought:
                        emit("reasoning", thought)
                    if delta.get("content"):
                        content.append(delta["content"])
                        emit("answer", delta["content"])
        if finish_reason in {"content_filter", "length"}:
            raise ValueError(
                "Foundry filtered the response." if finish_reason == "content_filter"
                else "The model stopped at its output limit. Shorten the requested document."
            )
        if not content:
            raise ValueError("The model returned no answer. Try again.")
        return Completion("".join(content))
