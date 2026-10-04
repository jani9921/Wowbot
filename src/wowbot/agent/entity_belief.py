"""Typed entity-identity evidence fusion (V4-010).

``WorldModel`` already stores per-entity roles/locations/states/appearances
as separate history lists (see ``world.py``) and already has
``ContradictionRecord``/``reliability_provider`` for confidence decay. This
module adds the missing piece: the spec's named ``EntityBelief`` record and
a ranked-evidence fusion rule so a single frame of weak visual evidence can
never promote itself to confirmed named identity.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# Identity source ranking, strongest first -- verbatim from the spec's
# worked example. Index position *is* the rank; lower index wins on
# conflicting evidence of otherwise-equal confidence.
IDENTITY_SOURCE_RANKING: tuple[str, ...] = (
    "addon_quest_reference",
    "target_frame_tooltip_name",
    "stable_nameplate_text",
    "quest_marker_and_context",
    "visual_appearance_classifier",
)

_WEAK_VISUAL_ONLY = frozenset({"visual_appearance_classifier"})


def rank_identity_source(source_tag: str) -> int:
    """Return the source's rank (0 = strongest); unknown sources rank last."""
    try:
        return IDENTITY_SOURCE_RANKING.index(source_tag)
    except ValueError:
        return len(IDENTITY_SOURCE_RANKING)


@dataclass(frozen=True, slots=True)
class IdentityEvidence:
    source_tag: str
    value: str
    confidence: float
    at: float


@dataclass(frozen=True, slots=True)
class EntityBelief:
    """One fused, evidence-backed belief about a tracked entity."""

    entity_ref: str
    type_belief: str | None
    identity_belief: str | None
    role_belief: str | None
    hostility_belief: str | None
    interactable_belief: bool | None
    location_belief: tuple[float, float, float] | None
    confidence: float
    evidence: tuple[IdentityEvidence, ...] = field(default_factory=tuple)
    first_seen: float = 0.0
    last_seen: float = 0.0


def fuse_identity(entity_ref: str, evidence: tuple[IdentityEvidence, ...], *,
                  contradiction_penalty: float = 0.25,
                  decay_per_second: float = 0.02, now: float | None = None) -> EntityBelief:
    """Fuse ranked identity evidence into one confidence-scored belief.

    Rules (all from the spec section directly):
    - the strongest-ranked source with the highest confidence wins the
      identity value, never a plain average;
    - if the *only* evidence is ``visual_appearance_classifier``, the
      result is never reported as a confirmed identity -- confidence is
      capped below the "confirmed" threshold;
    - a contradiction (two sources disagreeing on the value) reduces
      confidence rather than being silently dropped;
    - older evidence decays toward zero rather than staying at face value
      forever.
    """
    if not evidence:
        return EntityBelief(entity_ref, None, None, None, None, None, None, 0.0, (), 0.0, 0.0)

    first_seen = min(item.at for item in evidence)
    last_seen = max(item.at for item in evidence)
    reference_time = now if now is not None else last_seen

    def decayed(item: IdentityEvidence) -> float:
        age = max(0.0, reference_time - item.at)
        return max(0.0, item.confidence - decay_per_second * age)

    ranked = sorted(evidence, key=lambda item: (rank_identity_source(item.source_tag), -decayed(item)))
    best = ranked[0]
    best_confidence = decayed(best)

    distinct_values = {item.value for item in evidence}
    if len(distinct_values) > 1:
        best_confidence = max(0.0, best_confidence - contradiction_penalty)

    sources = {item.source_tag for item in evidence}
    if sources <= _WEAK_VISUAL_ONLY:
        # Weak visual evidence alone must not become confirmed named
        # identity -- cap below what a caller would treat as "confirmed".
        best_confidence = min(best_confidence, 0.45)

    return EntityBelief(
        entity_ref=entity_ref,
        type_belief=None,
        identity_belief=best.value,
        role_belief=None,
        hostility_belief=None,
        interactable_belief=None,
        location_belief=None,
        confidence=best_confidence,
        evidence=tuple(evidence),
        first_seen=first_seen,
        last_seen=last_seen,
    )
