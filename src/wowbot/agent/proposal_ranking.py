"""Availability filtering and explainable utility ranking for proposals."""
from __future__ import annotations

import math

from dataclasses import dataclass

from .models import Goal, Proposal, number
from .destination_distance import is_world_yards, world_arrived
from .objective_choice import objective_adjustment


@dataclass(frozen=True, slots=True)
class RankingResult:
    proposals: tuple[Proposal, ...]
    pattern_analysis: dict
    scores: dict[str, dict]


class ProposalRanker:
    """Pure selection boundary; it cannot plan, mutate world state or input."""

    @staticmethod
    def move_world_yards(world, parameters: dict) -> float:
        """Straight-line yards to a WORLD_YARDS MOVE destination (inf if unknown).

        Live 2026-10-04 09:02: two quest MOVEs (180 and 203 yd away) had the
        same utility -- their distance penalty is measured against the
        normalized map position and both hit the cap -- and the quest-log
        order sent the agent to the farther quest through the nearer quest's
        area.  Used only to break utility ties between MOVEs.
        """
        if parameters.get("coordinate_space") != "WORLD_YARDS":
            return math.inf
        position = world.state.get("player_world_position") or {}
        px, py = number(position.get("x")), number(position.get("y"))
        x, y = number(parameters.get("x")), number(parameters.get("y"))
        if None in (px, py, x, y) or (
                parameters.get("instance_id") is not None and position.get("instance_id") is not None
                and str(parameters.get("instance_id")) != str(position.get("instance_id"))):
            return math.inf
        return math.hypot(x-px, y-py)

    # Live 2026-10-20 17:12-17:13 (Murloc Mania): the server walk-up to a
    # murloc already within reach but off to the side is a MOVE whose stop
    # distance covers where we stand -- only its face_on_arrival turn is
    # left.  Dropping it as "arrived" left nothing but WAIT for a minute.
    FACE_LEFT_RADIANS = .30

    @staticmethod
    def facing_left_to_do(world, parameters: dict) -> bool:
        if not parameters.get("face_on_arrival") or parameters.get("coordinate_space") != "WORLD_YARDS":
            return False
        position = world.state.get("player_world_position") or {}
        px, py = number(position.get("x")), number(position.get("y"))
        x, y = number(parameters.get("x")), number(parameters.get("y"))
        facing = number(world.state.get("orientation"))
        if None in (px, py, x, y, facing) or math.hypot(x-px, y-py) < 1.:
            return False
        bearing = math.atan2(y-py, x-px)
        return abs((bearing-facing+math.pi) % math.tau - math.pi) > ProposalRanker.FACE_LEFT_RADIANS

    @staticmethod
    def rank(proposals: list[Proposal], *, goal: Goal, world, now: float,
             registry, memory, blocked_until: dict[str, float],
             recent: dict[str, float], evidence: tuple[str, ...],
             objective_context: dict | None = None,
             playbook_guidance: dict | None = None) -> RankingResult:
        selected: list[Proposal] = []
        unavailable_skills: list[str] = []
        cooling_down_skills: list[str] = []
        blocked_skills: list[str] = []
        for proposal in proposals:
            if blocked_until.get(proposal.key, 0) > now:
                blocked_skills.append(proposal.skill)
                continue
            # An explicit hover has a 3D/facing/pitch arrival contract owned
            # by HoverControl. XY arrival alone discarded VEHICLE_AIM at the
            # current position, leaving a selected live mob in WAIT.
            if (proposal.skill == "MOVE" and not proposal.parameters.get("hover_point")
                    and world_arrived(world, proposal.parameters)
                    and not ProposalRanker.facing_left_to_do(world, proposal.parameters)):
                continue
            if proposal.skill in {"INSPECT", "OPEN_MAP"} and recent.get(proposal.key, 0) > now:
                cooling_down_skills.append(proposal.skill)
                continue
            if registry.available(proposal, world):
                selected.append(Proposal.make(
                    proposal.skill, proposal.reason, proposal.parameters,
                    proposal.confidence, proposal.priority, evidence))
            else:
                unavailable_skills.append(proposal.skill)
        if not selected:
            reason = "Több adat szükséges: quest waypoint / megerősített objektum / elérhető skill"
            waiting_for = ["NEW_GOAL_RELEVANT_EVIDENCE"]
            if any(skill in {"COMBAT", "DEFEND"} for skill in unavailable_skills):
                reason = ("Kijelölt harci targethez nincs jelenleg ellenőrzötten "
                          "használható action: binding/resource/cooldown/range frissítésre vár")
                waiting_for = ["USABLE_COMBAT_ACTION_OR_RESOURCE"]
            elif "OPEN_MAP" in cooling_down_skills:
                reason = "A korábbi World Map keresés cooldownjának lejártára vár"
                waiting_for = ["MAP_SEARCH_COOLDOWN"]
            if goal.domain in {"DUNGEON", "PVP", "UNKNOWN"}:
                reason = f"A cél fogadva ({goal.domain}); nincs még bizonyított domain-végrehajtási stratégia"
                waiting_for = ["SUPPORTED_DOMAIN_STRATEGY"]
            selected.append(Proposal.make(
                "WAIT", reason,
                {"waiting_for": waiting_for,
                 "unavailable_skills": sorted(set(unavailable_skills)),
                 "cooling_down_skills": sorted(set(cooling_down_skills)),
                 "blocked_skills": sorted(set(blocked_skills))},
                evidence=evidence))

        state = world.state
        if memory:
            pattern_analysis = memory.find_similar_task_patterns(
                goal.domain, [proposal.skill for proposal in selected], state)
        else:
            pattern_analysis = {"mode": "NO_REFERENCE", "novelty": None, "matches": []}
        reusable = pattern_analysis["matches"][0] if pattern_analysis["matches"] else None
        scores: dict[str, dict] = {}

        def score(proposal: Proposal) -> float:
            if memory:
                profile = memory.procedure_profile(
                    memory.learning_context(state, goal.domain), proposal.skill)
                reliability = (.45 * profile["historical_reliability"]
                               + .55 * profile["recent_reliability"])
            else:
                reliability = .5
            distance = world.distance(proposal.parameters) if proposal.skill == "MOVE" else 0.
            if proposal.skill == "MOVE" and is_world_yards(proposal.parameters):
                # WORLD_YARDS MOVEs always carried the capped penalty (their
                # old map-unit distance was meaningless); the live-tuned
                # ranking relies on it, and move_world_yards breaks ties by
                # real yards.  Keep that explicitly rather than by accident.
                distance = .2
            contract = getattr(registry, "contracts", {}).get(proposal.skill)
            cost = getattr(contract, "cost", 1.)
            pattern_boost = (
                reusable["confidence"] * 3
                if reusable and reusable["similarity"] >= .5
                and proposal.skill in reusable["steps"] else 0.)
            detail = {
                "proposal_id": proposal.key, "skill": proposal.skill,
                "priority": proposal.priority,
                "reliability_bonus": reliability * 5,
                "pattern_bonus": pattern_boost, "cost_penalty": cost,
                "distance_penalty": min(20, (distance or 0) * 100),
            }
            detail["total"] = (detail["priority"] + detail["reliability_bonus"]
                               + detail["pattern_bonus"] - detail["cost_penalty"]
                               - detail["distance_penalty"])
            # One scale for every objective target (objective_choice): route
            # cost with height, placed-here, counted kills, fresh quest.
            adjustment = objective_adjustment(proposal, state, objective_context, now)
            if adjustment is not None:
                detail["objective"] = adjustment
                detail["total"] += adjustment["total"]
            playbook = (playbook_guidance or {}).get(proposal.key)
            if playbook is not None:
                detail["quest_playbook"] = playbook
                detail["total"] += playbook["adjustment"]
            scores[proposal.key] = detail
            return detail["total"]

        ordered = tuple(sorted(selected, key=lambda proposal: (
            -score(proposal),
            ProposalRanker.move_world_yards(world, proposal.parameters)
            if proposal.skill == "MOVE" else math.inf,
            proposal.key)))
        return RankingResult(ordered, pattern_analysis, scores)
