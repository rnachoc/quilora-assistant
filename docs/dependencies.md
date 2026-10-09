# Dependencies

Every dependency must earn its place. Versions are pinned in `pyproject.toml` and were checked
against PyPI on 2026-10-09.

| Package | Version | Phase | Why it is needed | Alternative considered |
|---------|---------|-------|------------------|------------------------|
| pytest | 9.1.1 | 0 | Test runner | unittest (more boilerplate) |
| ruff | 0.16.10 | 0 | Lint + import sorting in one fast tool | flake8 + isort + black |
| psycopg[binary] | 3.3.6 | 1 | PostgreSQL driver (psycopg 3: native async, server-side binding, row factories) | psycopg2 (legacy), SQLAlchemy (ORM not needed for ~10 hand-written queries) |
| psycopg-pool | 3.3.3 | 1 | Connection pool shared by API threads and tools | One connection per request (slow, exhausts connections) |
| anthropic | 1.12.1 | 2 | Official SDK for the Messages API: typed requests, retries with backoff, timeouts | Raw HTTP with httpx (re-implementing retries and types) |
| pydantic | 2.14.0 | 3 | Validates every tool input before it reaches business code; generates the JSON Schema sent to the model, so schema and validation cannot drift | Hand-written JSON Schema + manual checks (two sources of truth) |
| pyyaml | 6.0.3 | 4 | Human-readable labelled query and evaluation case files | JSON (noisier to hand-edit, no comments) |
| fastembed (optional extra) | 0.9.0 | 4 | Local ONNX embedding models, no PyTorch (ADR 0009) | sentence-transformers (PyTorch), Voyage AI API |
