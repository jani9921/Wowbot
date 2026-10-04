"""Explicit FRESH/STALE/EXPIRED evidence-age classification (V4-009).

``Evidence`` (see ``world.py``) already carries ``at``/``expires``/``source``/
``confidence``. This module adds the missing tri-state freshness policy named
in the spec, keyed by the same worked examples it gives (screen-space bbox,
local entity location, minimap marker, quest objective text, quest completion
state, world-map objective area) so callers stop treating "not yet expired"
as the only signal and can also react to evidence that is merely getting old.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class FreshnessTier(StrEnum):
    FRESH = "FRESH"
    STALE = "STALE"
    EXPIRED = "EXPIRED"


@dataclass(frozen=True, slots=True)
class EvidenceFreshnessPolicy:
    """One source category's lifetime window.

    ``stale_after_seconds`` is when the evidence should be treated as
    ageing but still usable; ``expires_after_seconds`` is when it must no
    longer be acted on. Either may be ``None``: a category with both set to
    ``None`` never expires by clock alone (e.g. quest completion state,
    which the spec says lives "until replaced by newer authoritative quest
    state").
    """

    stale_after_seconds: float | None
    expires_after_seconds: float | None


# Named directly after the spec's own worked examples (V4-009).
KNOWN_POLICIES: dict[str, EvidenceFreshnessPolicy] = {
    "screen_space_bbox": EvidenceFreshnessPolicy(.3, 1.0),
    "local_entity_location": EvidenceFreshnessPolicy(1.5, 4.0),
    "minimap_marker": EvidenceFreshnessPolicy(.5, 2.0),
    "quest_objective_text": EvidenceFreshnessPolicy(30.0, 120.0),
    "quest_completion_state": EvidenceFreshnessPolicy(None, None),
    "world_map_objective_area": EvidenceFreshnessPolicy(15.0, 60.0),
}

DEFAULT_POLICY = EvidenceFreshnessPolicy(1.0, 5.0)


def policy_for(category: str) -> EvidenceFreshnessPolicy:
    """Return the named policy, or a conservative default for an unknown one."""
    return KNOWN_POLICIES.get(category, DEFAULT_POLICY)


def classify(category: str, age_seconds: float) -> FreshnessTier:
    """Classify ``age_seconds`` of evidence in ``category`` into a tier."""
    policy = policy_for(category)
    age = max(0.0, float(age_seconds))
    if policy.stale_after_seconds is None and policy.expires_after_seconds is None:
        return FreshnessTier.FRESH
    if policy.stale_after_seconds is not None and age <= policy.stale_after_seconds:
        return FreshnessTier.FRESH
    if policy.expires_after_seconds is not None and age > policy.expires_after_seconds:
        return FreshnessTier.EXPIRED
    return FreshnessTier.STALE
