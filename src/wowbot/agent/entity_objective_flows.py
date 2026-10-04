"""Input-free SPEAK/KILL objective orchestration policies.

These policies bridge objective location arrival to bounded local entity
search.  They do not select inputs, run combat or assert identity from CV.
Identity is validated only from structured target/addon evidence.
"""
from __future__ import annotations

from .models import Proposal
from .quest_semantics import (combat_subjects, talk_to_subject,
                              subject_matches_name,
                              target_matches_objective,
                              target_matches_structured_entity)


class SpeakObjectiveFlow:
    objective_types = frozenset({"TALK_TO", "INTERACT_NPC", "BUY", "SELL"})

    @staticmethod
    def matches_target(objective, target: dict) -> bool:
        if target.get("attackable", target.get("is_attackable")) is not False:
            return False
        if target_matches_structured_entity(target, getattr(objective, "target_entity", None)):
            return True
        expected = talk_to_subject({**(getattr(objective, "raw", {}) or {}),
                                    "description": getattr(objective, "description", "")})
        return bool(expected and subject_matches_name([expected], target.get("name")))

    @staticmethod
    def propose_local_search(objective, record, search_area: dict) -> list[Proposal]:
        entity = getattr(objective, "target_entity", {}) or {}
        name = entity.get("name") or talk_to_subject({
            **(getattr(objective, "raw", {}) or {}),
            "description": getattr(objective, "description", "")})
        return [Proposal.make(
            "SEEK_VISUAL_CUE", "SPEAK célterület elérve: korlátos NPC-keresés és addon-azonosítás",
            {"purpose": "LOCALIZE_SPEAK_NPC", "search_capability": "SEARCH_LOCAL_ENTITY",
             "query": str(name or entity.get("npc_id") or "quest NPC"),
             "expected_npc_id": entity.get("npc_id"), "expected_name": name,
             "objective_description": getattr(objective, "description", ""),
             "objective_type": getattr(objective, "type", None),
             "quest_id": getattr(record, "quest_id", None),
             "objective_id": getattr(objective, "objective_id", None),
             "search_area": dict(search_area), "scan_budget": 4, "time_budget": 22.},
            confidence=max(.6, float(getattr(objective, "confidence", 0.) or 0.)),
            priority=67, evidence=("speak_area_reached", "npc_identity_not_yet_confirmed"))]


class KillObjectiveFlow:
    objective_types = frozenset({"KILL", "KILL_NAMED"})

    @staticmethod
    def matches_target(objective, target: dict) -> bool:
        if target.get("attackable", target.get("is_attackable")) is not True:
            return False
        if target_matches_structured_entity(target, getattr(objective, "target_entity", None)):
            return True
        return target_matches_objective(
            target, {**(getattr(objective, "raw", {}) or {}),
                     "description": getattr(objective, "description", "")})

    @staticmethod
    def propose_local_search(objective, record, search_area: dict) -> list[Proposal]:
        entity = getattr(objective, "target_entity", {}) or {}
        subjects = combat_subjects({**(getattr(objective, "raw", {}) or {}),
                                    "description": getattr(objective, "description", "")})
        name = entity.get("name") or (subjects[0] if subjects else None)
        return [Proposal.make(
            "SEEK_VISUAL_CUE", "KILL célterület elérve: korlátos hostile keresés és addon-azonosítás",
            {"purpose": "LOCALIZE_KILL_TARGET", "search_capability": "SEARCH_LOCAL_ENTITY",
             "query": str(name or entity.get("npc_id") or "quest hostile"),
             "expected_npc_id": entity.get("npc_id"), "expected_name": name,
             "objective_description": getattr(objective, "description", ""),
             "objective_type": getattr(objective, "type", None),
             "require_attackable": True,
             "quest_id": getattr(record, "quest_id", None),
             "objective_id": getattr(objective, "objective_id", None),
             "search_area": dict(search_area), "scan_budget": 4, "time_budget": 22.},
            confidence=max(.6, float(getattr(objective, "confidence", 0.) or 0.)),
            priority=68, evidence=("kill_area_reached", "hostile_identity_not_yet_confirmed"))]
