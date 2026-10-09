"""Deterministic guardrails around the model.

Defence in depth, from strongest to weakest:

1. Tools enforce authorisation and consent (phases 3 and 5). Even a fully "jailbroken"
   model cannot read another customer's order or create an unconfirmed return. This is
   the layer that actually limits the blast radius.
2. Input guard (here): redacts payment-card numbers, IBANs and Spanish ID numbers BEFORE
   they reach the model, the logs or the stored history; flags likely injection attempts.
3. Output guard (here): blocks replies that leak the system prompt or hand out discount
   codes, and flags amounts not backed by any tool result.
4. The system prompt (weakest: it is a request, not a control).

Heuristics in layers 2-3 have false positives and negatives. That is why injection
detection only *flags* (for monitoring and evals) instead of blocking, and only
high-precision checks block.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# Placed in the system prompt; if it ever appears in a reply, the prompt is leaking.
PROMPT_CANARY = "QLR-CANARY-7F3A"

_CARD = re.compile(r"(?<!\d)(?:\d[ -]?){13,19}(?!\d)")
_IBAN = re.compile(r"\b[A-Z]{2}\d{2}(?:\s?[A-Z0-9]{4}){3,7}(?:\s?[A-Z0-9]{1,4})?\b")
_DNI_NIE = re.compile(r"\b(?:\d{8}|[XYZ]\d{7})-?[A-Z]\b", re.IGNORECASE)

_INJECTION_PATTERNS = [
    r"ignore (all |any |the )?(previous|prior|above|your) (instructions|rules|prompt)",
    r"disregard (all |the )?(previous|above|your) (instructions|rules)",
    r"(reveal|show|print|repeat) (me )?(your|the) (system )?(prompt|instructions)",
    r"you are now\b", r"developer mode", r"admin mode", r"system override", r"jailbreak",
    r"ignora (todas |las )?(tus |las )?(instrucciones|reglas)",
    r"olvida (todas |las )?(tus |las )?(instrucciones|reglas)",
    r"(muestra|dime|ens[eé]ñame|repite) (tu|el) (prompt|system prompt|instrucciones)",
    r"modo (administrador|admin|desarrollador)", r"ahora eres\b", r"act[uú]a como",
]
_INJECTION = re.compile("|".join(f"(?:{p})" for p in _INJECTION_PATTERNS), re.IGNORECASE)

_CODE_CONTEXT = re.compile(r"c[oó]digo|cup[oó]n|coupon|promo|discount|descuento|voucher",
                           re.IGNORECASE)
_CODE_TOKEN = re.compile(r"(?<![-\w])(?=[A-Z0-9]*\d)(?=[A-Z0-9]*[A-Z])[A-Z0-9]{4,12}(?![-\w])")
_NUM = r"(\d{1,5}(?:[.,]\d{1,2})?)"
# "49,95 €", "49.95 EUR", "60 euros" or "€49.95"
_AMOUNT = re.compile(rf"(?:€\s?)?{_NUM}\s?(?:€|eur\b|euros?\b)|€\s?{_NUM}", re.IGNORECASE)

BLOCKED_REPLY = {
    "es": "Lo siento, no puedo ayudarte con eso. Puedo ayudarte con productos, tallas, pedidos, "
          "devoluciones y políticas de Quilora.",
    "en": "Sorry, I can't help with that. I can help with Quilora products, sizes, orders, "
          "returns and policies.",
}
NO_DISCOUNT_REPLY = {
    "es": "No puedo dar ni aplicar códigos de descuento. Las promociones se publican solo en "
          "nuestra newsletter y en la web (Política de pagos §3).",
    "en": "I can't give or apply discount codes. Promotions are published only in our "
          "newsletter and on the website (Payments Policy §3).",
}


@dataclass
class GuardResult:
    text: str
    flags: list[str] = field(default_factory=list)
    blocked: bool = False


def _luhn_ok(digits: str) -> bool:
    total, parity = 0, len(digits) % 2
    for i, ch in enumerate(digits):
        d = int(ch)
        if i % 2 == parity:
            d = d * 2 - 9 if d > 4 else d * 2
        total += d
    return total % 10 == 0


def check_input(text: str) -> GuardResult:
    flags: list[str] = []

    def redact_card(match: re.Match) -> str:
        digits = re.sub(r"\D", "", match.group(0))
        if 13 <= len(digits) <= 19 and _luhn_ok(digits):
            flags.append("pii_card_redacted")
            return "[CARD NUMBER REDACTED]"
        return match.group(0)

    cleaned = _CARD.sub(redact_card, text)
    if _IBAN.search(cleaned):
        cleaned = _IBAN.sub("[IBAN REDACTED]", cleaned)
        flags.append("pii_iban_redacted")
    if _DNI_NIE.search(cleaned):
        cleaned = _DNI_NIE.sub("[ID NUMBER REDACTED]", cleaned)
        flags.append("pii_id_redacted")
    if _INJECTION.search(cleaned):
        flags.append("possible_injection")
    return GuardResult(cleaned, sorted(set(flags)))


def normalise_amount(raw: str) -> str:
    value = raw.replace(",", ".")
    return f"{float(value):.2f}"


def amounts_in(text: str) -> set[str]:
    found = set()
    for match in _AMOUNT.finditer(text):
        raw = match.group(1) or match.group(2)
        if raw:
            found.add(normalise_amount(raw))
    return found


def numbers_in(text: str) -> set[str]:
    """Every number in tool results/user text, normalised like amounts (JSON has no €)."""
    return {normalise_amount(n) for n in re.findall(r"\d{1,5}(?:[.,]\d{1,2})?", text)}


def check_output(reply: str, *, grounding_text: str, lang: str) -> GuardResult:
    """`grounding_text`: tool results and customer messages of the conversation so far."""
    flags: list[str] = []

    if PROMPT_CANARY in reply or "Rules you must always follow" in reply:
        return GuardResult(BLOCKED_REPLY[lang], ["prompt_leak_blocked"], blocked=True)

    if _CODE_CONTEXT.search(reply):
        suspicious = [t for t in _CODE_TOKEN.findall(reply) if t not in grounding_text]
        if suspicious:
            return GuardResult(NO_DISCOUNT_REPLY[lang], ["discount_code_blocked"], blocked=True)

    known = numbers_in(grounding_text)
    ungrounded = sorted(a for a in amounts_in(reply) if a not in known)
    if ungrounded:
        flags.append("ungrounded_amount")

    if re.search(r"[\w.+-]+@[\w-]+\.[\w.]+", reply):
        flags.append("email_in_reply")
    return GuardResult(reply, flags)


def grounding_text(messages: list[dict]) -> str:
    """Concatenate customer messages and tool results: the only legitimate sources of facts."""
    parts: list[str] = []
    for m in messages:
        if m["role"] != "user":
            continue
        if isinstance(m["content"], str):
            parts.append(m["content"])
        else:
            parts.extend(str(b.get("content", "")) for b in m["content"]
                         if b.get("type") == "tool_result")
    return "\n".join(parts)
