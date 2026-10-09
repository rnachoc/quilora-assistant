"""LLM-as-judge for what deterministic checks cannot see (tone, helpfulness, faithfulness).

Used only for cases with a `judge` rubric and only with `--judge`. The judge receives the
transcript, the tool results and a narrow yes/no rubric, and answers in JSON. Narrow
rubrics are far more reliable than "rate this from 1 to 10". The judge is a different,
cheaper model than the agent (JUDGE_MODEL) to limit cost and self-preference bias.
Judge verdicts should be spot-checked by a human; see docs/evaluation.md.
"""

from __future__ import annotations

import json
import re

import anthropic

from quilora.evals.graders import Check

SYSTEM = (
    "You grade a customer-support assistant of an online fashion store. You receive a "
    "conversation (customer messages, tool results the assistant saw, assistant replies) and "
    "a rubric. Decide strictly whether the FINAL assistant reply satisfies the rubric, using "
    "only the transcript as evidence. Respond with JSON only: "
    '{"pass": true|false, "reason": "<one sentence>"}'
)

SCHEMA = {
    "type": "object",
    "properties": {"pass": {"type": "boolean"}, "reason": {"type": "string"}},
    "required": ["pass", "reason"],
    "additionalProperties": False,
}


def render_transcript(messages: list[dict]) -> str:
    lines = []
    for m in messages:
        if isinstance(m["content"], str):
            lines.append(f"CUSTOMER: {m['content']}")
            continue
        for block in m["content"]:
            if block["type"] == "text":
                lines.append(f"ASSISTANT: {block['text']}")
            elif block["type"] == "tool_use":
                lines.append(f"[assistant calls {block['name']} {json.dumps(block['input'])}]")
            elif block["type"] == "tool_result":
                lines.append(f"[tool result] {block['content'][:1500]}")
    return "\n".join(lines)


class Judge:
    def __init__(self, api_key: str | None, model: str) -> None:
        self.client = anthropic.Anthropic(api_key=api_key, max_retries=2, timeout=60)
        self.model = model

    def evaluate(self, rubric: str, messages: list[dict]) -> Check:
        prompt = f"RUBRIC:\n{rubric}\n\nTRANSCRIPT:\n{render_transcript(messages)}"
        kwargs = {"model": self.model, "max_tokens": 300, "system": SYSTEM,
                  "messages": [{"role": "user", "content": prompt}]}
        try:
            # Structured outputs guarantee valid JSON when the model supports them...
            response = self.client.messages.create(
                **kwargs, output_config={"format": {"type": "json_schema", "schema": SCHEMA}})
        except anthropic.BadRequestError:
            # ...otherwise fall back to asking for JSON and parsing it.
            response = self.client.messages.create(**kwargs)
        text = "".join(b.text for b in response.content if b.type == "text")
        match = re.search(r"\{.*\}", text, re.DOTALL)
        try:
            verdict = json.loads(match.group(0)) if match else {}
            return Check("judge", bool(verdict["pass"]), str(verdict.get("reason", "")))
        except (json.JSONDecodeError, KeyError):
            return Check("judge", False, f"unparseable judge output: {text[:200]}")
