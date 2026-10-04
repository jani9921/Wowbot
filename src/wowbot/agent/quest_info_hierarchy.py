"""Ranked quest-information source hierarchy (V4-012).

Each named source (quest tracker/world map/minimap/3D world/tooltip/...)
already exists as its own module -- ``quest_model.py``, ``world_map.py``,
``minimap.py``, ``vision/world3d/``, ``tooltip.py``, ``memory.py`` -- but
nothing named the spec's A-H priority order in one place. This adds that
single resolver: "do not reduce the system to 3D object detection" means a
caller must never treat ``E. 3D world`` as authoritative when a
higher-ranked source (A-D) already answered the same question.
"""
from __future__ import annotations

from enum import StrEnum
from typing import Any, Mapping, TypeVar

T = TypeVar("T")


class QuestInfoSource(StrEnum):
    """Ranked A-H, strongest first -- verbatim from the spec's own letters."""

    QUEST_TRACKER = "QUEST_TRACKER"                        # A
    WORLD_MAP = "WORLD_MAP"                                 # B
    SUPERTRACK_MARKER = "SUPERTRACK_MARKER"                 # C
    MINIMAP = "MINIMAP"                                     # D
    WORLD_3D = "WORLD_3D"                                   # E
    TARGET_NAMEPLATE_TOOLTIP = "TARGET_NAMEPLATE_TOOLTIP"   # F
    QUEST_SPECIFIC_UI = "QUEST_SPECIFIC_UI"                 # G
    TEMPORAL_HISTORY = "TEMPORAL_HISTORY"                   # H


# Priority order, strongest first -- index position *is* the rank.
_RANKING: tuple[QuestInfoSource, ...] = tuple(QuestInfoSource)


def rank_quest_info_source(source: QuestInfoSource) -> int:
    """Return the source's rank (0 = strongest)."""
    return _RANKING.index(source)


def resolve_first_available(
    available: Mapping[QuestInfoSource, T | None],
) -> tuple[QuestInfoSource, T] | None:
    """Return the highest-ranked non-``None`` entry from ``available``.

    This is the guard against "do not reduce the system to 3D object
    detection": ``WORLD_3D`` (E) is only ever picked when every A-D source
    is absent for this same question, never because it happened to be
    checked first.
    """
    for source in _RANKING:
        if source not in available:
            continue
        value = available[source]
        if value is not None:
            return source, value
    return None
