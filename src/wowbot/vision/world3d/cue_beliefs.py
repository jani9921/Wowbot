"""UNKNOWN-first World3D cue belief derivation.

These helpers turn visual appearance hints into inspectable hypotheses.  They
never establish entity identity, semantic type, quest role or lootability as a
fact; those require temporal continuity plus external telemetry/verification.
"""
from __future__ import annotations

import math
from typing import Any, Iterable


def _clamp(value: object) -> float:
    if not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        return 0.0
    return max(0.0, min(1.0, float(value)))


def derive_cue_beliefs(*, detector_kind: str, candidate_labels: Iterable[object],
                       appearance: dict[str, Any], confidence: float,
                       quest_context_active: bool = False) -> dict[str, Any]:
    """Return candidate cue beliefs without crossing recognition boundaries."""
    labels = {str(label).strip().casefold() for label in candidate_labels if str(label).strip()}
    joined = " ".join(sorted(labels))
    base = _clamp(confidence)

    interact_like = any(token in joined for token in (
        "interact", "highlight", "soft_target", "action_target"))
    learned_corpse = any(token in joined for token in ("corpse", "dead_body", "loot_body"))
    explicit_death = appearance.get("death_confirmation") is True
    continuity = bool(appearance.get("source_track_id") or
                      appearance.get("death_continuity_track_id"))
    object_like = ("object" in detector_kind or
                   any(token in joined for token in ("object", "resource_node")))
    visual_quest_context = any(token in joined for token in ("quest_object", "quest_related"))
    quest_context = visual_quest_context or bool(quest_context_active)

    interactability = {
        "belief": "CANDIDATE" if interact_like else "UNKNOWN",
        "confidence": round(base * (.86 if interact_like else .18 if object_like else 0.), 4),
        "evidence": (["visual_interaction_cue_like"] if interact_like else
                     ["unknown_object_proximity_prior"] if object_like else []),
        "fact": False,
    }
    corpse_confidence = base * (.92 if explicit_death and continuity else
                                .68 if explicit_death else .48 if learned_corpse else 0.)
    corpse = {
        "belief": ("SUPPORTED" if explicit_death and continuity else
                   "CANDIDATE" if explicit_death or learned_corpse else "UNKNOWN"),
        "confidence": round(corpse_confidence, 4),
        "source_track_id": (appearance.get("source_track_id") or
                            appearance.get("death_continuity_track_id")),
        "lootable_belief": ("CANDIDATE" if (explicit_death and continuity and interact_like)
                             else "UNKNOWN"),
        "evidence": (["external_death_confirmation", "temporal_track_continuity"]
                     if explicit_death and continuity else
                     ["external_death_confirmation"] if explicit_death else
                     ["learned_corpse_like_appearance"] if learned_corpse else []),
        "fact": False,
    }
    obj = {
        "belief": "CANDIDATE" if object_like else "UNKNOWN",
        "confidence": round(base * (.74 if object_like else 0.), 4),
        "interactable_belief": interactability["belief"],
        "quest_role_belief": "CANDIDATE" if object_like and quest_context else "UNKNOWN",
        "evidence": (["unknown_object_visual_proposal"] if object_like else []) +
                    (["quest_context_like"] if object_like and visual_quest_context else []) +
                    (["quest_search_context_prior"]
                     if object_like and quest_context_active else []),
        "fact": False,
    }
    return {
        "interactability_belief": interactability,
        "corpse_belief": corpse,
        "object_belief": obj,
    }
