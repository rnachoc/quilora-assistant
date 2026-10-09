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
