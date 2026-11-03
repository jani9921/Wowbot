"""Planner-owned rolling horizon, not another quest/skill/input authority.

Future steps are conditional. Only existing available M0 proposals may be
ranked; neither TDB nor an LLM can manufacture progress or an executable step.
"""
from __future__ import annotations

from copy import deepcopy
import math

from wowbot.query_ports import TravelCostPort
from .agenda_sources import discovery_steps, distance, follow_up_steps, offer_steps, quest_steps, same_area
from .models import Proposal, canonical


class QuestAgenda:
    MAX_DEFER_SECONDS = 600.
    EXHAUSTED_PENALTY = 20.
    # Live 2026-11-02 (Jangolode, 26229 kobolds / 26230 coyotes + dirt): a
    # failed local step left the local quest without a proposal for a moment
    # and the other quest's area MOVE (160 yd away) won; there the first
    # quest's remembered object pulled back -- seven trips in 15 minutes.
    # While the quest whose work area we stand in still proposes something,
    # a far MOVE for another quest yields.
    LOCAL_YARDS = 60.
    FAR_YARDS = 90.
    LOCAL_GRACE_SECONDS = 25.
    LEAVE_PENALTY = 15.

    def __init__(self, *, travel_cost: TravelCostPort | None = None):
        self.travel_cost = travel_cost
        # P8.3: (quest id, objective id) the probe ladder exhausted; the
        # planner sets it before each refresh.
        self.exhausted_objectives = frozenset()
        self.zones = None
        self.reset()

    def _zone_place(self, state, step) -> int:
        """0 same or unknown zone, 1 another zone (P8.3: the turn-in zone
        rule of turnin_order, for every ready task).  Unknown never outranks."""
        from .turnin_order import turn_in_ui_map, zone_place
        if self.zones is None:
            from .ui_zones import ZoneResolver
            self.zones = ZoneResolver()
        location = step.get("location") or {}
        if step["kind"] == "TURN_IN":
            ui_map = turn_in_ui_map(state, step["quest_id"], location, self.zones)
        else:
            ui_map = location.get("ui_map_id")
        return int(zone_place(state, ui_map, self.zones) == 2)

    def reset(self):
        self.context = None
        self.steps = []
        self.groups = []
        self.work_locations = {}
        self.completed_at = {}
        self.preferred_key = None
        self.revision = 0
        self.updated_at = None
        self._signature = None
        self.advice = "deterministic"
        self.advisor_order = ()
        self.advice_key = None
        self.selection_reason = "no_grounded_tasks"
        self.itinerary = {}
        self.recommendation = {}

    def refresh(self, goal, world, now, *, advisor=None):
        state = world.state
        context = (getattr(goal, "goal_id", None), state.get("session_id"), state.get("character_guid"),
                   state.get("map_id"), (state.get("player_world_position") or {}).get("instance_id"), state.get("phase"))
        if context != self.context:
            self.reset()
            self.context = context
        if getattr(goal, "domain", None) != "QUEST":
            self.steps = []
            self.preferred_key = None
            self.itinerary = {}
            return
        ui = state.get("quest_ui") or {}
        # Availability/UI changes must not wait for the one-second idle
        # refresh. Conversely, frame clocks and changing player XY do not
        # invalidate a prepared plan or trigger another LLM request.
        signature = canonical({
            "quest_log_known": isinstance(state.get("active_quests"), (list, tuple)),
            "quests": [(str(q.get("quest_id")), q.get("is_complete"),
                        [(o.get("is_complete"), o.get("current"), o.get("required", o.get("total")))
                         for o in q.get("objectives") or () if isinstance(o, dict)])
                       for q in state.get("active_quests") or () if isinstance(q, dict)],
            "quest_revision": state.get("quest_state_revision"),
            "offers": [(row.get("quest_id"), row.get("is_campaign"))
                       for row in (state.get("map_pois") or {}).get("available_quests") or ()
                       if isinstance(row, dict)],
            "ui": [ui.get("open", state.get("quest_ui_open")),
                   ui.get("quest_id", state.get("quest_ui_quest_id")),
                   ui.get("action", state.get("quest_ui_action")),
                   [(row.get("quest_id"), row.get("kind")) for row in ui.get("entries") or ()
                    if isinstance(row, dict)]],
            "turnins": [(str(record.quest_id), record.last_updated_at)
                        for record in world.quest_model.records.values() if record.current_state == "TURNED_IN"],
            "exhausted": sorted(self.exhausted_objectives),
        })
        if self.updated_at is not None and signature == self._signature and 0 <= now-self.updated_at < 1.:
            return
        self.updated_at, self._signature = now, signature
        steps = quest_steps(world, goal, travel_cost=self.travel_cost)
        steps.extend(offer_steps(state, goal, travel_cost=self.travel_cost))
        steps.extend(discovery_steps(world, goal, steps, self.steps, now))
        steps.extend(follow_up_steps(state, steps, travel_cost=self.travel_cost))
        for step in steps:
            # P8.3: every ready objective of this quest was probed to the end
            # (objective_probes_exhausted): set it aside, other tasks lead.
            if (step["kind"] == "WORK" and step["status"] == "READY" and step.get("objective_ids")
                    and all((step["quest_id"], str(oid)) in self.exhausted_objectives
                            for oid in step["objective_ids"])):
                step["status"] = "DEFERRED_EXHAUSTED"
                step["deferred_reason"] = "objective_probes_exhausted"
        active = {step["quest_id"] for step in steps if step["kind"] == "WORK"}
        self.work_locations = {qid: p for qid, p in self.work_locations.items() if qid in active}
        self.completed_at = {qid: at for qid, at in self.completed_at.items() if qid in active}
        for step in steps:
            if step["kind"] != "WORK":
                continue
            if step["status"] == "VERIFIED":
                self.completed_at.setdefault(step["quest_id"], now)
                step["location"] = self.work_locations.get(step["quest_id"])
            else:
                self.completed_at.pop(step["quest_id"], None)
                if step["location"]:
                    self.work_locations[step["quest_id"]] = step["location"]
                else:
                    self.work_locations.pop(step["quest_id"], None)
        self.groups = []
        for qid, point in sorted(self.work_locations.items()):
            group = next((group for group in self.groups if all(
                same_area(point, self.work_locations[other]) for other in group)), None)
            if group is None:
                self.groups.append([qid])
            else:
                group.append(qid)
        player = state.get("player_world_position") or {}
        work = {step["quest_id"]: step for step in steps if step["kind"] == "WORK"}
        deferred = set()
        for group in self.groups:
            ready = [qid for qid in group if work[qid]["status"] == "READY"]
            if not ready:
                continue
            for qid in group:
                if (work[qid]["status"] == "VERIFIED"
                        and now-self.completed_at.get(qid, now) <= self.MAX_DEFER_SECONDS):
                    turnin = next(step for step in steps if step["key"] == f"turnin:{qid}")
                    if (turnin.get("completion_mode") not in {"FIELD_TURN_IN", "AUTO_COMPLETE", "SPECIAL_UI"}
                            and distance(player, turnin["location"]) > 40.):
                        deferred.add(qid)
                        turnin["status"] = "BATCH_DEFERRED"
                        turnin["depends_on"] = [f"work:{other}" for other in group]
        self._deferred = deferred
        # Nearby real offers can be picked up before departure. Other tasks
        # use straight-line estimates, NOT a claim that a route is walkable.
        def cost(step):
            d = distance(player, step.get("location"))
            group_size = max((len(group) for group in self.groups if step["quest_id"] in group), default=1)
            local_offer = step["kind"] == "ACCEPT" and (d <= 40. or step.get("source") in {"LIVE_GOSSIP_OFFER", "LIVE_QUEST_OFFER"})
            local_completion = step["kind"] == "TURN_IN" and step.get("completion_mode") in {"FIELD_TURN_IN", "AUTO_COMPLETE", "SPECIAL_UI"}
            rank = 0 if local_offer or local_completion else 1
            return (rank, self._zone_place(state, step),
                    d / (1.+.2*(group_size-1)) if math.isfinite(d) else math.inf, step["key"])
        ready = sorted((step for step in steps if step["status"] == "READY"), key=cost)
        self.advice = "deterministic"
        if advisor is not None:
            from .agenda_advice import request, validate
            asked = request(steps, [group for group in self.groups if len(group) > 1],
                            context={key: state.get(key) for key in ("map_id", "phase", "faction")})
            if asked:
                key, payload = asked
                self.advice_key = key
                result = advisor.ask("agenda", key, payload)
                checked = validate(payload, result) if result else {}
                if checked:
                    self.advisor_order = tuple(checked["order"])
        if self.advisor_order:
            order = {value: i for i, value in enumerate(self.advisor_order)}
            # Previously prepared advice survives progress counters/stages;
            # disappeared IDs are ignored, and new tasks use deterministic cost.
            ready.sort(key=lambda step: (cost(step)[0], cost(step)[1],
                int(cost(step)[2]//150.) if math.isfinite(cost(step)[2]) else math.inf,
                order.get(step["key"], 1000), cost(step)))
            self.advice = "grounded_local_llm"
        if not any(step["key"] == self.preferred_key for step in ready):
            self.preferred_key = ready[0]["key"] if ready else None
            self.selection_reason = "verified_state_or_available_tasks_changed"
        ordered = ready + [step for step in steps if step["status"] != "READY"]
        if ordered != self.steps:
            self.revision += 1
        self.steps = ordered
        from .agenda_route_preview import route_preview
        self.itinerary = route_preview(steps, player, self.preferred_key)

    @staticmethod
    def _quest_ids(proposal):
        params = proposal.parameters
        return {str(qid) for qid in [params.get("quest_id"), *(params.get("quest_ids") or ())] if qid is not None}

    @staticmethod
    def _turnin(proposal):
        params = proposal.parameters
        purpose = str(params.get("purpose") or "").upper()
        return ("TURN_IN" in purpose or "TURNIN" in purpose
                or str(params.get("action") or "").upper() in {"TURN_IN", "COMPLETE"})

    @classmethod
    def _matches(cls, step, proposal):
        if step["kind"] == "CHECK_NEXT_QUESTS":
            params = proposal.parameters
            return (proposal.skill == "OPEN_MAP" and params.get("purpose") == "DISCOVER_AVAILABLE_QUESTS"
                    or proposal.skill == "INTERACT" and params.get("after_turn_in_quest_id") is not None
                    and str(params["after_turn_in_quest_id"]) == step["quest_id"])
        if step["kind"] not in {"WORK", "TURN_IN", "ACCEPT"}:
            return False  # conditional future phases cannot execute from a forecast
        return (step["quest_id"] in cls._quest_ids(proposal)
                and ((step["kind"] == "TURN_IN") == cls._turnin(proposal)))

    def note_recommendation(self, proposals, now):
        """Explain the shared Planner's recommendation, never start/advance it."""
        self.recommendation = {}
        if not self.steps or not proposals:
            return
        first = proposals[0]
        matched = next((step for step in self.steps if step["status"] == "READY"
                        and self._matches(step, first)), None)
        self.recommendation = {
            "skill": first.skill, "proposal_key": first.key,
            "task": matched["key"] if matched else None,
            "is_preferred_task": bool(matched and matched["key"] == self.preferred_key),
            "at": now,
            "status": "PLANNER_RECOMMENDATION_NOT_EXECUTION",
        }

    def apply(self, proposals, world, now, *, registry, blocked_until):
        if not self.steps:
            return proposals
        ready_work = {step["quest_id"] for step in self.steps if step["kind"] == "WORK" and step["status"] == "READY"}
        workable = set()
        local_action_ready = False
        available = []
        for proposal in proposals:
            if blocked_until.get(proposal.key, 0.) > now or not registry.available(proposal, world):
                continue
            available.append(proposal)
            if proposal.skill in {"OBJECT_USE", "USE_ON_TARGET", "TARGET", "TALK", "INTERACT", "COMBAT", "DEFEND", "LOOT"}:
                local_action_ready = True
            if (proposal.skill in {"MOVE", "SEEK_VISUAL_CUE", "VISUAL_APPROACH", "TARGET", "INTERACT", "TALK", "OBJECT_USE", "USE_ON_TARGET"}
                    and not self._turnin(proposal)):
                workable |= self._quest_ids(proposal) & ready_work
        deferred = set()
        for group in self.groups:
            if set(group) & workable:
                deferred |= set(group) & getattr(self, "_deferred", set())
        preferred = next((step for step in self.steps if step["key"] == self.preferred_key), None)
        def executable(step):
            return any(self._matches(step, proposal) for proposal in available)
        if preferred is not None and not executable(preferred):
            alternative = next((step for step in self.steps
                                if step["status"] == "READY" and executable(step)), None)
            if alternative:
                preferred = alternative
                self.preferred_key = alternative["key"]
                self.selection_reason = "planned_task_not_executable_choose_available_alternative"
                from .agenda_route_preview import route_preview
                self.itinerary = route_preview(self.steps, world.state.get("player_world_position") or {},
                                               self.preferred_key)
        local = self._local_work(world, proposals, now)
        # P8.3: a quest whose objectives the probe ladder exhausted yields its
        # search/approach/wait to any other ready task; alone, it keeps them.
        set_aside = {step["quest_id"] for step in self.steps
                     if step["kind"] == "WORK" and step["status"] == "DEFERRED_EXHAUSTED"}
        others_ready = any(step["status"] == "READY" and step["quest_id"] not in set_aside
                           for step in self.steps)
        output = []
        for proposal in proposals:
            ids = self._quest_ids(proposal)
            turnin = self._turnin(proposal)
            if (turnin and ids and ids <= deferred and proposal.skill in {
                    "MOVE", "REACH_LOCATION", "REACH_OBJECT", "VISUAL_APPROACH", "SEEK_VISUAL_CUE"}):
                continue
            # Never bias emergency/combat/loot/modal input or manufacture a
            # proposal. Keys/parameters stay unchanged for anti-loop memory.
            bonus = 0.
            if (not local_action_ready and proposal in available and preferred
                    and preferred["kind"] == "CHECK_NEXT_QUESTS" and self._matches(preferred, proposal)):
                bonus = 12.
            elif (not local_action_ready and proposal.skill in {"MOVE", "SEEK_VISUAL_CUE", "VISUAL_APPROACH"}
                    and ids):
                if preferred and preferred["quest_id"] in ids:
                    bonus = 12.
                elif ids & ready_work and not turnin:
                    bonus = 4.
            if (others_ready and ids and ids <= set_aside and not turnin
                    and proposal.skill in {"MOVE", "REACH_LOCATION", "SEEK_VISUAL_CUE", "VISUAL_APPROACH", "WAIT"}):
                bonus -= self.EXHAUSTED_PENALTY
            if (local is not None and local not in ids
                    and proposal.skill in {"MOVE", "REACH_LOCATION", "REACH_OBJECT", "SEEK_VISUAL_CUE"}
                    and self._far(world, proposal.parameters)):
                bonus -= self.LEAVE_PENALTY
            output.append(Proposal.make(proposal.skill, proposal.reason, proposal.parameters,
                                        proposal.confidence, proposal.priority+bonus, proposal.evidence))
        return output

    def _local_work(self, world, proposals, now):
        """The ready quest whose work area we stand in, while it still proposes."""
        player = world.state.get("player_world_position") or {}
        near = [(distance(player, step.get("location")), step["quest_id"]) for step in self.steps
                if step["kind"] == "WORK" and step["status"] == "READY" and step.get("location")]
        near = [row for row in near if row[0] <= self.LOCAL_YARDS]
        if not near:
            self.__dict__.pop("local_seen", None)
            return None
        qid = min(near)[1]
        if any(qid in self._quest_ids(p) and p.skill != "WAIT" for p in proposals):
            self.local_seen = (qid, now)
        seen = self.__dict__.get("local_seen")
        if seen is None or seen[0] != qid or not 0 <= now-seen[1] <= self.LOCAL_GRACE_SECONDS:
            return None
        return qid

    def _far(self, world, params) -> bool:
        if params.get("coordinate_space") != "WORLD_YARDS":
            return False
        player = world.state.get("player_world_position") or {}
        point = {"x": params.get("x"), "y": params.get("y"), "instance_id": params.get("instance_id"),
                 "z": params.get("z"), "z_known": params.get("z_known")}
        return distance(player, point) > self.FAR_YARDS

    def snapshot(self):
        current = next((step for step in self.steps if step["key"] == self.preferred_key), None)
        from .agenda_route_preview import expectation
        current_task = ({key: deepcopy(current.get(key)) for key in
                         ("key", "kind", "quest_id", "title", "status", "requires")}
                        if current else None)
        if current_task is not None:
            current_task["expects"] = expectation(current["kind"])
        return {"implementation": "grounded-quest-agenda-v1", "revision": self.revision,
                "updated_at": self.updated_at, "preferred_step": self.preferred_key,
                "same_area_groups": [list(group) for group in self.groups if len(group) > 1],
                "advice": self.advice, "execution_authority": "existing_Planner_and_ActiveSkillRuntime",
                "advice_key": self.advice_key,
                "selection_reason": self.selection_reason,
                "route_cost": "straight_line_estimate_requires_navigation_validation",
                "current_task": current_task,
                "recommendation": deepcopy(self.recommendation),
                "future_is_conditional": True,
                "itinerary": deepcopy(self.itinerary),
                "steps": deepcopy(self.steps[:96]), "omitted_steps": max(0, len(self.steps)-96)}
