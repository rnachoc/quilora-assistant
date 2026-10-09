# Phase 9: API, chat widget and Docker Compose

_Author: Ignacio Rodríguez Caro_

## Concept

Until now the agent lived in a terminal. To be a product it needs:

- an **HTTP API** that keeps the conversation per session, so the browser only sends the
  new message and gets the reply (the full history never travels to the client);
- **durable sessions**, so a restart or a second API replica does not lose conversations;
- a **UI** a customer can use;
- **one command** to run everything the same way on any machine.

## What was built

| Path | Content |
|------|---------|
| `src/quilora/api/app.py` | `POST /api/chat`, `GET /api/sessions/{id}`, `/healthz`, `/readyz`, CORS |
| `db/migrations/004_chat_sessions.sql` | Conversation storage with `version` for optimistic locking |
| `agent/session.py` | `PostgresSessionStore` (409 on concurrent update, retention purge) |
| `web/` | Angular 22 storefront + chat widget (suggestions, typing indicator, handoff banner, details toggle) |
| `Dockerfile`, `web/Dockerfile`, `web/nginx.conf` | API image (non-root); static build behind nginx with `/api` proxy |
| `docker-compose.yml` | `db` (pgvector) → `seed` (one-shot) → `api` (health-checked) → `web` |
| `src/quilora/paths.py` | Data/migration paths that work from source and in containers |

## The API contract

```http
POST /api/chat
{"session_id": "optional", "message": "¿Queda la M en negro?"}

200 {"session_id": "...", "reply": "...", "handed_off": false, "ticket_id": null,
     "meta": {"stop_reason": "end_turn", "iterations": 2, "latency_ms": 2140.3,
              "cost_usd": 0.0061, "usage": {...}, "tools": [...], "flags": [], "model": "..."}}
404 unknown session · 409 concurrent update · 422 invalid input
```

## How to run

```bash
cp .env.example .env            # add ANTHROPIC_API_KEY
docker compose up --build       # http://localhost:4200 and http://localhost:8000/docs
```

Without Docker: `make seed && make api` in one terminal, `make web` in another.

## Notes

- The compose file was validated with `docker compose config`; the images could not be
  built in the environment where this was written (no access to Docker Hub). Build it
  once locally before the demo.
- No authentication or rate limiting on `/api/chat`: in production this sits behind an API
  gateway with per-IP and per-session limits, which also caps cost.
