"""Phase 2: model client wrapper and cost estimation (no network).

Author: Ignacio Rodríguez Caro
"""

from __future__ import annotations

import os
from types import SimpleNamespace

import pytest

from quilora.agent.model import AnthropicModelClient, ModelResponse, TokenUsage
from quilora.agent.pricing import estimate_cost_usd


def _fake_message():
    return SimpleNamespace(
        content=[
            SimpleNamespace(type="text", text="Let me check.", citations=None),
            SimpleNamespace(type="tool_use", id="toolu_1", name="check_stock",
                            input={"product_id": "QL-TRS-001"}),
        ],
        stop_reason="tool_use",
        model="claude-sonnet-5-5",
        usage=SimpleNamespace(input_tokens=1200, output_tokens=40,
                              cache_creation_input_tokens=0, cache_read_input_tokens=900),
    )


def test_client_normalises_blocks_and_usage(monkeypatch):
    client = AnthropicModelClient(api_key="test-key", model="claude-sonnet-5-5")
    captured = {}

    def fake_create(**kwargs):
        captured.update(kwargs)
        return _fake_message()

    monkeypatch.setattr(client._client.messages, "create", fake_create)
    response = client.create(system="sys", messages=[{"role": "user", "content": "hi"}],
                             tools=[{"name": "check_stock"}], max_tokens=100)

    assert captured["cache_control"] == {"type": "ephemeral"}
    assert captured["tools"] == [{"name": "check_stock"}]
    # Only the fields we resend are kept (no `citations: None` noise in stored history).
    assert response.content[0] == {"type": "text", "text": "Let me check."}
    assert response.tool_uses[0]["name"] == "check_stock"
    assert response.usage.cache_read_input_tokens == 900
    assert response.stop_reason == "tool_use"


def test_client_requires_api_key():
    with pytest.raises(ValueError, match="ANTHROPIC_API_KEY"):
        AnthropicModelClient(api_key=None, model="claude-sonnet-5-5")


def test_cost_counts_cache_reads_cheaper_than_fresh_input():
    fresh = estimate_cost_usd("claude-sonnet-5-5", TokenUsage(input_tokens=10_000))
    cached = estimate_cost_usd("claude-sonnet-5-5", TokenUsage(cache_read_input_tokens=10_000))
    assert cached < fresh
    assert estimate_cost_usd("unknown-model", TokenUsage(input_tokens=1)) is None


def test_usage_addition():
    total = TokenUsage(1, 2, 3, 4) + TokenUsage(10, 20, 30, 40)
    assert total.as_dict() == {"input_tokens": 11, "output_tokens": 22,
                               "cache_creation_input_tokens": 33,
                               "cache_read_input_tokens": 44}


def test_response_text_joins_text_blocks():
    r = ModelResponse(content=[{"type": "text", "text": "a"}, {"type": "text", "text": "b"}],
                      stop_reason="end_turn", model="m")
    assert r.text == "a\nb"


@pytest.mark.live
@pytest.mark.skipif(not os.environ.get("ANTHROPIC_API_KEY"), reason="needs ANTHROPIC_API_KEY")
def test_live_minimal_call():
    from quilora.config import load_settings

    s = load_settings()
    client = AnthropicModelClient(s.anthropic_api_key, s.agent_model)
    r = client.create(system="Reply with the single word OK.",
                      messages=[{"role": "user", "content": "ping"}], tools=None, max_tokens=10)
    assert "OK" in r.text.upper()
