"""Public demo guard: Basic Auth, login throttle, daily message cap, static widget (ADR 0022).

Author: Ignacio Rodríguez Caro
"""

from __future__ import annotations

import base64
from dataclasses import replace
from datetime import date

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from quilora.agent.loop import Agent
from quilora.agent.session import PostgresSessionStore
from quilora.api.access import BasicAuthMiddleware, LoginThrottle, consume_daily_message
from quilora.api.app import create_app
from quilora.config import load_settings
from quilora.tools import build_registry
from tests.fakes import ScriptedModel, text


def _basic(user: str, password: str) -> dict[str, str]:
    token = base64.b64encode(f"{user}:{password}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture()
def guarded():
    clock = FakeClock()
    app = FastAPI()

    @app.get("/healthz")
    def healthz():
        return {"status": "ok"}

    @app.get("/api/store")
    def store():
        return {"name": "demo"}

    throttle = LoginThrottle(max_failures=3, window_s=60, clock=clock)
    app.add_middleware(BasicAuthMiddleware, username="ana", password="s3cret pass",
                       throttle=throttle)
    return TestClient(app), clock


def test_anonymous_request_gets_a_browser_login_challenge(guarded):
    client, _ = guarded
    res = client.get("/api/store")
    assert res.status_code == 401
    assert res.headers["www-authenticate"].startswith('Basic realm="')


def test_right_credentials_pass_and_wrong_ones_do_not(guarded):
    client, _ = guarded
    assert client.get("/api/store", headers=_basic("ana", "s3cret pass")).json() == {
        "name": "demo"}
    assert client.get("/api/store", headers=_basic("ana", "wrong")).status_code == 401
    assert client.get("/api/store", headers=_basic("bob", "s3cret pass")).status_code == 401


@pytest.mark.parametrize("header", ["Bearer abc", "Basic not-base64!!", "Basic " +
                                    base64.b64encode(b"no-colon").decode()])
def test_malformed_authorization_headers_are_rejected(guarded, header):
    client, _ = guarded
    assert client.get("/api/store", headers={"Authorization": header}).status_code == 401


def test_health_probe_stays_open_for_the_platform(guarded):
    client, _ = guarded
    assert client.get("/healthz").status_code == 200


def test_repeated_wrong_passwords_lock_the_client_out_for_a_while(guarded):
    client, clock = guarded
    for _ in range(3):
        assert client.get("/api/store", headers=_basic("ana", "guess")).status_code == 401
    locked = client.get("/api/store", headers=_basic("ana", "s3cret pass"))
    assert locked.status_code == 429 and int(locked.headers["retry-after"]) > 0

    clock.now += 61
    assert client.get("/api/store", headers=_basic("ana", "s3cret pass")).status_code == 200


def test_the_challenge_itself_does_not_count_as_a_failed_login(guarded):
    client, _ = guarded
    for _ in range(5):
        client.get("/api/store")
    assert client.get("/api/store", headers=_basic("ana", "s3cret pass")).status_code == 200


def test_settings_fail_closed_when_a_login_is_required_but_missing(monkeypatch):
    for key in ("DEMO_USERNAME", "DEMO_PASSWORD"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("REQUIRE_DEMO_AUTH", "1")
    with pytest.raises(ValueError, match="REQUIRE_DEMO_AUTH"):
        load_settings(dotenv_path="/nonexistent")


def test_settings_reject_half_configured_credentials(monkeypatch):
    monkeypatch.setenv("DEMO_USERNAME", "ana")
    monkeypatch.delenv("DEMO_PASSWORD", raising=False)
    with pytest.raises(ValueError, match="both"):
        load_settings(dotenv_path="/nonexistent")


def test_password_is_not_printed_with_the_settings(monkeypatch):
    monkeypatch.setenv("DEMO_USERNAME", "ana")
    monkeypatch.setenv("DEMO_PASSWORD", "s3cret pass")
    monkeypatch.delenv("REQUIRE_DEMO_AUTH", raising=False)
    assert "s3cret" not in repr(load_settings(dotenv_path="/nonexistent"))


# --- needs Postgres ---------------------------------------------------------------------

def _clear_usage(database) -> None:
    with database.connection() as conn:
        conn.execute("DELETE FROM daily_usage")


def test_daily_counter_stops_at_the_limit_and_restarts_the_next_day(database):
    _clear_usage(database)
    day = date(2026, 10, 10)
    assert [consume_daily_message(database, day, 2) for _ in range(3)] == [True, True, False]
    assert consume_daily_message(database, date(2026, 10, 11), 2) is True


def test_chat_returns_429_once_the_daily_limit_is_used(database, settings):
    _clear_usage(database)
    capped = replace(settings, daily_message_limit=1)
    agent = Agent(model=ScriptedModel([text("Hola, ¿en qué te ayudo?")]),
                  registry=build_registry(), settings=capped, db=database)
    app = create_app(capped, agent=agent, store=PostgresSessionStore(database))
    with TestClient(app) as client:
        assert client.post("/api/chat", json={"message": "hola"}).status_code == 200
        blocked = client.post("/api/chat", json={"message": "otra"})
    assert blocked.status_code == 429
    _clear_usage(database)


def test_api_serves_the_built_widget_without_shadowing_the_api(database, settings, tmp_path):
    (tmp_path / "index.html").write_text("<app-root></app-root>", encoding="utf-8")
    hosted = replace(settings, web_dist_dir=str(tmp_path), demo_username="ana",
                     demo_password="s3cret pass")
    agent = Agent(model=ScriptedModel([]), registry=build_registry(), settings=hosted,
                  db=database)
    app = create_app(hosted, agent=agent, store=PostgresSessionStore(database))
    with TestClient(app) as client:
        assert client.get("/").status_code == 401
        page = client.get("/", headers=_basic("ana", "s3cret pass"))
        assert page.status_code == 200 and "app-root" in page.text
        api = client.get("/api/store", headers=_basic("ana", "s3cret pass"))
        assert api.status_code == 200 and "name" in api.json()
