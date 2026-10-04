"""M1 deterministic quest-execution state; it never sends input or plans routes."""
from __future__ import annotations

from dataclasses import dataclass

from wowbot.runtime import ObjectiveLocationStatus
from .objective_locator import ObjectiveLocator
from .next_quest_resolver import NextQuestResolver
from .quest_model import ObjectiveClassifier
from .quest_state import QuestState


@dataclass
class PrimaryQuestState:
    quest_id: str | None = None
    source: str | None = None
    status: str = "UNRESOLVED"
    selected_at: float | None = None
    phase: str = "SELECT_PRIMARY_QUEST"
    objective_id: str | None = None
    objective_type: str | None = None
    location_status: str | None = None
    completion_mode: str = "UNKNOWN"
    evidence: tuple[str, ...] = ()
    stage_signature: tuple = ()
    stage_revision: int = 0
    last_stage_transition: dict | None = None


class QuestExecutionRuntime:
    """Keep one quest/objective state machine stable until state proves change.

    This is intentionally an M1 *state* layer.  It classifies the next
    objective and its location resolution result, while Planner remains the
    sole component that proposes M0 skills and the executor remains the sole
    component that sends input.
    """
    def __init__(self, attempt_memory=None):
        self.primary = PrimaryQuestState()
        self.classifier = ObjectiveClassifier()
        self.locator = ObjectiveLocator()
        self.next_quest_resolver = NextQuestResolver()
        from .quest_attempt_memory import QuestAttemptMemory
        self.attempt_memory = attempt_memory or QuestAttemptMemory()
        self.failure_memory = self.attempt_memory.failure_memory

    def record_failure(self, *, skill: str, parameters: dict, reason: str, now: float):
        """Record a generic quest action failure; this never changes progress."""
        return self.attempt_memory.record_execution_failure(
            quest_id=parameters.get("quest_id") or self.primary.quest_id,
            objective_id=parameters.get("objective_id") or self.primary.objective_id,
            target_ref=parameters.get("guid"), skill=skill, reason=reason, now=now)

    def record_success(self, *, skill: str, parameters: dict) -> int:
        return self.attempt_memory.record_execution_success(
            quest_id=parameters.get("quest_id") or self.primary.quest_id,
            objective_id=parameters.get("objective_id") or self.primary.objective_id,
            target_ref=parameters.get("guid"), skill=skill)

    def invalidate_selection(self, reason: str, now: float) -> None:
        """Forget derived objective selection, never authoritative progress."""
        self.primary.last_stage_transition = {
            "at": now, "from": self.primary.stage_signature,
            "to": self.primary.stage_signature, "reason": reason,
        }
        self.primary.objective_id = None
        self.primary.objective_type = None
        self.primary.location_status = None

    def observe(self, goal, quest_model, state: dict, now: float,
                *, locator: ObjectiveLocator | None = None) -> PrimaryQuestState:
        if getattr(goal, "domain", None) != "QUEST":
            self.primary = PrimaryQuestState(status="NOT_QUEST_GOAL")
            return self.primary
        explicit = ((getattr(goal, "parameters", {}) or {}).get("primary_quest_id")
                    or (getattr(goal, "parameters", {}) or {}).get("quest_id")
                    or state.get("primary_quest_id"))
        active = [str(record.quest_id) for record in quest_model.records.values()
                  if record.current_state == "ACTIVE"]
        parameters = getattr(goal, "parameters", {}) or {}
        main_campaign = str(parameters.get("mode") or parameters.get("quest_mode") or "").upper() == "MAIN_CAMPAIGN"
        if explicit is None and not main_campaign:
            # Generic questing (user 2026-10-03): every quest in the log is
            # worked on.  Live 21:33-21:55 the turned-in 55122 stayed the
            # primary quest for 22 minutes and filtered out the objectives,
            # turn-ins and gossip offers of every later quest.  Only a single
            # quest in the log is pinned; with several, none is, and the
            # planner batches nearby objectives before turn-ins.
            in_log = sorted(str(record.quest_id) for record in quest_model.records.values()
                            if record.current_state in {"ACTIVE", "COMPLETED"})
            if len(in_log) != 1:
                if self.primary.quest_id is not None or self.primary.status in {"ACTIVE", "COMPLETED"}:
                    self.primary = PrimaryQuestState()
                self.primary.status = "NEEDS_SELECTION" if in_log else "UNRESOLVED"
                self.primary.phase = "SELECT_PRIMARY_QUEST"
                self.primary.evidence = ("auto_batch_all_quests_in_log",) if in_log else ()
                return self.primary
            if self.primary.quest_id != in_log[0]:
                self.primary = PrimaryQuestState(in_log[0], "ONLY_ACTIVE_QUEST", "ACTIVE", now)
        if self.primary.quest_id is None:
            if explicit is not None:
                self.primary = PrimaryQuestState(str(explicit), "EXPLICIT_OR_TELEMETRY", "ACTIVE", now)
            elif len(active) == 1:
                self.primary = PrimaryQuestState(active[0], "ONLY_ACTIVE_QUEST", "ACTIVE", now)
            else:
                self.primary.status = "NEEDS_SELECTION" if len(active) > 1 else "UNRESOLVED"
                self.primary.phase = "SELECT_PRIMARY_QUEST"
        elif self.primary.quest_id in active:
            self.primary.status = "ACTIVE"
        elif any(str(item.quest_id) == self.primary.quest_id and item.current_state == "COMPLETED"
                 for item in quest_model.records.values()):
            self.primary.status = "COMPLETED"
        else:
            # An explicitly addressed quest remains authoritative.  Only a
            # dedicated MAIN_CAMPAIGN goal without a fixed quest id may
            # continue to one fresh addon-confirmed campaign quest.
            continuation = self.next_quest_resolver.resolve(
                quest_model.records.values(),
                main_campaign=main_campaign and explicit is None,
            )
            if continuation.quest_id is not None:
                self.primary = PrimaryQuestState(continuation.quest_id,
                                                 "MAIN_CAMPAIGN_CONTINUATION",
                                                 "ACTIVE", now,
                                                 evidence=(continuation.source,
                                                           continuation.reason))
                active = [str(record.quest_id) for record in quest_model.records.values()
                          if record.current_state == "ACTIVE"]
            else:
                # Never silently replace the user's previous goal with another
                # active quest. Completion/turn-in is a state, not an invitation
                # to select an arbitrary side quest.
                self.primary.status = "NOT_ACTIVE_REASSESS"
                self.primary.phase = "READ_QUEST_STATE"
                self.primary.objective_id = None
                self.primary.objective_type = None
                self.primary.location_status = None
                self.primary.evidence = (continuation.reason, *continuation.candidate_ids)
                return self.primary
        if any(str(item.quest_id) == self.primary.quest_id and item.current_state == "COMPLETED"
               for item in quest_model.records.values()):
            self.primary.status = "COMPLETED"
        if self.primary.status not in {"ACTIVE", "COMPLETED"}:
            return self.primary

        record = next((item for item in quest_model.records.values()
                       if str(item.quest_id) == self.primary.quest_id), None)
        if record is None:
            self.primary.status = "NOT_ACTIVE_REASSESS"
            self.primary.phase = "READ_QUEST_STATE"
            return self.primary
        self._observe_stage(record, now)
        if getattr(record, "lifecycle_state", None) in {
                QuestState.OBJECTIVES_COMPLETE, QuestState.READY_TO_TURN_IN,
                QuestState.TURNING_IN}:
            self.primary.status = getattr(record, "lifecycle_state").value
            self.primary.objective_id = None
            self.primary.objective_type = None
            self.primary.location_status = None
            self.primary.completion_mode = self._completion_mode(state)
            self.primary.evidence = ("quest_lifecycle_completion_surface",)
            self.primary.phase = self._phase_for_completion(self.primary.completion_mode)
            return self.primary
        if record.current_state == "COMPLETED":
            self.primary.objective_id = None
            self.primary.objective_type = None
            self.primary.location_status = None
            self.primary.completion_mode = self._completion_mode(state)
            self.primary.evidence = ("quest_record_completed",)
            self.primary.phase = self._phase_for_completion(self.primary.completion_mode)
            return self.primary

        readiness = quest_model.readiness()
        ready = sorted((objective for objective in record.objectives
                        if readiness.get(objective.objective_id, {}).get("status") == "READY"),
                       key=lambda objective: objective.objective_id)
        if not ready:
            self.primary.phase = "VERIFY_QUEST_PROGRESS"
            self.primary.objective_id = None
            self.primary.objective_type = None
            self.primary.location_status = None
            self.primary.evidence = ("no_ready_objective",)
            return self.primary

        # Keep the objective selection stable when several independent
        # objectives are ready.  Only an objective state transition is
        # allowed to change it; the initial deterministic tie-break uses the
        # normalized objective id, never producer array ordering.
        objective = next((item for item in ready
                          if item.objective_id == self.primary.objective_id), ready[0])
        classified = self.classifier.classify(objective.raw)
        resolved = (locator or self.locator).locate(objective, record, state)
        self.primary.objective_id = objective.objective_id
        self.primary.objective_type = classified.canonical_kind
        self.primary.location_status = resolved.status.value
        self.primary.completion_mode = "UNKNOWN"
        self.primary.evidence = tuple(dict.fromkeys((
            *(str(item.get("source") or "objective_classification") for item in classified.evidence),
            *resolved.evidence,
        )))
        self.primary.phase = self._phase_for_location(resolved.status)
        return self.primary

    @staticmethod
    def _phase_for_location(status: ObjectiveLocationStatus) -> str:
        return {
            ObjectiveLocationStatus.LOCAL_ENTITY: "EXECUTE_OBJECTIVE",
            ObjectiveLocationStatus.LOCAL_OBJECT: "EXECUTE_OBJECTIVE",
            ObjectiveLocationStatus.LOCAL_MARKER: "NAVIGATE_LOCAL",
            ObjectiveLocationStatus.WORLD_MAP_LOCATION: "NAVIGATE_GLOBAL",
            ObjectiveLocationStatus.KNOWN_LOCATION: "NAVIGATE_GLOBAL",
            ObjectiveLocationStatus.SEARCH_AREA: "SEARCH_LOCAL",
            ObjectiveLocationStatus.TRANSITION_REQUIRED: "RESOLVE_TRANSITION",
            ObjectiveLocationStatus.UNKNOWN: "GATHER_INFORMATION",
        }[status]

    @staticmethod
    def _completion_mode(state: dict) -> str:
        declared = str(state.get("quest_completion_mode") or "").upper()
        if declared in {"NPC_TURN_IN", "FIELD_TURN_IN", "AUTO_COMPLETE", "SPECIAL_UI"}:
            return declared
        action = str((state.get("quest_ui") or {}).get("action")
                     or state.get("quest_ui_action") or "").upper()
        if action in {"COMPLETE", "TURN_IN", "REWARD_SELECT"}:
            return "FIELD_TURN_IN"
        return "UNKNOWN"

    @staticmethod
    def _phase_for_completion(mode: str) -> str:
        """Expose the next completion surface without executing it.

        Planner and the typed dialog skill own concrete UI input. The runtime
        only represents the confirmed completion surface, so it does not
        collapse field, automatic, and special completion into one state.
        """
        return {
            "NPC_TURN_IN": "LOCATE_TURNIN",
            "FIELD_TURN_IN": "FIELD_TURN_IN",
            "AUTO_COMPLETE": "VERIFY_COMPLETE",
            "SPECIAL_UI": "HANDLE_SPECIAL_UI",
        }.get(str(mode or "").upper(), "RESOLVE_COMPLETION_MODE")

    def _observe_stage(self, record, now: float) -> None:
        """Invalidate only quest-runtime selections on authoritative stage change.

        ``ObjectiveLocator`` is deliberately a pure resolver, so it has no
        cache to mutate.  Clearing the selected objective here makes the next
        classification/location query use the newly normalized QuestModel
        stage rather than carrying an old objective's location hypothesis.
        """
        signature = (
            str(getattr(record, "current_state", "UNKNOWN")),
            tuple(sorted((str(objective.objective_id), objective.completion_state,
                          objective.current_count, objective.required_count)
                         for objective in getattr(record, "objectives", ()) or ())),
        )
        if not self.primary.stage_signature:
            self.primary.stage_signature = signature
            return
        if self.primary.stage_signature == signature:
            return
        prior = self.primary.stage_signature
        self.primary.stage_signature = signature
        self.primary.stage_revision += 1
        self.primary.last_stage_transition = {
            "at": now, "from": prior, "to": signature,
            "reason": "quest_model_stage_changed",
        }
        self.primary.objective_id = None
        self.primary.objective_type = None
        self.primary.location_status = None
        self.failure_memory.clear(quest_id=self.primary.quest_id)

    def snapshot(self, now: float | None = None) -> dict:
        return {"quest_id": self.primary.quest_id, "source": self.primary.source,
                "status": self.primary.status, "selected_at": self.primary.selected_at,
                "phase": self.primary.phase, "objective_id": self.primary.objective_id,
                "objective_type": self.primary.objective_type,
                "location_status": self.primary.location_status,
                "completion_mode": self.primary.completion_mode,
                "evidence": list(self.primary.evidence),
                "stage_revision": self.primary.stage_revision,
                "last_stage_transition": self.primary.last_stage_transition,
                "failure_memory": self.failure_memory.snapshot(now)}
