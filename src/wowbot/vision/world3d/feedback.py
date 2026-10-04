"""World3D belief feedback from verified quest/interaction/combat outcomes."""
from __future__ import annotations

from copy import deepcopy
from typing import Any, Iterable


def _clamp(value: object) -> float:
    try:
        return max(0., min(1., float(value)))
    except (TypeError, ValueError):
        return 0.


def apply_world3d_feedback(tracks: Iterable[dict[str, Any]], context: dict[str, Any],
                           *, observed_at: float
                           ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Apply outcome evidence without changing detection or input authority."""
    result = [deepcopy(track) for track in tracks]
    by_id = {str(track.get("track_id")): track for track in result}
    events: list[dict[str, Any]] = []

    for death in context.get("world3d_death_events") or ():
        corpse_id = str(death.get("corpse_track_id") or death.get("track_id") or "")
        source_id = str(death.get("source_entity_track_id") or "")
        corpse = by_id.get(corpse_id)
        source = by_id.get(source_id)
        confidence = _clamp(death.get("confidence", 1.))
        ground_truth = bool(death.get("ground_truth") or
                            str(death.get("source") or "").upper() in {"COMBAT_LOG", "TARGET_TELEMETRY"})
        if source:
            source["temporal_state"] = "DEAD"
            source["alive_belief"] = {
                "label": "DEAD", "state": "CONFIRMED", "confidence": confidence,
                "source": str(death.get("source") or "DEATH_EVENT"),
                "fact": ground_truth,
            }
        if corpse:
            corpse["source_entity_track_id"] = source_id or None
            corpse["corpse_belief"] = {
                "belief": "CONFIRMED" if ground_truth else "SUPPORTED",
                "confidence": confidence,
                "evidence": ["death_transition", *(death.get("evidence") or ())],
                "source_track_id": source_id or None,
                "fact": ground_truth,
            }
        if corpse or source:
            events.append({
                "event_type": "WORLD3D_DEATH_TRANSITION", "timestamp_monotonic": observed_at,
                "source_entity_track_id": source_id or None,
                "corpse_track_id": corpse_id or None, "confidence": confidence,
                "fact": ground_truth,
            })

    feedback_rows = [
        *(context.get("world3d_feedback") or ()),
        *(context.get("quest_no_credit_events") or ()),
        *(context.get("interaction_failure_events") or ()),
        *(context.get("combat_error_events") or ()),
    ]
    for row in feedback_rows:
        track_id = str(row.get("track_id") or "")
        track = by_id.get(track_id)
        if track is None:
            continue
        kind = str(row.get("kind") or row.get("event_type") or "").upper()
        reason = str(row.get("reason") or "").upper()
        evidence_id = str(row.get("evidence_id") or f"feedback:{kind}:{reason}:{observed_at}")
        if kind in {"QUEST_NO_CREDIT", "NO_CREDIT"}:
            role_label = str(row.get("role_label") or "QUEST_OBJECTIVE")
            penalty = _clamp(row.get("penalty", .35))
            track.setdefault("role_beliefs", []).append({
                "label": role_label, "confidence": penalty,
                "belief": "CONTRADICTED", "source": "QUEST_PROGRESS_VERIFIER",
                "evidence_refs": [evidence_id], "fact": False,
            })
            track["quest_role_penalty"] = {
                "role": role_label, "amount": penalty, "evidence_ref": evidence_id,
                "detector_confidence_unchanged": True,
            }
        if kind in {"INTERACTION_FAILURE", "COMBAT_ERROR"}:
            if reason == "OUT_OF_RANGE":
                track.setdefault("distance_belief", {})["relative_lower_bound"] = "BEYOND_ACTION_RANGE"
                track["distance_belief"]["feedback_source"] = kind
                track["distance_belief"]["evidence_ref"] = evidence_id
            elif reason in {"FACING_WRONG_WAY", "WRONG_FACING"}:
                track["facing_feedback"] = {
                    "correction_required": True, "evidence_ref": evidence_id,
                    "source": kind, "fact": False,
                }
            elif reason == "LINE_OF_SIGHT":
                track["local_geometry_feedback"] = {
                    "obstacle_evidence": "LOS_BLOCKED", "confidence": _clamp(row.get("confidence", .8)),
                    "evidence_ref": evidence_id, "fact": False,
                }
            elif reason in {"TARGET_LOST", "TARGET_NOT_FOUND"}:
                track["reacquire_request"] = {
                    "kind": "WORLD3D_REACQUIRE", "track_id": track_id,
                    "reason": reason, "evidence_ref": evidence_id,
                    "input_authority": False,
                }
            elif reason in {"NO_RESPONSE", "NO_UI_RESPONSE"} and bool(row.get("expected_context")):
                cue = track.get("interactability_belief") or {}
                cue["confidence"] = round(_clamp(cue.get("confidence"))*.65, 4)
                cue["feedback"] = "NO_RESPONSE_IN_EXPECTED_CONTEXT"
                cue["evidence_ref"] = evidence_id
                track["interactability_belief"] = cue
        events.append({
            "event_type": "WORLD3D_BELIEF_FEEDBACK", "timestamp_monotonic": observed_at,
            "track_id": track_id, "kind": kind, "reason": reason,
            "evidence_id": evidence_id, "fact": False,
        })
    return result, events

