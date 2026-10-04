"""Derive canonical UI transition events without creating a UI control path."""
from __future__ import annotations

from typing import TYPE_CHECKING

from .models import Observation

if TYPE_CHECKING:
    from .world import WorldModel


class WorldUiReducer:
    """Publish source-attributable UI deltas into the one canonical model."""

    _SURFACES = {
        "QUEST_DIALOG": lambda state: bool((state.get("quest_ui") or {}).get("open") or state.get("quest_ui_open")),
        "GOSSIP": lambda state: bool((state.get("gossip_ui") or {}).get("open") or state.get("gossip_open")),
        "VENDOR": lambda state: bool((state.get("vendor_ui") or {}).get("open")),
        "BAGS": lambda state: bool(state.get("bags_open")),
        "WORLD_MAP": lambda state: bool(state.get("world_map_open")),
        "DEATH_SCREEN": lambda state: bool(state.get("is_dead") or state.get("is_ghost")),
        "LOADING": lambda state: bool(state.get("loading")),
        "COMBAT_LOCK": lambda state: bool(state.get("is_in_combat")),
    }

    def apply(self, model: "WorldModel", previous: dict | None, state: dict,
              observation: Observation) -> int:
        if not previous:
            return 0
        changed = 0
        for name, projector in self._SURFACES.items():
            opened = projector(state)
            if projector(previous) != opened:
                model._emit_derived_event("UI_OPENED" if opened else "UI_CLOSED",
                                          {"ui_state": name, "open": opened}, observation)
                changed += 1
        return changed
