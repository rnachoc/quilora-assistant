# 0022. A free hosted demo behind a login and a spending cap

- **Status:** Accepted
- **Date:** 2026-10-10
- **Author:** Ignacio Rodríguez Caro

## Context

The assistant should be reachable from a real URL so reviewers can try it without cloning
the repository. Hosting can be free, but every customer message is a paid call to the
Anthropic API on the owner's key. A public, unauthenticated chat endpoint would invite bots
and could spend the API budget. The known-limitations list already said "no authentication
or rate limiting on the public endpoint".

## Options

1. **Hosting**
   - *Render free web service + Neon free Postgres*: no cost, Docker deploy from GitHub,
     pgvector available on Neon. The instance sleeps after 15 minutes idle (about a minute
     to wake) and has 512 MB of memory.
   - *Render free Postgres*: simpler, but free databases expire after 30 days.
   - *A paid instance*: always on, but costs money for a portfolio demo.
2. **Access control**
   - *HTTP Basic Auth on the whole site*: the browser's own login dialog, no dependencies,
     protects the widget and the API with one check. Looks plain and has no logout.
   - *A custom login page with a session cookie*: nicer for a demo, but more code and more
     attack surface (CSRF, cookie flags, session storage) to defend.
3. **Spending guard**: a daily message cap in the application, an access code, the
   Anthropic Console spend limit, or a combination.

## Decision

Render free web service with Neon free Postgres, deployed from `render.yaml`. One service
serves both the API and the built Angular widget (`deploy/Dockerfile.render`), so a single
HTTP Basic Auth layer protects everything except `/healthz` (the platform's probe), with
no CORS and no second host.

Defence in layers:

- **Login** (`DEMO_USERNAME` / `DEMO_PASSWORD`, secrets set in the Render dashboard, never
  in the repository). Constant-time comparison; after 10 wrong passwords in 15 minutes the
  client IP gets `429` for the rest of the window.
- **Fail closed**: `REQUIRE_DEMO_AUTH=1` makes the app refuse to start without credentials,
  so a forgotten variable cannot leave the demo open.
- **Daily cap** (`DAILY_MESSAGE_LIMIT`, 200 by default in the deploy): an atomic upsert in
  Postgres, so it survives the restarts that sleeping causes. It counts by the real
  calendar day, not `STORE_TODAY`, which is frozen for reproducible data.
- **Anthropic Console spend limit**: the last line, independent of this code.

Policy search runs on Postgres FTS in the hosted demo (ADR 0008's default): the embedding
model does not fit comfortably in 512 MB. Data is seeded on start only when the database
is empty (`seed --if-empty`), so restarts keep conversations, returns and tickets.

## Consequences

- Reviewers get a working URL at no hosting cost; the first request after idle is slow.
- Basic Auth credentials travel on every request, which is acceptable only over HTTPS
  (Render terminates TLS). A shared demo password is a bot filter, not user accounts.
- The login throttle is in memory: a restart clears it. It keys on the client IP reported
  by the platform proxy (`uvicorn --proxy-headers`).
- The cap is global, so one heavy visitor can use the day's quota for everyone. Fine for a
  demo; a real deployment would rate-limit per user at the gateway.
- Local development is unchanged: without credentials there is no login and no cap.

## Amendment (2026-10-10): public landing page

The product page (`site/index.html`) is served at `/` without login, and the widget moved to
`/demo/`. The page is static and makes no server calls, so making it public adds no cost or
attack surface; the widget and every `/api/*` route still require the login.
