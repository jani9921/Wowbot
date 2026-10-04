"""Read-only M3 quest dependency graph and objective readiness service."""
from __future__ import annotations

from dataclasses import asdict
from typing import Mapping


class QuestGraph:
    """Project normalized quest records without selecting or executing skills."""

    @staticmethod
    def readiness(records: Mapping) -> dict[str, dict]:
        complete = {objective.objective_id for record in records.values()
                    for objective in record.objectives if objective.completion_state == "COMPLETE"}
        completed_quests = {str(qid) for qid, record in records.items()
                            if record.current_state in {"COMPLETED", "TURNED_IN"}}
        result: dict[str, dict] = {}
        for record in records.values():
            for objective in record.objectives:
                blockers = []
                if record.current_state != "ACTIVE":
                    blockers.append(f"QUEST_{record.current_state}")
                blockers.extend(f"QUEST_DEPENDENCY:{value}" for value in record.dependencies
                                if value not in completed_quests)
                blockers.extend(f"OBJECTIVE_DEPENDENCY:{value}" for value in objective.dependencies
                                if value not in complete)
                if objective.completion_state == "COMPLETE":
                    status = "COMPLETE"
                elif objective.branch_type == "CONDITIONAL" and objective.condition_state != "SATISFIED":
                    blockers.append(f"CONDITION_{objective.condition_state}")
                    status = "BLOCKED"
                else:
                    status = "READY" if not blockers else "BLOCKED"
                result[objective.objective_id] = {
                    "status": status, "blockers": blockers,
                    "branch_type": objective.branch_type,
                    "optional": objective.optional,
                    "evidence": list(dict.fromkeys((*objective.evidence, *objective.condition_evidence))),
                }
        return result

    def build(self, records: Mapping) -> dict:
        nodes, edges, quest_nodes, quest_edges = [], [], [], []
        readiness = self.readiness(records)
        for record in records.values():
            if record.current_state == "ABSENT":
                continue
            quest_nodes.append({
                "quest_id": record.quest_id,
                "title": record.title,
                "state": record.lifecycle_state.value,
                "confidence": record.confidence,
                "prerequisites": list(record.dependencies),
                "giver_belief": record.giver_belief,
                "turnin_belief": record.turnin_belief,
                "reward_belief": record.reward_belief,
                "last_updated_at": record.last_updated_at,
            })
            quest_edges.extend(record.chain_relations or self.normalize_relations(
                record.quest_id, record.raw))
            for objective in record.objectives:
                nodes.append({**asdict(objective), "quest_id": record.quest_id,
                              "readiness": readiness.get(objective.objective_id, {})})
                edges.extend({"from": dependency, "to": objective.objective_id,
                              "branch_type": objective.branch_type,
                              "optional": objective.optional, "condition": objective.condition,
                              "condition_state": objective.condition_state,
                              "condition_evidence": list(objective.condition_evidence)}
                             for dependency in objective.dependencies)
            edges.extend({"from": f"quest:{dependency}", "to": f"quest:{record.quest_id}",
                          "branch_type": "QUEST_DEPENDENCY", "optional": False, "condition": True}
                         for dependency in record.dependencies)
        # Preserve the original objective graph API while exposing the M3
        # quest-chain graph explicitly. Consumers cannot accidentally treat
        # an objective dependency as a quest unlock relationship.
        unique_quest_edges = []
        seen = set()
        for edge in quest_edges:
            key = (str(edge["from"]), str(edge["to"]), edge["type"])
            if key not in seen:
                seen.add(key)
                unique_quest_edges.append(edge)
        return {"nodes": nodes, "edges": edges,
                "quest_nodes": quest_nodes, "quest_edges": unique_quest_edges}

    @staticmethod
    def normalize_relations(quest_id, raw: Mapping) -> tuple[dict, ...]:
        """Normalize only explicitly supplied chain relations.

        Absence of a relation is not evidence of a chain. No title, numeric
        adjacency or quest-list order is used to invent edges.
        """
        current = str(quest_id)
        relations: list[dict] = []

        def values(*keys):
            result = []
            for key in keys:
                value = raw.get(key)
                if value is None:
                    continue
                result.extend(value if isinstance(value, (list, tuple, set)) else (value,))
            return tuple(str(value) for value in result if value is not None)

        for dependency in values("dependencies", "prerequisites", "requires"):
            relations.append({"from": dependency, "to": current, "type": "REQUIRES"})
        for unlocked in values("unlocks", "unlocks_quest_ids"):
            relations.append({"from": current, "to": unlocked, "type": "UNLOCKS"})
        for follow_up in values("follow_up", "follow_up_id", "follow_up_ids"):
            relations.append({"from": current, "to": follow_up, "type": "FOLLOW_UP"})
        for predecessor in values("follow_up_of", "previous_quest_id"):
            relations.append({"from": predecessor, "to": current, "type": "FOLLOW_UP"})
        for other in values("exclusive_with", "exclusive_quest_ids"):
            relations.append({"from": current, "to": other, "type": "EXCLUSIVE_WITH"})
        for other in values("same_area_with", "same_area_quest_ids"):
            relations.append({"from": current, "to": other, "type": "SAME_AREA_SYNERGY"})
        return tuple(relations)

    def ready(self, records: Mapping):
        readiness = self.readiness(records)
        return [objective for record in records.values() for objective in record.objectives
                if readiness[objective.objective_id]["status"] == "READY"]
