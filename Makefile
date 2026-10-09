# Common tasks. Run `make help` to list them.
.DEFAULT_GOAL := help
PY ?= python

help: ## List available targets
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-18s %s\n", $$1, $$2}'

install: ## Install the package with dev dependencies (inside a virtualenv)
	$(PY) -m pip install -e ".[dev]"

hooks: ## Install a git pre-push hook that runs the secret scan
	printf '#!/bin/sh\nexec scripts/check_secrets.sh\n' > .git/hooks/pre-push && chmod +x .git/hooks/pre-push

secrets-check: ## Scan tracked files for secrets
	scripts/check_secrets.sh

lint: ## Lint with ruff
	ruff check src tests data

test: ## Run the test suite
	$(PY) -m pytest -q

data: ## Regenerate the synthetic dataset (deterministic)
	$(PY) data/generate.py

seed: ## Create the schema and load the synthetic data into Postgres
	$(PY) -m quilora.seed

chat-raw: ## Phase 2: chat with the model, no tools
	$(PY) -m quilora.cli --raw

chat: ## Chat with the full agent in the terminal (needs ANTHROPIC_API_KEY)
	$(PY) -m quilora.cli --verbose

embed: ## Compute policy embeddings (needs: pip install -e '.[embeddings]')
	$(PY) -m quilora.search.embed

compare-search: ## Compare FTS, vector and hybrid policy retrieval; update docs/results
	$(PY) -m quilora.search.compare --write

eval-validate: ## Validate evaluation case files (no API calls)
	$(PY) -m quilora.evals.run --validate

eval: ## Run the evaluation suite against the real model and compare with the baseline
	$(PY) -m quilora.evals.run

eval-judge: ## Same, with LLM-as-judge rubrics
	$(PY) -m quilora.evals.run --judge

eval-baseline: ## Run the suite and save it as evals/baseline.json
	$(PY) -m quilora.evals.run --save-baseline

mcp: ## Run the MCP server over stdio
	$(PY) -m quilora.mcp_server

api: ## Run the HTTP API locally with auto-reload
	uvicorn quilora.api.app:app --reload --port 8000

web: ## Run the Angular widget (proxies /api to localhost:8000)
	cd web && npm start

up: ## Start the whole stack with Docker Compose
	docker compose up --build
