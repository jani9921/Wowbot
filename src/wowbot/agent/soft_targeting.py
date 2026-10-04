"""Optional Retail action-targeting evidence helpers.

Soft/action targeting is a transient client hint.  It may improve candidate
ranking, but it is never selected-target ground truth and never confirms an
entity identity, semantic role, hostility, or interactability by itself.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping, Any

from .models import number, words


_SOFT_UNIT_TOKENS = frozenset({"softenemy", "softfriend", "softinteract"})


@dataclass(frozen=True, slots=True)
class SoftTargetHint:
    source_unit: str
    guid: str | None = None
    npc_id: int | None = None
    name: str | None = None
    unit_type: str | None = None
    reaction: int | None = None
    is_attackable: bool | None = None
    is_dead: bool | None = None
    world_position: dict | None = None
    confidence: float = 0.25
    evidence_role: str = "CANDIDATE_HINT"
    confirmed: bool = False
    semantic_type: str = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class SoftTargetMatch:
    source_unit: str
    score: float
    reasons: tuple[str, ...]
    hint: SoftTargetHint
    evidence_role: str = "CANDIDATE_HINT"
    confirmed: bool = False
    semantic_type: str = "UNKNOWN"


def _text(value: Any, limit: int) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value[:limit] if value else None


def _integer(value: Any) -> int | None:
    parsed = number(value)
    return int(parsed) if parsed is not None and parsed >= 0 else None


def observe_soft_targets(values: object) -> tuple[SoftTargetHint, ...]:
    """Normalize a bounded addon sample without promoting it to fact."""
    if not isinstance(values, (list, tuple)):
        return ()
    result: list[SoftTargetHint] = []
    seen: set[tuple] = set()
    for raw in values[:3]:
        if not isinstance(raw, Mapping):
            continue
        source_unit = str(raw.get("source_unit") or "").casefold()
        if source_unit not in _SOFT_UNIT_TOKENS:
            continue
        guid = _text(raw.get("guid"), 128)
        npc_id = _integer(raw.get("npc_id"))
        name = _text(raw.get("name"), 96)
        if not any((guid, npc_id, name)):
            continue
        identity_key = guid or (f"npc:{npc_id}" if npc_id is not None else f"name:{words(name or '')}")
        key = (source_unit, identity_key)
        if key in seen:
            continue
        seen.add(key)
        confidence = .7 if guid else (.5 if npc_id is not None else .3)
        position = raw.get("world_position")
        if not isinstance(position, Mapping):
            position = None
        result.append(SoftTargetHint(
            source_unit=source_unit,
            guid=guid,
            npc_id=npc_id,
            name=name,
            unit_type=_text(raw.get("unit_type"), 24),
            reaction=_integer(raw.get("reaction")),
            is_attackable=raw.get("is_attackable") if isinstance(raw.get("is_attackable"), bool) else None,
            is_dead=raw.get("is_dead") if isinstance(raw.get("is_dead"), bool) else None,
            world_position=dict(position) if position is not None else None,
            confidence=confidence,
        ))
    return tuple(result)


def use_as_candidate_hint(hints: Iterable[SoftTargetHint], candidate: Mapping[str, Any]
                          ) -> SoftTargetMatch | None:
    """Return supporting evidence for an existing candidate, never a target.

    Exact GUID is strongest; NPC id and normalized name are successively
    weaker.  The caller may add ``score`` to candidate ranking, but this
    function cannot create a Proposal or mutate canonical target state.
    """
    candidate_guid = _text(candidate.get("guid"), 128)
    candidate_npc = _integer(candidate.get("npc_id"))
    candidate_name = words(str(candidate.get("name") or "").strip())
    matches: list[SoftTargetMatch] = []
    for hint in hints:
        reasons: list[str] = []
        score = 0.
        if candidate_guid and hint.guid and candidate_guid == hint.guid:
            score, reasons = .85, ["exact_guid"]
        elif candidate_npc is not None and hint.npc_id == candidate_npc:
            score, reasons = .62, ["matching_npc_id"]
        elif candidate_name and hint.name and candidate_name == words(hint.name):
            score, reasons = .4, ["matching_name"]
        if reasons:
            matches.append(SoftTargetMatch(
                source_unit=hint.source_unit,
                score=min(score, hint.confidence + .15),
                reasons=tuple(reasons), hint=hint))
    return max(matches, key=lambda item: item.score, default=None)
