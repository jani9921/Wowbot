"""Make the src-layout importable when pytest runs from the repository root."""
from __future__ import annotations

import os
import sys
from pathlib import Path

# The suite must never call a locally running Ollama (semantic_advisor).
os.environ.setdefault("AIPC_SEMANTIC_ENABLED", "0")
# Nor read the user's local TDB catalogue (config/reference_catalog.local.json):
# tests that need one pass an explicit path, the rest must not depend on it.
os.environ.setdefault("AIPC_REFERENCE_CATALOG",
                      str(Path(__file__).resolve().parent / "tests" / "_no_reference_catalog.sqlite3"))

_SRC = Path(__file__).resolve().parent / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))
