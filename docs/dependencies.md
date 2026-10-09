# Dependencies

Every dependency must earn its place. Versions are pinned in `pyproject.toml` and were checked
against PyPI on 2026-10-09.

| Package | Version | Phase | Why it is needed | Alternative considered |
|---------|---------|-------|------------------|------------------------|
| pytest | 9.1.1 | 0 | Test runner | unittest (more boilerplate) |
| ruff | 0.16.10 | 0 | Lint + import sorting in one fast tool | flake8 + isort + black |
