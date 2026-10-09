#!/usr/bin/env bash
# Author: Ignacio Rodríguez Caro
# Lightweight secret scan. Run before every push (also wired as a git pre-push hook
# by `make hooks`, and executed in CI). It is intentionally simple and dependency-free;
# for a stronger scan use gitleaks (https://github.com/gitleaks/gitleaks).
set -euo pipefail

cd "$(git rev-parse --show-toplevel)"

patterns=(
  'sk-ant-[A-Za-z0-9_-]{20,}'          # Anthropic API keys
  'AKIA[0-9A-Z]{16}'                    # AWS access key IDs
  'ghp_[A-Za-z0-9]{36}'                 # GitHub personal access tokens
  'xox[baprs]-[A-Za-z0-9-]{10,}'        # Slack tokens
  '-----BEGIN [A-Z ]*PRIVATE KEY-----'  # PEM private keys
  'pa-[A-Za-z0-9_-]{30,}'               # Voyage AI keys
)

status=0

# 1) A real .env must never be tracked.
if git ls-files --error-unmatch .env >/dev/null 2>&1; then
  echo "ERROR: .env is tracked by git. Remove it with 'git rm --cached .env'." >&2
  status=1
fi

# 2) .env.example must not contain a value for the API key.
if grep -Eq '^ANTHROPIC_API_KEY=.+' .env.example 2>/dev/null; then
  echo "ERROR: .env.example contains a value for ANTHROPIC_API_KEY." >&2
  status=1
fi

# 3) Scan all tracked files for known secret formats.
for p in "${patterns[@]}"; do
  if git ls-files -z | xargs -0 grep -EIn -- "$p" 2>/dev/null \
      | grep -v 'scripts/check_secrets.sh'; then
    echo "ERROR: possible secret matching pattern: $p" >&2
    status=1
  fi
done

if [ "$status" -eq 0 ]; then
  echo "Secret scan passed."
fi
exit "$status"
