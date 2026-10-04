"""Quest-scoped escort/follow proposal policy (DESIGN-058)."""
from __future__ import annotations

from wowbot.verification import QuestProgressVerifier
from .models import Proposal, words
from .planning_types import point, world_point


class EscortFollowPolicy:
    def __init__(self, verifier: QuestProgressVerifier | None = None) -> None:
        self.verifier = verifier or QuestProgressVerifier()

    @staticmethod
    def identify_escort_entity(objective, state: dict) -> dict | None:
        expected = getattr(objective, "target_entity", {}) or {}
        candidates = [state.get("target") or {}, *(state.get("entities") or ())]
        for candidate in candidates:
            if not isinstance(candidate, dict) or not candidate.get("guid"):
                continue
            if expected.get("guid") and str(candidate["guid"]) == str(expected["guid"]):
                return candidate
            if (expected.get("npc_id") is not None and candidate.get("npc_id") is not None
                    and str(expected["npc_id"]) == str(candidate["npc_id"])):
                return candidate
            wanted, actual = words(str(expected.get("name") or "")), words(str(candidate.get("name") or ""))
            if wanted and wanted == actual:
                return candidate
        return None

    @staticmethod
    def maintain_distance_band() -> dict:
        return {"follow_min_distance": .003, "follow_max_distance": .008}

    def follow(self, objective, record, state: dict) -> Proposal | None:
        entity = self.identify_escort_entity(objective, state)
        if entity is None:
            return None
        location = world_point(entity.get("world_position") or entity)
        if location is None:
            location = point(entity.get("position") or entity)
        if location is None:
            return None
        return Proposal.make(
            "FOLLOW", "Quest escort entity követése stabil távolságsávban",
            {**location, **self.maintain_distance_band(),
             "follow_quest_entity": True, "follow_entity_guid": str(entity["guid"]),
             "quest_id": getattr(record, "quest_id", None),
             "objective_id": getattr(objective, "objective_id", None),
             "objective_type": getattr(objective, "type", None)},
            confidence=max(.7, float(getattr(objective, "confidence", 0.) or 0.)),
            priority=76)

    @staticmethod
    def handle_stop(distance: float, minimum: float, maximum: float) -> bool:
        return minimum <= distance <= maximum

    @staticmethod
    def handle_combat(state: dict) -> bool:
        return state.get("is_in_combat") is True

    def reacquire(self, objective, record) -> Proposal:
        entity = getattr(objective, "target_entity", {}) or {}
        return Proposal.make(
            "SEEK_VISUAL_CUE", "Escort entity elveszett: korlátos újraazonosítás",
            {"purpose": "REACQUIRE_ESCORT_ENTITY",
             "search_capability": "SEARCH_LOCAL_ENTITY",
             "query": str(entity.get("name") or entity.get("npc_id") or "escort entity"),
             "quest_id": getattr(record, "quest_id", None),
             "objective_id": getattr(objective, "objective_id", None),
             "scan_budget": 4, "time_budget": 18.},
            confidence=.65, priority=70)

    def verify_progress(self, before: dict, after: dict, objective, record):
        return self.verifier.evaluate(
            before, after, quest_ids=(getattr(record, "quest_id", None),),
            objective_ids=(getattr(objective, "objective_id", None),))

    def propose(self, objective, record, state: dict) -> list[Proposal]:
        if self.handle_combat(state):
            return []
        following = self.follow(objective, record, state)
        return [following] if following is not None else [self.reacquire(objective, record)]
