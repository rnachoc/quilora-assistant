# Deploying the hosted demo

A free deployment on [Render](https://render.com) (app) and [Neon](https://neon.com)
(Postgres), behind a login and a daily message cap. Why it is built this way:
[ADR 0022](decisions/0022-hosted-demo.md).

```
browser ──HTTPS──> Render web service (free, Frankfurt)
                   ├─ HTTP Basic Auth (everything except /healthz)
                   ├─ /            built Angular widget
                   └─ /api/*       FastAPI + agent ──> Anthropic API
                                        │
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
   | `ANTHROPIC_API_KEY` | an API key from the Anthropic Console |
   | `DATABASE_URL` | the Neon connection string from step 1 |
   | `DEMO_USERNAME` | the demo login user |
   | `DEMO_PASSWORD` | the demo login password (long and random is best) |

3. Deploy. The first build takes a few minutes. The URL is
   `https://<service-name>.onrender.com`.

## 3. Spending guards

- `DAILY_MESSAGE_LIMIT` (200 in `render.yaml`): messages per day for all visitors together.
- Set a monthly **spend limit** in the Anthropic Console. It is the guard that does not
  depend on this code.

## Operating it

- **Change the password**: edit `DEMO_PASSWORD` in Render → Environment. The service
  restarts with the new value; no code change.
- **Reset the demo data**: run `python -m quilora.seed` against the Neon URL from a laptop
  (reloads catalog and orders, clears returns, tickets and sessions).
- **Free-tier behaviour**: the service sleeps after 15 minutes without traffic; the next
  request waits about a minute while it wakes and runs the (idempotent) migrations.
- **Logs**: Render → Logs. Each turn logs tools, latency and cost; failed logins and the
  daily cap log a warning.
