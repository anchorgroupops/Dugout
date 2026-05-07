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


# ---------------------------------------------------------------------------
# build_default_adapter
# ---------------------------------------------------------------------------

def test_build_default_adapter_returns_adapter():
    from unittest.mock import patch, MagicMock
    fake_client = MagicMock()
    with patch("tools.autopull.llm_adapter.Anthropic", return_value=fake_client) if False else __import__("contextlib").nullcontext():
        # Patch at the module level where it's imported inside the function
        with patch("anthropic.Anthropic", return_value=fake_client):
            adapter = la.build_default_adapter(api_key="fake-key", model="test-model")
    assert isinstance(adapter, la.ClaudeLocatorAdapter)


def test_build_default_adapter_passes_model():
    from unittest.mock import patch, MagicMock
    fake_client = MagicMock()
    with patch("anthropic.Anthropic", return_value=fake_client):
        adapter = la.build_default_adapter(api_key="fake-key", model="claude-sonnet-4-6")
    assert adapter.model == "claude-sonnet-4-6"


def test_rejects_response_with_no_text_block():
    """When the API response has no text-type content block, raise LLMAdapterError."""
    client = MagicMock()
    resp = MagicMock()
    resp.content = [MagicMock(type="tool_use")]  # no text block
    resp.usage.input_tokens = 1; resp.usage.output_tokens = 1
    resp.usage.cache_creation_input_tokens = 0; resp.usage.cache_read_input_tokens = 0
    client.messages.create.return_value = resp
    adapter = la.ClaudeLocatorAdapter(client=client, model="claude-sonnet-4-6")
    with pytest.raises(la.LLMAdapterError):
        adapter("<html></html>")


def test_rejects_json_list_response():
    """When the response JSON is a list (not a dict), raise LLMAdapterError."""
    client = MagicMock()
    resp = MagicMock()
    resp.content = [MagicMock(type="text", text='["not", "a", "dict"]')]
    resp.usage.input_tokens = 1; resp.usage.output_tokens = 1
    resp.usage.cache_creation_input_tokens = 0; resp.usage.cache_read_input_tokens = 0
    client.messages.create.return_value = resp
    adapter = la.ClaudeLocatorAdapter(client=client, model="claude-sonnet-4-6")
    with pytest.raises(la.LLMAdapterError):
        adapter("<html></html>")


def test_rejects_unknown_strategy():
    """When strategy is not 'css' or 'xpath', raise LLMAdapterError."""
    client = MagicMock()
    client.messages.create.return_value = _fake_anthropic_response({
        "strategy": "locator", "selector": "role=button",
        "confidence": 0.9, "reasoning": "",
    })
    adapter = la.ClaudeLocatorAdapter(client=client, model="claude-sonnet-4-6")
    with pytest.raises(la.LLMAdapterError):
        adapter("<html></html>")
