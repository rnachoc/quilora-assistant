"""Project directories (data, migrations, eval cases).

From a source checkout they are found relative to this file. In a container, where the
package is installed into site-packages, set QUILORA_HOME to the directory holding
`data/`, `db/` and `evals/` (the Dockerfile sets it to /app).
"""

from __future__ import annotations

import os
from pathlib import Path

PROJECT_ROOT = Path(os.environ.get("QUILORA_HOME") or Path(__file__).resolve().parents[2])
DATA_DIR = PROJECT_ROOT / "data"
MIGRATIONS_DIR = PROJECT_ROOT / "db" / "migrations"
EVALS_DIR = PROJECT_ROOT / "evals"
DOCS_DIR = PROJECT_ROOT / "docs"
