"""The agent loop: one customer message in, one reply out.

    user message
      -> [model] -> text?        -> reply, done
                 -> tool_use?    -> registry validates + executes each call
                                 -> tool_result blocks go back to the model
                                 -> repeat (at most AGENT_MAX_ITERATIONS model calls)

Everything that can go wrong has an explicit, non-model fallback: the model API failing,
the iteration budget running out, or the output being truncated. The conversation history
is always left valid (every tool_use has its tool_result, roles alternate), so the next
turn can continue normally.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any

from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode

from quilora.agent.guardrails import check_input, check_output, grounding_text
from quilora.agent.model import ModelClient, ModelError, TokenUsage
from quilora.agent.pricing import estimate_cost_usd
from quilora.agent.prompts import render
from quilora.agent.session import Conversation
from quilora.config import Settings
from quilora.db import Database
from quilora.observability import redact
from quilora.tools.base import ToolContext, ToolRegistry

log = logging.getLogger(__name__)

MAX_USER_MESSAGE_CHARS = 2000
MAX_TURNS_PER_CONVERSATION = 30

FALLBACK_MODEL_ERROR = {
    "es": "Lo siento, ahora mismo tengo un problema técnico. ¿Puedes intentarlo de nuevo en un "
          "momento?",
    "en": "Sorry, I'm having a technical problem right now. Could you try again in a moment?",
}
FALLBACK_GAVE_UP = {
    "es": "Lo siento, no he podido resolver esto. Puedo pasar tu caso al equipo de atención al "
          "cliente para que lo revise una persona.",
    "en": "Sorry, I couldn't resolve this. I can pass your case to our support team so a "
          "person can review it.",
}
MESSAGE_TOO_LONG = {
    "es": "Tu mensaje es demasiado largo. ¿Puedes resumirlo en unas líneas?",
    "en": "Your message is too long. Could you summarise it in a few lines?",
}
CONVERSATION_TOO_LONG = {
    "es": "Esta conversación es ya muy larga. Por favor, abre una nueva o pide que te pase con "
          "una persona.",
    "en": "This conversation is very long now. Please start a new one or ask me to transfer "
          "you to a person.",
}


def guess_language(text: str) -> str:
    """Cheap heuristic used only for canned fallback messages (the model handles the rest)."""
    lowered = f" {text.lower()} "
    spanish_markers = (" el ", " la ", " de ", " que ", " mi ", " por ", " para ", " tengo ",
                       " quiero ", "¿", "ñ", " hola", " gracias", " pedido", " talla")
    return "es" if any(m in lowered for m in spanish_markers) else "en"


@dataclass
class ToolCallRecord:
    name: str
    input: dict[str, Any]
    is_error: bool
    error_code: str | None
    duration_ms: float
    iteration: int


@dataclass
class TurnResult:
    reply: str
    stop_reason: str  # end_turn | max_iterations | model_error | max_tokens | rejected_input
    iterations: int = 0
    tool_calls: list[ToolCallRecord] = field(default_factory=list)
    usage: TokenUsage = field(default_factory=TokenUsage)
    cost_usd: float | None = 0.0
    latency_ms: float = 0.0
    model: str = ""
    flags: list[str] = field(default_factory=list)
    handed_off: bool = False
    ticket_id: str | None = None


class Agent:
    def __init__(
        self,
        model: ModelClient,
        registry: ToolRegistry,
        settings: Settings,
        db: Database,
        prompt_name: str = "system",
        embedder: Any = None,
        tracer: trace.Tracer | None = None,
    ) -> None:
        self.model = model
        self.registry = registry
        self.settings = settings
        self.db = db
        self.prompt_name = prompt_name
        self.embedder = embedder
        self._tools = registry.definitions()
        # The global tracer is a no-op unless observability.setup_tracing() installed one.
        self.tracer = tracer or trace.get_tracer("quilora.agent")

    def system_prompt(self) -> str:
        return render(self.prompt_name, today=self.settings.today())

    def run_turn(self, conv: Conversation, user_text: str) -> TurnResult:
        with self.tracer.start_as_current_span("chat.turn") as span:
            result = self._run_turn(conv, user_text)
            span.set_attributes({
                "session.id": conv.id,
                "quilora.turn.index": conv.turn_count,
                "quilora.turn.stop_reason": result.stop_reason,
                "quilora.turn.iterations": result.iterations,
                "quilora.turn.tool_calls": len(result.tool_calls),
                "quilora.turn.latency_ms": round(result.latency_ms, 1),
                "quilora.turn.cost_usd": result.cost_usd or 0.0,
                "quilora.turn.handed_off": result.handed_off,
                "quilora.turn.flags": result.flags,
                "gen_ai.usage.input_tokens": result.usage.input_tokens,
                "gen_ai.usage.output_tokens": result.usage.output_tokens,
                "quilora.usage.cache_read_input_tokens": result.usage.cache_read_input_tokens,
                "quilora.usage.cache_creation_input_tokens":
                    result.usage.cache_creation_input_tokens,
            })
            if result.stop_reason in {"model_error", "max_iterations"}:
                span.set_status(Status(StatusCode.ERROR, result.stop_reason))
            return result

    def _call_model(self, system: str, conv: Conversation):
        name = f"chat {self.model.model}"
        with self.tracer.start_as_current_span(name, kind=trace.SpanKind.CLIENT) as span:
            span.set_attributes({
                "gen_ai.operation.name": "chat",
                "gen_ai.provider.name": "anthropic",
                "gen_ai.request.model": self.model.model,
                "gen_ai.request.max_tokens": self.settings.agent_max_tokens,
            })
            try:
                response = self.model.create(system=system, messages=conv.messages,
                                             tools=self._tools,
                                             max_tokens=self.settings.agent_max_tokens)
            except ModelError as exc:
                span.set_status(Status(StatusCode.ERROR, str(exc)))
                raise
            span.set_attributes({
                "gen_ai.response.model": response.model,
                "gen_ai.response.finish_reasons": [response.stop_reason],
                "gen_ai.usage.input_tokens": response.usage.input_tokens,
                "gen_ai.usage.output_tokens": response.usage.output_tokens,
                "quilora.usage.cache_read_input_tokens": response.usage.cache_read_input_tokens,
                "quilora.model.latency_ms": round(response.latency_ms, 1),
            })
            return response

    def _execute_tool(self, call: dict, ctx: ToolContext):
        with self.tracer.start_as_current_span(f"execute_tool {call['name']}") as span:
            span.set_attributes({
                "gen_ai.operation.name": "execute_tool",
                "gen_ai.tool.name": call["name"],
                "gen_ai.tool.call.id": call["id"],
                "quilora.tool.arguments": json.dumps(redact(call["input"]), ensure_ascii=False),
            })
            outcome = self.registry.execute(call["name"], call["input"], ctx)
            span.set_attribute("quilora.tool.duration_ms", round(outcome.duration_ms, 1))
            if outcome.is_error:
                span.set_attribute("error.type", outcome.error_code or "tool_error")
                span.set_status(Status(StatusCode.ERROR, outcome.error_code))
            return outcome

    def _run_turn(self, conv: Conversation, user_text: str) -> TurnResult:
        started = time.perf_counter()
        user_text = (user_text or "").strip()
        lang = guess_language(user_text)

        rejected = self._check_input(conv, user_text, lang)
        if rejected:
            return rejected

        # Input guard: redact card/IBAN/ID numbers before the model, logs or history see them.
        guarded_input = check_input(user_text)
        conv.turn_count += 1
        conv.messages.append({"role": "user", "content": guarded_input.text})
        result = TurnResult(reply="", stop_reason="end_turn", model=self.model.model,
                            flags=list(guarded_input.flags))
        ctx = ToolContext(db=self.db, settings=self.settings, state=conv.state,
                          session_id=conv.id, turn_index=conv.turn_count, embedder=self.embedder)
        system = self.system_prompt()

        for iteration in range(1, self.settings.agent_max_iterations + 1):
            result.iterations = iteration
            try:
                response = self._call_model(system, conv)
            except ModelError as exc:
                log.warning("Model error in session %s: %s", conv.id, exc)
                result.stop_reason = "model_error"
                result.reply = FALLBACK_MODEL_ERROR[lang]
                break

            result.usage = result.usage + response.usage
            conv.messages.append({"role": "assistant", "content": response.content or
                                  [{"type": "text", "text": "..."}]})

            if response.stop_reason == "tool_use" and response.tool_uses:
                tool_results = []
                for call in response.tool_uses:
                    outcome = self._execute_tool(call, ctx)
                    result.tool_calls.append(ToolCallRecord(
                        name=call["name"], input=call["input"], is_error=outcome.is_error,
                        error_code=outcome.error_code, duration_ms=outcome.duration_ms,
                        iteration=iteration))
                    if call["name"] == "handoff_to_human" and not outcome.is_error:
                        result.handed_off = True
                        result.ticket_id = outcome.payload.get("ticket_id")
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": call["id"],
                        "content": outcome.content(),
                        "is_error": outcome.is_error,
                    })
                conv.messages.append({"role": "user", "content": tool_results})
                continue

            if response.stop_reason == "max_tokens":
                result.stop_reason = "max_tokens"
                if response.tool_uses:  # a truncated tool call must never be executed
                    conv.messages.pop()
                    result.reply = FALLBACK_GAVE_UP[lang]
                else:
                    result.reply = response.text
                break

            result.reply = response.text
            result.stop_reason = "end_turn"
            self._guard_output(conv, result, lang)
            break
        else:
            result.stop_reason = "max_iterations"
            result.reply = FALLBACK_GAVE_UP[lang]

        if result.stop_reason in {"model_error", "max_iterations"} or (
            result.stop_reason == "max_tokens" and conv.messages[-1]["role"] == "user"
        ):
            # Keep the history valid: close the turn with our own assistant message.
            conv.messages.append({"role": "assistant",
                                  "content": [{"type": "text", "text": result.reply}]})

        result.cost_usd = estimate_cost_usd(self.model.model, result.usage)
        result.latency_ms = (time.perf_counter() - started) * 1000
        return result

    def _guard_output(self, conv: Conversation, result: TurnResult, lang: str) -> None:
        """Output guard: block prompt leaks and discount codes, flag ungrounded amounts."""
        guarded = check_output(result.reply, grounding_text=grounding_text(conv.messages),
                               lang=lang)
        result.flags.extend(guarded.flags)
        if guarded.blocked:
            result.reply = guarded.text
            # Store the safe text, so the blocked content never re-enters the context.
            conv.messages[-1] = {"role": "assistant",
                                 "content": [{"type": "text", "text": guarded.text}]}

    def _check_input(self, conv: Conversation, text: str, lang: str) -> TurnResult | None:
        if not text:
            return TurnResult(reply="", stop_reason="rejected_input", flags=["empty_input"])
        if len(text) > MAX_USER_MESSAGE_CHARS:
            return TurnResult(reply=MESSAGE_TOO_LONG[lang], stop_reason="rejected_input",
                              flags=["input_too_long"])
        if conv.turn_count >= MAX_TURNS_PER_CONVERSATION:
            return TurnResult(reply=CONVERSATION_TOO_LONG[lang], stop_reason="rejected_input",
                              flags=["conversation_too_long"])
        return None
