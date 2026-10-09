"""Terminal chat for local experiments.

    python -m quilora.cli            # full agent with tools
    python -m quilora.cli --raw      # model only, no tools (phase 2 experiment)
    python -m quilora.cli --verbose  # also print tool inputs

Author: Ignacio Rodríguez Caro
"""

from __future__ import annotations

import argparse
import json

from quilora.agent.model import AnthropicModelClient, TokenUsage
from quilora.agent.pricing import PRICING_VERIFIED, estimate_cost_usd
from quilora.agent.prompts import render
from quilora.agent.session import Conversation
from quilora.bootstrap import build_agent
from quilora.config import load_settings
from quilora.observability import setup_tracing


def _read() -> str | None:
    """Read one line from the terminal; None on Ctrl-D."""
    try:
        return input("you> ").strip()
    except EOFError:
        return None


def raw_chat(prompt_name: str) -> None:
    """Plain model call with a system prompt and no tools, to observe the model's limits."""
    settings = load_settings()
    client = AnthropicModelClient(settings.anthropic_api_key, settings.agent_model,
                                  settings.model_timeout_s)
    system = render(prompt_name, today=settings.today(), store=settings.store)
    history: list[dict] = []
    total = TokenUsage()
    print(f"Raw chat with {settings.agent_model} (prompt: {prompt_name}). Ctrl-D to exit.\n")
    while (user := _read()) is not None:
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


def agent_chat(verbose: bool) -> None:
    """Interactive terminal chat with the full agent, printing tools, latency and cost per turn."""
    settings = load_settings()
    setup_tracing(settings)
    agent = build_agent(settings)
    conv = Conversation()
    print(f"{settings.store.name} assistant ({settings.agent_model}). Ctrl-D to exit.")
    if not PRICING_VERIFIED:
        print("(cost figures use an unverified price table, see agent/pricing.py)")
    print()
    while (user := _read()) is not None:
        if not user:
            continue
        result = agent.run_turn(conv, user)
        print(f"\nassistant> {result.reply}\n")
        for call in result.tool_calls:
            status = f"ERROR {call.error_code}" if call.is_error else "ok"
            args = f" {json.dumps(call.input, ensure_ascii=False)}" if verbose else ""
            print(f"  · {call.name}{args} -> {status} ({call.duration_ms:.0f} ms)")
        print(f"  [{result.stop_reason} | {result.iterations} model calls | "
              f"{result.latency_ms:.0f} ms | in {result.usage.input_tokens} "
              f"(cache read {result.usage.cache_read_input_tokens}) out "
              f"{result.usage.output_tokens} | ~${result.cost_usd}]\n")


def main() -> None:
    """Command-line entry point."""
    parser = argparse.ArgumentParser(description="Store assistant in the terminal")
    parser.add_argument("--raw", action="store_true", help="model only, no tools (phase 2)")
    parser.add_argument("--prompt", default="minimal", help="prompt template for --raw")
    parser.add_argument("--verbose", action="store_true", help="print tool inputs")
    args = parser.parse_args()
    if args.raw:
        raw_chat(args.prompt)
    else:
        agent_chat(args.verbose)


if __name__ == "__main__":
    main()
