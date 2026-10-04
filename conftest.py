"""Make the src-layout importable when pytest runs from the repository root."""
from __future__ import annotations

import os
import sys
from pathlib import Path

# The suite must never call a locally running Ollama (semantic_advisor).
os.environ.setdefault("AIPC_SEMANTIC_ENABLED", "0")

_SRC = Path(__file__).resolve().parent / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))
