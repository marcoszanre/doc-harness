"""Azure Foundry Chat Completions adapter with streaming output."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from threading import Event
from typing import Any, Callable
from urllib.parse import urlsplit

from azure.identity import DefaultAzureCredential, get_bearer_token_provider
from openai import OpenAI

DEPLOYMENT = "DeepSeek-V4-Pro"
ENDPOINT_ENV = "READING_HARNESS_FOUNDRY_ENDPOINT"
CONFIG_PATH = Path.home() / ".reading-harness" / "settings.json"
EventSink = Callable[[str, str], None]


def validate_endpoint(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("The Foundry endpoint must be a URL.")
    endpoint = value.strip().rstrip("/")
    if endpoint.endswith("/chat/completions"):
        endpoint = endpoint.removesuffix("/chat/completions")
    parsed = urlsplit(endpoint)
    if parsed.scheme != "https" or not parsed.hostname or not parsed.path.endswith("/openai/v1"):
        raise ValueError("Provide the HTTPS Foundry OpenAI v1 base endpoint.")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("Do not include credentials or query parameters in the endpoint.")
    return endpoint + "/"


def load_endpoint() -> str:
    configured = os.getenv(ENDPOINT_ENV)
    if configured:
        return validate_endpoint(configured)
    if CONFIG_PATH.is_file():
        try:
            settings = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise ValueError(f"Cannot read local Foundry settings: {CONFIG_PATH}") from error
        return validate_endpoint(settings.get("foundry_endpoint"))
    raise ValueError(
        f"Set {ENDPOINT_ENV} or use --set-foundry-endpoint once before running the model."
    )


def save_local_endpoint(value: str) -> Path:
    from .workspace import atomic_text

    atomic_text(CONFIG_PATH, json.dumps({"foundry_endpoint": validate_endpoint(value)}, indent=2))
    if os.name != "nt":
        CONFIG_PATH.chmod(0o600)
    return CONFIG_PATH


@dataclass
class Completion:
    content: str
    input_tokens: int | None = None
    output_tokens: int | None = None


class Foundry:
    def __init__(self, client: Any = None) -> None:
        self.credential = None
        self.on_usage: Callable[[Completion], None] | None = None
        if client is None:
            endpoint = load_endpoint()
            key = os.getenv("AZURE_AI_API_KEY")
            if key:
                client = OpenAI(base_url=endpoint, api_key=key, timeout=120, max_retries=0)
            else:
                self.credential = DefaultAzureCredential(
                    exclude_interactive_browser_credential=True,
                )
                token = get_bearer_token_provider(self.credential, "https://ai.azure.com/.default")
                client = OpenAI(base_url=endpoint, api_key=token, timeout=120, max_retries=0)
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
            "stream_options": {"include_usage": True},
            "max_completion_tokens": 6000,
        }
        content: list[str] = []
        finish_reason = None
        input_tokens: int | None = None
        output_tokens: int | None = None
        with self.client.chat.completions.create(**request) as stream:
            try:
                for chunk in stream:
                    if cancel.is_set():
                        raise InterruptedError("Model generation was interrupted.")
                    usage = getattr(chunk, "usage", None)
                    if usage is not None:
                        input_tokens = usage.prompt_tokens
                        output_tokens = usage.completion_tokens
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
            finally:
                if self.on_usage is not None:
                    self.on_usage(Completion("".join(content), input_tokens, output_tokens))
        result = Completion("".join(content), input_tokens, output_tokens)
        if finish_reason in {"content_filter", "length"}:
            raise ValueError(
                "Foundry filtered the response." if finish_reason == "content_filter"
                else "The model stopped at its output limit. Shorten the requested document."
            )
        if not content:
            raise ValueError("The model returned no answer. Try again.")
        return result
