"""Canonical live-entity references shared by every action domain.

Visual tracks, NPC template IDs and map markers are useful evidence, but none
is safe to use as the identity of a physical in-game unit.  A WorldEntityId is
therefore deliberately a normalized *live addon GUID*.  It is a ``str``
subclass for gradual migration compatibility, while making the boundary
explicit in runtime contracts.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
import math
from typing import Mapping


_VISUAL_REFERENCE = re.compile(r"^(?:world3d|track(?:_id)?|candidate|npc|object|entity):", re.I)
_ENTRY_GUID = re.compile(
    r"^(Creature|Vehicle|Pet|GameObject)-\d+-\d+-\d+-\d+-(\d+)-[0-9a-f]+$", re.I)


class WorldEntityId(str):
    """An authoritative, non-empty addon unit GUID.

    No attempt is made to manufacture an identity from an NPC ID, name,
    visual track, or map position.  Those values may associate with this ID in
    the WorldModel only after telemetry supplies the GUID.
    """

    @classmethod
    def from_guid(cls, value: object) -> "WorldEntityId | None":
        if value is None or not isinstance(value, str):
            return None
        normalized = value.strip()
        if (not normalized or normalized.isdecimal() or _VISUAL_REFERENCE.match(normalized)
                or normalized.casefold() in {"none", "null", "unknown", "0"}):
            return None
        return cls(normalized)


def world_entity_id(value: object) -> WorldEntityId | None:
    """Normalize an externally supplied live GUID without guessing."""
    return WorldEntityId.from_guid(value)


def template_id(value: object) -> int | None:
    """A positive integral API/template ID, never a track or an invented zero."""
    if isinstance(value, bool):
        return None
    if isinstance(value, float):
        return int(value) if math.isfinite(value) and value.is_integer() and 0 < value <= 0xFFFFFFFF else None
    text = str(value).strip()
    return int(text) if len(text) <= 10 and text.isascii() and text.isdecimal() and 0 < int(text) <= 0xFFFFFFFF else None


def identity_fields(value: Mapping | None) -> dict:
    """Extract only identity; names, appearance and visual IDs are not proof.

    A full public Retail GUID can itself prove its template entry. Opaque
    GUIDs remain usable as instance IDs but are never parsed heuristically.
    Explicit fields are retained so a contradictory ID cannot be repaired by
    the GUID (or by a matching tooltip name).
    """
    value = value or {}
    result = {}
    aliases = [value.get(key) for key in ("guid", "object_guid", "soft_guid") if value.get(key)]
    guid = aliases[0] if aliases else None
    if guid not in (None, ""):
        result["guid"] = world_entity_id(guid)
    for key in ("npc_id", "object_id", "item_id"):
        raw, alias = value.get(key), value.get("expected_" + key)
        if raw is None:
            raw = alias
        if raw not in (None, "", 0, "0"):
            result[key] = template_id(raw)
            if alias not in (None, "", 0, "0") and template_id(alias) != result[key]:
                result["_identity_invalid"] = True
    # Callers may pass an extracted identity through another comparison.
    # Normalization must not silently erase an explicitly malformed field
    # and let a matching GUID override the rejected numeric constraint.
    if (value.get("_identity_invalid") is True or result.get("_identity_invalid")
            or any(field is None for field in result.values())
            or len({world_entity_id(alias) for alias in aliases}) > 1):
        result["_identity_invalid"] = True
    return result


def guid_template(guid: object) -> dict:
    match = _ENTRY_GUID.fullmatch(str(guid or ""))
    if match is None:
        return {}
    key = "object_id" if match[1].casefold() == "gameobject" else "npc_id"
    return {key: int(match[2])}


@dataclass(frozen=True, slots=True)
class IdentityCheck:
    matched: bool
    reason: str

    def __bool__(self) -> bool:
        return self.matched


def check_entity_identity(expected: Mapping | None, observed: Mapping | None) -> IdentityCheck:
    """One fail-closed ID/GUID rule shared by planning, skills and navigation.

    Every supplied constraint must match. A template identifies a *kind*, not
    an instance: callers pin an observed GUID for the lifetime of an attempt.
    GUID-less objects can be proved by their public object ID at a freshly
    verified cursor; that never creates a persistent physical entity ID.
    """
    wanted, actual = identity_fields(expected), identity_fields(observed)
    if not wanted or wanted.get("_identity_invalid") or any(value is None for value in wanted.values()):
        return IdentityCheck(False, "EXPECTED_IDENTITY_MISSING_OR_INVALID")
    if actual.get("_identity_invalid") or any(value is None for value in actual.values()):
        return IdentityCheck(False, "OBSERVED_IDENTITY_INVALID")
    for fields in (wanted, actual):
        for key, entry in guid_template(fields.get("guid")).items():
            if key in fields and fields[key] != entry:
                return IdentityCheck(False, "GUID_TEMPLATE_CONFLICT")
    proved = {**guid_template(actual.get("guid")), **actual}
    for key, value in wanted.items():
        if key not in proved:
            return IdentityCheck(False, key.upper() + "_MISSING")
        if proved[key] != value:
            return IdentityCheck(False, key.upper() + "_MISMATCH")
    return IdentityCheck(True, "ID_GUID_CONFIRMED")
