"""Small, data-only class ability metadata missing from Retail action slots.

WoW remains authoritative for usability, cooldown and range-at-this-moment.
This catalog supplies stable semantics (range envelope, role and preference)
only when the addon action record does not already contain them.
"""
from __future__ import annotations

from typing import Mapping


ABILITY_DEFAULTS: dict[int, dict] = {
    # Warrior starter/core abilities used by Exile's Reach.
    100: {
        "min_range": 8.0, "max_range": 25.0, "cooldown_ms": 20000,
        "combat_priority": 60.0, "tags": ("OFFENSIVE", "MOVEMENT"),
    },
    23922: {
        "min_range": 0.0, "max_range": 5.0, "cooldown_ms": 9000,
        "combat_priority": 40.0, "tags": ("OFFENSIVE",),
    },
    1464: {
        "min_range": 0.0, "max_range": 5.0,
        "resource_cost": 20.0,
        "combat_priority": 20.0, "tags": ("OFFENSIVE",),
    },
}


def enrich_ability(action: Mapping) -> dict:
    """Merge known stable metadata without overriding live/addon facts."""
    result = dict(action)
    spell_id = result.get("id", result.get("spell_id"))
    try:
        defaults = ABILITY_DEFAULTS.get(int(spell_id))
    except (TypeError, ValueError):
        defaults = None
    if not defaults:
        return result
    for key, value in defaults.items():
        if result.get(key) is None:
            result[key] = value
    return result

