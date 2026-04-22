"""Tests for the Claude API adapter used by the locator engine."""
from __future__ import annotations
import json
from unittest.mock import MagicMock
import pytest
from tools.autopull import llm_adapter as la


def _fake_anthropic_response(json_obj: dict):
    resp = MagicMock()
    resp.content = [MagicMock(type="text", text=json.dumps(json_obj))]
    resp.usage.input_tokens = 500
    resp.usage.output_tokens = 50
    resp.usage.cache_creation_input_tokens = 0
    resp.usage.cache_read_input_tokens = 400
    return resp


def test_returns_parsed_json_on_success():
    client = MagicMock()
    client.messages.create.return_value = _fake_anthropic_response({
        "strategy": "css", "selector": "button.export",
        "confidence": 0.9, "reasoning": "big export button",
    })
    adapter = la.ClaudeLocatorAdapter(client=client, model="claude-sonnet-4-6")
    out = adapter("<html>...</html>")
    assert out["selector"] == "button.export"
    assert out["strategy"] == "css"


def test_rejects_non_json_response():
    client = MagicMock()
    resp = MagicMock()
    resp.content = [MagicMock(type="text", text="Sure, try: button.export")]
    resp.usage.input_tokens = 1; resp.usage.output_tokens = 1
    resp.usage.cache_creation_input_tokens = 0; resp.usage.cache_read_input_tokens = 0
    client.messages.create.return_value = resp
    adapter = la.ClaudeLocatorAdapter(client=client, model="claude-sonnet-4-6")
    with pytest.raises(la.LLMAdapterError):
        adapter("<html>...</html>")


def test_uses_prompt_caching_on_system_block():
    client = MagicMock()
    client.messages.create.return_value = _fake_anthropic_response({
        "strategy": "css", "selector": "x", "confidence": 0.5, "reasoning": "",
    })
    adapter = la.ClaudeLocatorAdapter(client=client, model="claude-sonnet-4-6")
    adapter("<html>...</html>")
    kwargs = client.messages.create.call_args.kwargs
    system = kwargs["system"]
    assert isinstance(system, list)
    assert any(block.get("cache_control") == {"type": "ephemeral"} for block in system)


def test_rejects_missing_required_keys():
    client = MagicMock()
    client.messages.create.return_value = _fake_anthropic_response({
        "selector": "x"   # missing 'strategy'
    })
    adapter = la.ClaudeLocatorAdapter(client=client, model="claude-sonnet-4-6")
    with pytest.raises(la.LLMAdapterError):
        adapter("<html>...</html>")
