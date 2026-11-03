"""Read-only, declarative counter conditions over normalized WorldModel data.

Conditions describe expected evidence. They never dispatch input, change
world state or turn an unknown measurement into a confirmed result.
"""
from __future__ import annotations

import math
import re

_ROOTS = frozenset({"active_quests", "packet_quest_credits", "route_counters"})


def _number(value):
    return float(value) if type(value) in {int, float} and math.isfinite(value) else None


def validate_condition(condition: dict) -> None:
    if not isinstance(condition, dict) or condition.get("kind") != "COUNTER_AT_LEAST":
        raise ValueError("Unknown observation condition")
    minimum = _number(condition.get("minimum"))
    paths = condition.get("paths")
    if minimum is None or minimum < 0 or not isinstance(paths, list) or not 1 <= len(paths) <= 8:
        raise ValueError("Invalid counter condition")
    for entry in paths:
        path = entry.get("path") if isinstance(entry, dict) else None
        if (not isinstance(path, list) or not 1 <= len(path) <= 12
                or not isinstance(path[0], str) or path[0] not in _ROOTS
                or entry.get("parse", "NUMBER") not in {"NUMBER", "FRACTION"}):
            raise ValueError("Invalid normalized evidence path")
        for step in path:
            if isinstance(step, str) or type(step) is int and step >= 0:
                continue
            if (not isinstance(step, dict) or not isinstance(step.get("field"), str)
                    or set(step) not in ({"field", "equals"}, {"field", "contains"})
                    or not isinstance(step.get("equals", step.get("contains")), (str, int))):
                raise ValueError("Invalid evidence selector")


def _read(state, path):
    value = state
    for step in path:
        if isinstance(step, str):
            value = value.get(step) if isinstance(value, dict) else None
        elif type(step) is int:
            value = value[step] if isinstance(value, (list, tuple)) and step < len(value) else None
        else:
            if not isinstance(value, (list, tuple)):
                return None
            field = step["field"]
            matches = [row for row in value if isinstance(row, dict) and (
                str(row.get(field)) == str(step["equals"]) if "equals" in step else
                isinstance(row.get(field), str) and str(step["contains"]).casefold() in row[field].casefold())]
            value = matches[0] if len(matches) == 1 else None
        if value is None:
            return None
    return value


def condition_count(condition: dict, state: dict) -> float | None:
    """First available source wins in the explicitly declared evidence order."""
    validate_condition(condition)
    for entry in condition["paths"]:
        value = _read(state, entry["path"])
        if entry.get("parse") == "FRACTION":
            match = re.match(r"\s*(\d+)\s*/\s*\d+", value) if isinstance(value, str) else None
            value = int(match.group(1)) if match else None
        count = _number(value)
        if count is not None:
            return count
    return None


def evaluate_condition(condition: dict | None, state: dict) -> bool | None:
    if condition is None:
        return True
    count = condition_count(condition, state)
    return None if count is None else count >= condition["minimum"]
