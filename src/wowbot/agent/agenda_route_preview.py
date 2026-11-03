"""Bounded conditional route rollout, never a navigation or truth service."""
from __future__ import annotations

import math

from .agenda_sources import distance


def expectation(kind):
    """Expected evidence, not a prediction asserted to be true."""
    return {
        "ACCEPT": "QUEST_PRESENT_IN_FRESH_LIVE_LOG",
        "READ_ACCEPTED_QUEST": "ACTUAL_OBJECTIVES_AND_COMPLETION_MODE_READ",
        "WORK": "QUEST_OBJECTIVE_CREDIT_VERIFIED",
        "WORK_AFTER_ACCEPT": "QUEST_OBJECTIVE_CREDIT_VERIFIED",
        "TURN_IN": "QUEST_TURN_IN_VERIFIED",
        "TURN_IN_AFTER_WORK": "QUEST_TURN_IN_VERIFIED",
        "CHECK_NEXT_QUESTS": "FRESH_AVAILABLE_QUEST_OR_BOUNDED_ABSENCE_EVIDENCE",
        "CHECK_FOLLOW_UP": "FRESH_LIVE_OFFER_FOR_CHAIN_CANDIDATE",
    }.get(kind, "FRESH_GOAL_RELEVANT_EVIDENCE")


def route_preview(steps, player, preferred_key, *, limit=24):
    """Estimate where to go AFTER hypothetical verification of each step.

    The local ``assumed`` set is simulation only. No step status, quest
    counter, WorldModel, route controller or execution precondition changes.
    Unknown locations and dependencies remain explicitly unknown.
    """
    by_key = {step["key"]: step for step in steps}
    assumed = {key for key, step in by_key.items() if step["status"] == "VERIFIED"}
    pending = {key: step for key, step in by_key.items() if key not in assumed}
    current = player
    preview = []
    while pending and len(preview) < limit:
        eligible = [step for step in pending.values()
                    if all(key in assumed for key in step.get("depends_on") or ())]
        if not eligible:
            break
        selected = next((step for step in eligible
                         if not preview and step["key"] == preferred_key), None)
        def cost(step):
            local = (step["kind"] == "ACCEPT" and step.get("source") in {"LIVE_GOSSIP_OFFER", "LIVE_QUEST_OFFER"}
                     or step["kind"] == "TURN_IN" and step.get("completion_mode") in {"FIELD_TURN_IN", "AUTO_COMPLETE", "SPECIAL_UI"})
            return (0 if local else 1, distance(current, step.get("location")), step["key"])
        selected = selected or min(eligible, key=cost)
        leg = distance(current, selected.get("location"))
        preview.append({"order": len(preview), "step": selected["key"], "kind": selected["kind"],
                        "quest_id": selected["quest_id"], "actual_status": selected["status"],
                        "leg_yards_estimate": round(leg, 1) if math.isfinite(leg) else None,
                        "conditional": True, "expects": expectation(selected["kind"]),
                        "requires_real_verification": list(selected.get("requires") or ()),
                        "if_evidence_missing": "GATHER_FRESH_EVIDENCE_THEN_REPLAN",
                        "if_skill_fails": "CANONICAL_SKILL_RECOVERY_THEN_REPLAN"})
        if selected.get("location"):
            current = selected["location"]
        assumed.add(selected["key"])
        del pending[selected["key"]]
    return {"method": "DEPENDENCY_GATED_NEAREST_NEXT_ESTIMATE", "steps": preview,
            "unplanned_steps": len(pending), "navmesh_validated": False,
            "changes_quest_state": False, "assumed_completions_are_not_evidence": True}
