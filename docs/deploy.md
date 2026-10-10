# Deploying the hosted demo

A free deployment on [Render](https://render.com) (app) and [Neon](https://neon.com)
(Postgres), behind a login and a daily message cap. Why it is built this way:
[ADR 0022](decisions/0022-hosted-demo.md). It runs the scripted demo model, so it makes no
model API calls and needs no Anthropic key ([ADR 0023](decisions/0023-scripted-demo-model.md)).

```
browser ──HTTPS──> Render web service (free, Frankfurt)
                   ├─ HTTP Basic Auth (everything except /healthz)
                   ├─ /            built Angular widget
                   └─ /api/*       FastAPI + agent ──> scripted demo model
                                        │                 (or Claude, AGENT_MODE=live)
                                        └──> Neon Postgres (free)
```

## 1. Database (Neon)

1. Create a project (region close to Frankfurt, e.g. AWS eu-central-1).
2. Copy the connection string of the **direct** endpoint (host without `-pooler`). The
   app keeps its own connection pool; prefer the direct endpoint over PgBouncer's
   transaction mode.
3. Nothing else: migrations and the synthetic data are applied by the app on first start.

## 2. App (Render Blueprint)

1. Render dashboard → **New → Blueprint** → pick this repository. Render reads
   [`render.yaml`](../render.yaml).
2. It asks for the secret variables:

   | Variable | Value |
   |---|---|
   | `DATABASE_URL` | the Neon connection string from step 1 |
   | `DEMO_USERNAME` | the demo login user |
   | `DEMO_PASSWORD` | the demo login password (long and random is best) |

3. Deploy. The first build takes a few minutes. The URL is
   `https://<service-name>.onrender.com`.

## 3. Guards

- `DAILY_MESSAGE_LIMIT` (200 in `render.yaml`): messages per day for all visitors together.
  In scripted mode it protects the free database compute; with Claude it caps spending.

## Switching to Claude

Set `AGENT_MODE=live` and add `ANTHROPIC_API_KEY` in Render → Environment. Before doing so,
set a monthly **spend limit** in the Anthropic Console: it is the guard that does not depend
on this code.

## Operating it

- **Change the password**: edit `DEMO_PASSWORD` in Render → Environment. The service
  restarts with the new value; no code change.
- **Reset the demo data**: in scripted mode returns, tickets and sessions are cleared on
  every start. To reload catalog and orders too, run `python -m quilora.seed` against the
  Neon URL from a laptop.
- **Free-tier behaviour**: the service sleeps after 15 minutes without traffic; the next
  request waits about a minute while it wakes and runs the (idempotent) migrations.
- **Logs**: Render → Logs. Each turn logs tools, latency and cost; failed logins and the
  daily cap log a warning.
