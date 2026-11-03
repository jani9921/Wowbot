"""Match visible objectives to static rows without assuming hidden-row order."""
from __future__ import annotations

import re

from .models import words


def objective_text_key(value) -> str:
    return re.sub(r"^\d+\s*/\s*\d+\s*", "", words(str(value or ""))).strip()


def reference_objectives(quest_id, objective_id, description, rows, *, allow_ordinal: bool = True) -> list[dict]:
    """Exact ID, otherwise unique text; ordinal fallback only for blank text.

    Retail can hide a credit row entirely. A visible ``quest:1`` therefore
    need not be the TDB row with order=1. Contradictory/duplicate descriptions
    are not repaired by a guessed index. No identity/action authority here.
    Callers with incomplete row alignment can disable the ordinal fallback;
    exact-ID and unique-description matching remain available.
    """
    rows = [row for row in rows or () if isinstance(row, dict)]
    oid = str(objective_id)
    explicit = [row for row in rows if str(row.get("objective_id")) == oid]
    if explicit:
        return explicit if len(explicit) == 1 else []
    key = objective_text_key(description)
    named = [row for row in rows if key and objective_text_key(row.get("description")) == key]
    if named:
        return named if len(named) == 1 else []
    if not allow_ordinal:
        return []
    prefix, sep, index = oid.partition(":")
    if not sep or prefix != str(quest_id) or not index.isdigit():
        return []
    ordinal = [row for row in rows if str(row.get("order")) == index
               and (not key or not objective_text_key(row.get("description")))]
    return ordinal if len(ordinal) == 1 else []
