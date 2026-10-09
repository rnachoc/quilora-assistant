"""Phase 7: the evaluation harness itself (case files, graders, runner, report).

Author: Ignacio Rodríguez Caro
"""

from __future__ import annotations

import pytest

from quilora.agent.loop import Agent, ToolCallRecord, TurnResult
from quilora.evals.cases import Case, Expect, load_cases
from quilora.evals.graders import CaseRun, grade
from quilora.evals.report import compare, render_report
from quilora.evals.run import play, summarise
from quilora.tools import build_registry
from tests.fakes import ScriptedModel, text, tool_call


def test_case_files_are_valid_and_cover_every_category():
    cases = load_cases()
    assert 50 <= len(cases) <= 90
    categories = {c.category for c in cases}
    assert categories == {"product_search", "sizing", "stock", "order_status", "returns",
                          "policies", "off_topic", "ambiguous", "attacks", "handoff",
                          "multi_turn", "delivery"}
    assert sum(len(c.turns) > 1 for c in cases) >= 8  # real multi-turn coverage


def test_case_files_only_reference_real_tools():
    tools = {s.name for s in build_registry().specs}
    for case in load_cases():
        expects = [case.expect] + [t.expect for t in case.turns if t.expect]
        for e in expects:
            referenced = set(e.tools_called) | set(e.tools_not_called) | set(e.tool_args)
            assert referenced <= tools, (case.id, referenced - tools)


def _turn(reply, calls=(), **kw):
    return TurnResult(reply=reply, stop_reason="end_turn", tool_calls=[
        ToolCallRecord(name=n, input=i, is_error=bool(err), error_code=err, duration_ms=1,
                       iteration=1) for n, i, err in calls], **kw)


def test_graders_pass_and_fail_precisely():
    expect = Expect(
        tools_called=["search_products"],
        tool_args={"search_products": {"max_price_eur": {"lte": 60}}},
        reply_contains_all=["Garza"], reply_not_contains=["Gala Linen"],
        reply_matches=[r"49,95\s?€"], language="es", flags_exclude=["ungrounded_amount"],
    )
    good = _turn("Tenemos el Garza Linen Midi Dress por 49,95 €.",
                 [("search_products", {"query": "linen dress", "max_price_eur": 60}, None)])
    assert all(c.passed for c in grade(expect, [good], CaseRun([good]), scope="final"))

    bad = _turn("We have the Gala Linen Midi Dress for 74,95 €.",
                [("search_products", {"query": "linen dress"}, None)],
                flags=["ungrounded_amount"])
    failed = {c.name for c in grade(expect, [bad], CaseRun([bad]), scope="final")
              if not c.passed}
    assert failed == {"final:args:search_products", "final:contains:Garza",
                      "final:not_contains:Gala Linen", r"final:matches:49,95\s?€",
                      "final:language:es", "final:no_flag:ungrounded_amount"}


def test_matching_ignores_accents_and_case():
    turn = _turn("Lo siento, esta AGOTADA en arena.")
    checks = grade(Expect(reply_matches=["agotad"], reply_contains_all=["agotada"]), [turn],
                   CaseRun([turn]), scope="final")
    assert all(c.passed for c in checks)


def test_play_runs_a_multi_turn_case_against_the_database(database, settings):
    case = Case.model_validate({
        "id": "t", "category": "returns", "description": "d",
        "turns": [{"user": "devolver camiseta 1043 lucia.romero@example.com",
                   "expect": {"return_created": False}}, "sí"],
        "expect": {"return_created": True, "tools_called": ["create_return_request"]},
    })

    def confirm(messages):
        # Second turn: the scripted model redeems the token from the earlier proposal.
        import json
        for m in reversed(messages):
            if m["role"] == "user" and isinstance(m["content"], list):
                data = json.loads(m["content"][0]["content"])
                if "confirmation_token" in data:
                    return tool_call("create_return_request", {
                        "order_id": 1043, "items": [{"line_no": 1}], "reason": "doesnt_fit",
                        "confirmation_token": data["confirmation_token"]})
        raise AssertionError("no token found")

    model = ScriptedModel([
        tool_call("get_order_status", {"order_id": 1043, "email": "lucia.romero@example.com"}),
        tool_call("create_return_request",
                  {"order_id": 1043, "items": [{"line_no": 1}], "reason": "doesnt_fit"}),
        text("¿Confirmas la devolución?"),
        confirm,
        text("Hecho: RR-XXXX"),
    ])
    agent = Agent(model=model, registry=build_registry(), settings=settings, db=database)
    outcome = play(agent, database, case, attempt=1, judge=None)
    assert outcome["passed"], [c for c in outcome["checks"] if not c["passed"]]


@pytest.fixture()
def fake_results():
    def make(passed_ids):
        cases = [{"id": i, "category": "stock", "description": "", "passed": i in passed_ids,
                  "consistency": "1/1",
                  "attempts": [{"passed": i in passed_ids, "checks": [
                      {"name": "final:x", "passed": i in passed_ids, "detail": ""}],
                      "error": None, "turns": [{"user": "u", "reply": "r", "tools": [],
                                                "latency_ms": 900, "cost_usd": 0.01,
                                                "usage": {"input_tokens": 10}, "flags": [],
                                                "stop_reason": "end_turn", "iterations": 1,
                                                "handed_off": False}]}]}
                 for i in ("a", "b", "c")]
        meta = {"model": "m", "git_commit": "x", "prompt_sha": "p", "tools_sha": "t",
                "policy_search_backend": "fts", "repeat": 1, "pricing_verified": False}
        return {"meta": meta, "summary": summarise(cases), "cases": cases}
    return make


def test_report_compares_with_baseline(fake_results):
    baseline = fake_results({"a", "b"})
    current = fake_results({"a", "c"})
    diff = compare(current, baseline)
    assert diff["regressions"] == ["b"] and diff["fixed"] == ["c"]
    report = render_report(current, baseline)
    assert "Regressions (1): b" in report and "unverified price table" in report
    assert "| stock | 2/3 | 67% | = |" in report
