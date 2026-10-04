"""General post-turn-in chain-continuation source hierarchy (V4-063).

``NextQuestResolver`` (next_quest_resolver.py) already handles the narrow
MAIN_CAMPAIGN case: exactly one addon-flagged active campaign quest. This
module adds the missing general case the spec also names: after ANY
turn-in, inspect (in order) the resulting UI, the same NPC, local markers,
the tracker/log, and the world map, before falling back to campaign
classification. "Do not assume same NPC" -- this resolver never returns a
quest tied to the same-NPC source unless that source actually produced
evidence; it does not special-case that source to always be tried alone.
"""
from __future__ import annotations

from enum import StrEnum
from typing import Any, Mapping, TypeVar

T = TypeVar("T")


class NextQuestSource(StrEnum):
    """Inspection order, strongest first -- verbatim from the spec."""

    RESULTING_UI = "RESULTING_UI"
    SAME_NPC = "SAME_NPC"
    LOCAL_MARKERS = "LOCAL_MARKERS"
    TRACKER_LOG = "TRACKER_LOG"
    WORLD_MAP = "WORLD_MAP"
    CAMPAIGN_CLASSIFICATION = "CAMPAIGN_CLASSIFICATION"


_ORDER: tuple[NextQuestSource, ...] = tuple(NextQuestSource)


def resolve_next_quest_source(
    available: Mapping[NextQuestSource, T | None],
) -> tuple[NextQuestSource, T] | None:
    """Return the highest-priority source that actually produced a candidate.

    ``available`` need not include every source; a missing key is treated
    the same as an explicit ``None`` (no evidence from that source). This
    never assumes the same NPC gave a new quest just because it is a
    plausible source -- it only wins when its entry is genuinely non-None.
    """
    for source in _ORDER:
        if source not in available:
            continue
        value = available[source]
        if value is not None:
            return source, value
    return None
