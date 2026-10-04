"""Supertrack/navigation-cue evidence with explicit fallback (V4-019).

A focused/supertracked navigation cue is useful evidence when present, but
the architecture must not depend on it -- it can disappear on focus
change, quest turn-in, map-context change, objective change, or an
unsupported route. This module names the fallback chain explicitly:
navigation cue present -> use it; cue absent -> fall back to minimap ->
world-map -> location beliefs. "Never confuse 'no navigation arrow' with
'quest has no location'" -- absence of a cue is not itself negative
evidence about the quest; it only means this resolver moves to the next
source.
"""
from __future__ import annotations

from enum import StrEnum
from typing import Mapping, TypeVar

T = TypeVar("T")


class NavigationCueSource(StrEnum):
    SUPERTRACK_CUE = "SUPERTRACK_CUE"
    MINIMAP_BELIEF = "MINIMAP_BELIEF"
    WORLD_MAP_BELIEF = "WORLD_MAP_BELIEF"
    LOCATION_BELIEF = "LOCATION_BELIEF"


_ORDER: tuple[NavigationCueSource, ...] = tuple(NavigationCueSource)

# Reasons the spec names for why a supertrack cue may legitimately vanish
# mid-navigation -- exposed so a caller can distinguish "cue disappeared
# for a known reason" from "something is wrong".
KNOWN_DISAPPEARANCE_REASONS: frozenset[str] = frozenset({
    "FOCUS_CHANGED", "QUEST_TURNED_IN", "MAP_CONTEXT_CHANGED",
    "OBJECTIVE_CHANGED", "ROUTE_UNSUPPORTED",
})


def resolve_navigation_cue(
    available: Mapping[NavigationCueSource, T | None],
) -> tuple[NavigationCueSource, T] | None:
    """Return the supertrack cue if present, else the next available fallback."""
    for source in _ORDER:
        if source not in available:
            continue
        value = available[source]
        if value is not None:
            return source, value
    return None
