"""Terminal chat for local experiments.

Phase 2 (no tools, see docs/phases/02-minimal-chat.md):
    python -m quilora.cli --raw
"""

from __future__ import annotations

import argparse

from quilora.agent.model import AnthropicModelClient, TokenUsage
from quilora.agent.pricing import estimate_cost_usd
from quilora.agent.prompts import render
from quilora.config import load_settings


def raw_chat(prompt_name: str) -> None:
    """Plain model call with a system prompt and no tools, to observe the model's limits."""
    settings = load_settings()
    client = AnthropicModelClient(settings.anthropic_api_key, settings.agent_model,
                                  settings.model_timeout_s)
    system = render(prompt_name, today=settings.today())
    history: list[dict] = []
    total = TokenUsage()
    print(f"Raw chat with {settings.agent_model} (prompt: {prompt_name}). Ctrl-D to exit.\n")
    while True:
        try:
            user = input("you> ").strip()
        except EOFError:
            break
        if not user:
            continue
        history.append({"role": "user", "content": user})
        response = client.create(system=system, messages=history, tools=None,
                                 max_tokens=settings.agent_max_tokens)
        history.append({"role": "assistant", "content": response.content})
        total = total + response.usage
        cost = estimate_cost_usd(response.model, response.usage)
        print(f"\nassistant> {response.text}\n")
        print(f"  [{response.latency_ms:.0f} ms | in {response.usage.input_tokens} "
              f"out {response.usage.output_tokens} | ~${cost}]\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Quilora assistant in the terminal")
    parser.add_argument("--raw", action="store_true", help="model only, no tools (phase 2)")
    parser.add_argument("--prompt", default="minimal", help="prompt template name")
    args = parser.parse_args()
    if args.raw:
        raw_chat(args.prompt)
    else:
        parser.error("Only --raw is available until phase 3.")


if __name__ == "__main__":
    main()
