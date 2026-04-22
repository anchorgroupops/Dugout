"""Claude API adapter for locator fallback.

System prompt is cached via the ephemeral cache_control block so repeated
adaptations within the 5-minute cache window are cheap.
"""
from __future__ import annotations
import json
import logging
import re
from typing import Any

log = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
You identify UI elements on GameChanger's stats page that trigger a CSV
download. You are being called only when hardcoded selectors have failed,
meaning the page structure has likely changed.

Given a pruned HTML snapshot of the current page, return a JSON object with:
{
  "strategy": "css" | "xpath",
  "selector": "<the selector string>",
  "confidence": <float 0..1>,
  "reasoning": "<one-sentence why>"
}

Rules:
- Prefer CSS over XPath.
- The element, when clicked, must trigger a direct CSV download OR open a
  submenu whose CSV option triggers a download. For submenus, chain with
  Playwright's ">>" operator (e.g. "button.actions >> li:has-text('CSV')").
- NEVER propose selectors that match logout, delete, remove, unsubscribe,
  cancel, or any destructive action.
- If you cannot find a plausible candidate, return confidence < 0.3.

Return ONLY the JSON object — no markdown fences, no prose.
"""


class LLMAdapterError(RuntimeError):
    pass


class ClaudeLocatorAdapter:
    """Callable: takes pruned DOM, returns proposal dict or raises LLMAdapterError."""

    def __init__(self, *, client: Any, model: str = "claude-sonnet-4-6",
                 max_tokens: int = 400):
        self.client = client
        self.model = model
        self.max_tokens = max_tokens

    def __call__(self, pruned_dom: str) -> dict:
        resp = self.client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            system=[
                {"type": "text", "text": SYSTEM_PROMPT,
                 "cache_control": {"type": "ephemeral"}},
            ],
            messages=[
                {"role": "user", "content": f"Current DOM snapshot:\n\n{pruned_dom}"},
            ],
        )
        text = self._first_text(resp)
        data = self._parse_json(text)
        self._validate(data)
        return data

    @staticmethod
    def _first_text(resp: Any) -> str:
        for block in getattr(resp, "content", []) or []:
            if getattr(block, "type", None) == "text":
                return block.text
        raise LLMAdapterError("Response contained no text block")

    @staticmethod
    def _parse_json(text: str) -> dict:
        # Strip accidental code fences if the model added them
        stripped = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
        try:
            data = json.loads(stripped)
        except json.JSONDecodeError as e:
            raise LLMAdapterError(f"Response was not JSON: {e}; got: {text!r}")
        if not isinstance(data, dict):
            raise LLMAdapterError("Response JSON was not an object")
        return data

    @staticmethod
    def _validate(data: dict) -> None:
        for key in ("strategy", "selector"):
            if key not in data or not data[key]:
                raise LLMAdapterError(f"Response missing required key {key!r}")
        if data["strategy"] not in ("css", "xpath"):
            raise LLMAdapterError(f"Unknown strategy: {data['strategy']!r}")


def build_default_adapter(*, api_key: str, model: str) -> ClaudeLocatorAdapter:
    from anthropic import Anthropic
    client = Anthropic(api_key=api_key)
    return ClaudeLocatorAdapter(client=client, model=model)
