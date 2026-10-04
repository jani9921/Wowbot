"""Canonical live-entity references shared by every action domain.

Visual tracks, NPC template IDs and map markers are useful evidence, but none
is safe to use as the identity of a physical in-game unit.  A WorldEntityId is
therefore deliberately a normalized *live addon GUID*.  It is a ``str``
subclass for gradual migration compatibility, while making the boundary
explicit in runtime contracts.
"""
from __future__ import annotations


class WorldEntityId(str):
    """An authoritative, non-empty addon unit GUID.

    No attempt is made to manufacture an identity from an NPC ID, name,
    visual track, or map position.  Those values may associate with this ID in
    the WorldModel only after telemetry supplies the GUID.
    """

    @classmethod
    def from_guid(cls, value: object) -> "WorldEntityId | None":
        if value is None:
            return None
        normalized = str(value).strip()
        return cls(normalized) if normalized else None


def world_entity_id(value: object) -> WorldEntityId | None:
    """Normalize an externally supplied live GUID without guessing."""
    return WorldEntityId.from_guid(value)
