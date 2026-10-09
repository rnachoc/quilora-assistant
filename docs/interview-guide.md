# How I would explain this in 10 minutes

## Structure

| Minute | Topic | Key sentence |
|--------|-------|--------------|
| 0–1 | Problem | "A support assistant must be useful *and* truthful *and* safe. Prompting alone gives you two of the three." |
| 1–3 | Architecture | Widget → FastAPI → agent loop ↔ Claude; loop → tool registry → Postgres. Same registry behind an MCP server. |
| 3–5 | Three ideas | (1) The model proposes, the code decides. (2) Quality comes from tool design. (3) Measured with evals. |
| 5–7 | Evaluation | 72 cases, deterministic graders on behaviour and database effects, baseline, CI. Retrieval benchmark with numbers. |
| 7–9 | Production | Cost and latency per turn, caching, timeouts and fallbacks, idempotency, PII, traces, Docker. |
| 9–10 | Limits and next steps | What is not measured yet, what I would do next, what I learned. |

## The three ideas, with one concrete example each

1. **The model proposes, the code decides.** `create_return_request` issues a token that
   is only redeemable in a later customer turn. Even a manipulated model cannot complete a
   return without the customer replying after seeing the summary. A test drives a scripted
   "malicious" model that tries, and the tool refuses.
2. **Quality comes from tool design.** `get_order_status` returns the same error for "no
   such order" and "wrong email", so it cannot be used to enumerate orders; that is a
   property of the tool, not something I can ask a prompt to guarantee.
3. **Measured, not demoed.** Each eval case checks behaviour (tools, arguments, database
   effects), runs in CI on every change to prompt, tools or model, and is compared with a
   committed baseline.

## Hard questions and how I would answer

**Why not LangChain or another framework?**
The loop is ~150 lines and it is where the important decisions live: iteration budget,
error shaping, confirmation gates, tracing. I wanted to own and understand it. With more
agents or streaming I would re-evaluate the SDK's tool runner or the Agent SDK (ADR 0004).

**Your main stack is Java. Why Python?**
The official SDK, the MCP SDK and the embedding tooling are Python-first, and keeping the
mechanics explicit was the goal. The design (registry, validated DTOs, invariants in the
service layer, optimistic locking) is what I would build in Spring Boot too (ADR 0002).

**Why not a cheap model to route intents first?**
Choosing a tool already is intent classification; a router adds a round trip to every turn
and a new failure mode. I made the model configurable and the eval suite can compare Sonnet
and Haiku per category; I would decide with those numbers (ADR 0003).

**Can you prevent prompt injection?**
Not completely, and I would not claim it. I reduce the blast radius: tools enforce
authorisation and consent, untrusted data is labelled, high-precision output checks block
leaks and invented codes, and each attack type is an eval case. Detection heuristics only
flag, because blocking them would hurt real customers (ADR 0012).

**The customer says "vale, ¿y cuánto tarda?" after the summary. Is that a yes?**
No, and there is an eval case for it. The code guarantees that a reply *happened*; the model
interprets it. If that interpretation fails in evals, the fix is out-of-band confirmation:
Confirm/Cancel buttons that call the API directly (ADR 0010, option 4).

**How do you know your eval suite is any good?**
Cases come from business rules and from the brief; every category includes negative and
adversarial cases; checks are behavioural; I read failing transcripts before changing
anything. Its limits: 72 cases is small (one case ≈ 1.4 points), regexes are brittle, and
the LLM judge is not yet calibrated against human labels.

**LLMs are non-deterministic. Doesn't that make CI flaky?**
I use thresholds plus a regression diff, `--repeat N` with "pass only if all attempts
pass", and I treat small deltas as noise. Cases that flip without code changes are
signals: either the behaviour is genuinely unstable or the check is too strict.

**What does a conversation cost and how would you reduce it?**
The report gives cost per conversation and per category. Levers, in order: prompt
caching of the static prefix (~3.6k tokens of tools and prompt), fewer iterations through
better tool descriptions, compact tool outputs, a cheaper model where evals allow it,
shorter replies. One caveat I verified in code: the pricing table is unverified until
checked against the official page.

**Latency?**
Most time is model calls; tool calls take milliseconds (visible in traces). Next steps:
streaming replies, executing the tool calls of one model response concurrently (the loop
already accepts several per response but runs them in sequence), and keeping the cache warm.

**Why Postgres full-text search instead of Elasticsearch/OpenSearch?**
42 policy sections do not justify another cluster. I measured FTS: perfect on keyword
queries, weak on paraphrases and Spanish. The model rewrites queries into English
keywords before calling the tool, which closes much of that gap. I would move to OpenSearch
with a much larger corpus, multilingual analyzers or relevance tuning needs (ADR 0005, 0008).

**RAG and vector databases?**
These were new to me; I built the comparison to learn them properly: chunking by citable
section, a multilingual embedding model with a 128-token limit (so chunks stay short),
cosine distance with pgvector, hybrid with Reciprocal Rank Fusion, and Hit@k and MRR on a
labelled query set. No ANN index on purpose: with 42 rows an exact scan is faster and exact.

**What if the Anthropic API is down or slow?**
SDK retries with backoff for transient errors and a client timeout; the loop answers with
a canned message and keeps the history valid so the next turn works. In production I would
add a circuit breaker and alerting on error rate.

**Personal data / GDPR?**
Data minimisation: only order number and email are requested; card, IBAN and ID numbers
are redacted before the model, logs and storage; emails are masked in tool output and
traces; message text is not traced; a retention purge exists for sessions. Provider-side
retention and data-processing terms would be reviewed with legal for a real client.

**How would you deploy it on AWS or Kubernetes?**
The API is stateless (sessions in Postgres), so it scales horizontally: a Deployment with
an HPA, RDS for PostgreSQL with pgvector, the API key in Secrets Manager or a Kubernetes
secret, an OpenTelemetry Collector shipping traces, the widget on a CDN, rate limiting at
the gateway. The seed job becomes a migration Job.

**Where would Kafka or events fit?**
Return requests and tickets are natural events: write them with an outbox (the audit log
is already in the same transaction) and publish `return.requested` / `ticket.opened` to
Kafka for the warehouse and helpdesk instead of having the assistant call them directly.

**What did you decide yourself versus what the AI suggested?**
Answer honestly from the ADRs: which defaults I accepted, which I changed and why. Examples
of judgment over suggestions worth mentioning only if true for you: verifying model IDs and
SDK APIs against the installed packages (the MCP SDK 2.x renamed `FastMCP` to `MCPServer`),
refusing to present unverified prices as facts, keeping injection detection as a flag.

**What would you do differently?**
Start the eval cases even earlier (before the tools), and design the confirmation as an
out-of-band UI action from day one.

**How would you measure it in production?**
Containment (resolved without handoff), handoff rate and reasons, return completion rate,
guardrail flag rates, cost per resolved conversation, p95 latency, and a weekly human
review sample, especially for money and personal-data conversations.
