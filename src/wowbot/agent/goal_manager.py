"""Persistent high-level goal and explainable task-priority state.

The manager never executes input. It records candidate sub-tasks and recovery
state while the shared Planner/SkillRegistry remain the only decision path.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib

from .models import number

@dataclass
class GoalTask:
    task_id: str
    goal_id: str
    reference: str
    skill: str
    status: str
    relevance: float
    progress: float
    cost: float
    risk: float
    uncertainty: float
    expected_reward: float
    score: float
    failures: int = 0
    verified_steps: int = 0
    blocked_until: float = 0.
    reason: str = ""
    updated_at: float = 0.
    # Unit the task acts on (INTERACT/TALK/QUEST_DIALOG); lets new range
    # evidence for that unit reopen its interaction tasks.
    guid: str = ""


@dataclass(frozen=True)
class GoalLifecycleEvent:
    goal_id: str
    previous_status: str | None
    status: str
    reason: str
    at: float


class GoalManager:
    RISK = {"COMBAT": .65, "DEFEND": .7, "ESCAPE": .9, "MOVE": .25, "FOLLOW": .2,
            "APPROACH_TARGET": .45, "INTERACT": .2, "LOOT": .25,
            "HERB": .25, "MINE": .3, "FISH": .2, "INSPECT": .05,
            "MOUNT": .2, "DISMOUNT": .1, "ASSIST": .2, "USE_ON_TARGET": .25,
            "FOLLOW_INSTRUCTION": .3,
            "REPAIR": .1, "BUY_VENDOR": .15, "OPEN_BAGS": .05, "SELL_VENDOR": .15}

    def __init__(self, memory=None):
        self.memory = memory
        self.goal = None
        self.tasks: dict[str, GoalTask] = {}
        self.history: list[GoalLifecycleEvent] = []

    def set_goal(self, goal, now: float, resume=False):
        self.goal = goal
        self.tasks = {}
        self.history = [GoalLifecycleEvent(goal.goal_id, None, goal.status,
                                           "goal_restored" if resume else "goal_created", now)]
        if resume and self.memory:
            for value in self.memory.goal_tasks(goal.goal_id):
                task = GoalTask(**value)
                self.tasks[task.task_id] = task
        self._recompute(now)

    def transition(self, status: str, reason: str, now: float):
        if not self.goal or self.goal.status == status:
            return
        previous = self.goal.status
        self.goal.status = status
        self.goal.failure_reason = reason if status == "FAILED" else None
        if status == "COMPLETED":
            self.goal.progress, self.goal.completed_at = 1.0, now
        if status == "RECOVERING":
            self.goal.recovery_count += 1
        self.history.append(GoalLifecycleEvent(self.goal.goal_id, previous, status, reason, now))
        if self.memory:
            self.memory.save_goal(self.goal)

    def complete(self, reason: str, now: float):
        self.transition("COMPLETED", reason, now)

    def completion_condition_verified(self, world, now: float) -> bool:
        """Evaluate explicit high-level terminal conditions only.

        Attempted skills and task progress never imply completion here. Quest
        goals remain active until their domain lifecycle produces an explicit
        completion condition elsewhere.
        """
        if self.goal is None:
            return False
        parameters = self.goal.parameters
        duration = number(parameters.get("duration"))
        if duration is not None and now - self.goal.created_at >= duration:
            return True
        if (parameters.get("until_bags_full")
                and (world.state.get("inventory") or {}).get("free_slots") == 0):
            return True
        if self.goal.domain == "MOVE" and parameters.get("destination"):
            distance = world.distance(parameters["destination"])
            return distance is not None and distance <= .003
        return False

    def fail(self, reason: str, now: float):
        self.transition("FAILED", reason, now)

    @staticmethod
    def reference(proposal) -> str:
        params = proposal.parameters
        return str(params.get("objective_id") or params.get("quest_id") or
                   params.get("site_key") or params.get("node_id") or proposal.key)

    def register(self, proposal, contract, now: float) -> GoalTask:
        reference = self.reference(proposal)
        task_id = hashlib.sha256(f"{self.goal.goal_id}:{reference}:{proposal.skill}".encode()).hexdigest()[:24]
        relevance = max(0., min(1., proposal.priority/100))
        progress = self.goal.completed_steps/max(1, self.goal.completed_steps+self.goal.failures+1)
        uncertainty = 1-max(0., min(1., proposal.confidence))
        cost = min(1., contract.cost/3)
        risk = self.RISK.get(proposal.skill, .15)
        reward = max(relevance, float(proposal.parameters.get("expected_reward", 0) or 0))
        score = .35*relevance + .15*progress + .20*reward - .12*cost - .10*risk - .08*uncertainty
        old = self.tasks.get(task_id)
        task = GoalTask(task_id, self.goal.goal_id, reference, proposal.skill,
                        old.status if old else "CANDIDATE", relevance, progress, cost, risk,
                        uncertainty, reward, round(score, 5), old.failures if old else 0,
                        old.verified_steps if old else 0, old.blocked_until if old else 0.,
                        proposal.reason, now,
                        str(proposal.parameters.get("guid") or (old.guid if old else "")))
        self.tasks[task_id] = task
        self._persist(task)
        return task

    def filter(self, proposals, contracts, now: float):
        result = []
        for proposal in proposals:
            task = self.register(proposal, contracts[proposal.skill], now)
            if task.status == "UNRESOLVED" and task.blocked_until > now:
                continue
            if task.status == "UNRESOLVED":
                task.status, task.failures = "CANDIDATE", 0
                task.blocked_until = 0.
                self.transition("ACTIVE", "recovery_window_elapsed", now)
            result.append(proposal)
        self._recompute(now)
        return result

    def outcome(self, proposal, success: bool, reason: str, now: float,
                failure_decision=None):
        reference = self.reference(proposal)
        task = next((item for item in self.tasks.values()
                     if item.reference == reference and item.skill == proposal.skill), None)
        if task:
            if success:
                task.verified_steps += 1
                task.failures = 0
                task.status = "VERIFIED_STEP"
                self._reopen_interaction_after_approach(proposal, now)
            else:
                task.failures += 1
                task.status = "UNRESOLVED" if task.failures >= 3 else "RETRY"
                if task.status == "UNRESOLVED":
                    # Looking around is cheap and the scene changes; a 120 s
                    # block left FULL_AI waiting 80 s with nothing to do
                    # (live 2026-09-30).
                    task.blocked_until = now + (15. if proposal.skill in self._SEARCH_SKILLS
                                                else 120.)
            task.reason, task.updated_at = reason, now
            self._persist(task)
        if not success and failure_decision is not None:
            self._apply_failure_escalation(task, failure_decision, now)
        self._recompute(now)

    _SEARCH_SKILLS = frozenset({"SEEK_VISUAL_CUE", "INSPECT", "OPEN_MAP", "CLOSE_MAP"})
    _APPROACH_SKILLS = frozenset({"VISUAL_APPROACH", "APPROACH_TARGET", "REACH_OBJECT"})
    _INTERACTION_SKILLS = frozenset({"INTERACT", "TALK", "QUEST_DIALOG"})

    def _reopen_interaction_after_approach(self, proposal, now: float) -> None:
        """Arriving next to a unit is new evidence for interacting with it.

        Live 2026-09-30: silent INTERACTs from far away (Retail exports no NPC
        distance) blocked Lady Jaina's INTERACT task for 120 s, so after the
        visual approach reached INTERACTION_READY every proposal was filtered
        and the agent waited instead of interacting.
        """
        if proposal.skill not in self._APPROACH_SKILLS:
            return
        guid = str(proposal.parameters.get("guid")
                   or proposal.parameters.get("target_guid") or "")
        if not guid:
            return
        for task in self.tasks.values():
            if (task.guid == guid and task.skill in self._INTERACTION_SKILLS
                    and task.status in {"UNRESOLVED", "RETRY"}):
                task.status, task.failures, task.blocked_until = "CANDIDATE", 0, 0.
                task.reason, task.updated_at = "approach_reached_unit", now
                self._persist(task)

    def _apply_failure_escalation(self, task: GoalTask | None,
                                  decision, now: float) -> None:
        stage = str(getattr(decision, "escalation_stage", ""))
        recovery = str(getattr(decision, "recovery_action", "DOMAIN_RECOVERY"))
        if stage == "DOMAIN_RECOVERY":
            self.transition("RECOVERING", f"domain_recovery:{recovery}", now)
            return
        if stage == "PLANNER_REPLAN":
            self.transition("ACTIVE", f"planner_replan:{recovery}", now)
            return
        if stage in {"GOAL_ALTERNATIVE", "GOAL_FAILED"} and task is not None:
            task.status = "UNRESOLVED"
            task.blocked_until = max(task.blocked_until, now + 120.)
            task.reason = f"{stage.casefold()}:{recovery}"
            task.updated_at = now
            self._persist(task)
        if stage == "GOAL_ALTERNATIVE":
            self.transition("RECOVERING", f"goal_alternative:{recovery}", now)
        elif stage == "GOAL_FAILED":
            if self.goal and self.goal.parameters.get("finite", False):
                self.fail(f"failure_budget_exhausted:{recovery}", now)
            else:
                # Persistent farming/quest goals suppress this exhausted task
                # and wait for a different proposal/new evidence instead of
                # retrying the same chain forever.
                self.transition("RECOVERING", f"exhausted_task_suppressed:{recovery}", now)

    def sync_world(self, quest_model, now: float):
        completed = {obj.objective_id for record in quest_model.records.values()
                     for obj in record.objectives if obj.completion_state == "COMPLETE"}
        for task in self.tasks.values():
            if task.reference in completed:
                task.status, task.updated_at = "COMPLETED", now
                self._persist(task)
        self._recompute(now)

    def mark_task_completed(self, reference: str, now: float, reason: str = "task_completion_verified"):
        for task in self.tasks.values():
            if task.reference == reference:
                task.status, task.reason, task.updated_at = "COMPLETED", reason, now
                self._persist(task)
        self._recompute(now)

    def _recompute(self, now: float):
        if not self.goal:
            return
        completed = sum(task.status == "COMPLETED" for task in self.tasks.values())
        verified = sum(task.verified_steps for task in self.tasks.values())
        total = len(self.tasks)
        if total:
            self.goal.progress = max(self.goal.progress, min(1., (completed + .5*min(verified, total))/total))
        unresolved = [task for task in self.tasks.values()
                      if task.status == "UNRESOLVED" and task.blocked_until > now]
        active = [task for task in self.tasks.values()
                  if task.status not in {"COMPLETED", "UNRESOLVED"}]
        if unresolved and not active and self.goal.status not in {"FAILED", "COMPLETED"}:
            maximum = int(self.goal.parameters.get("max_goal_recoveries", 3) or 3)
            if self.goal.recovery_count >= maximum and self.goal.parameters.get("finite", False):
                self.fail("all_subgoals_unresolved", now)
            else:
                self.transition("RECOVERING", "subgoals_temporarily_unresolved", now)
        if total and completed == total and self.goal.parameters.get("complete_when_tasks_complete"):
            self.complete("all_subgoals_completed", now)

    def _persist(self, task):
        if self.memory:
            self.memory.save_goal_task(asdict(task))

    def snapshot(self, now: float) -> dict:
        ordered = sorted(self.tasks.values(), key=lambda item: (-item.score, item.task_id))
        return {"high_level_goal_id": self.goal.goal_id if self.goal else None,
                "goal_status": self.goal.status if self.goal else None,
                "goal_priority": self.goal.priority if self.goal else None,
                "goal_progress": self.goal.progress if self.goal else 0.,
                "persistent": bool(self.goal and self.goal.domain in {"QUEST", "HERB", "MINE", "FISH", "DUNGEON", "PVP"}),
                "active": sum(item.status not in {"COMPLETED", "UNRESOLVED"} for item in ordered),
                "unresolved": sum(item.status == "UNRESOLVED" and item.blocked_until > now for item in ordered),
                "tasks": [asdict(item) for item in ordered[:30]],
                "lifecycle": [asdict(item) for item in self.history[-50:]]}


def classify_failure(skill: str, reason: str) -> str:
    value = str(reason or "").lower()
    if "telemetry" in value or "observation" in value and "stalled" in value:
        return "TELEMETRY_MISSING"
    if "target_identity" in value or "wrong_entity" in value:
        return "WRONG_ENTITY"
    if "target" in value and "not" in value:
        return "TARGET_NOT_FOUND"
    if "path" in value or "progress" in value or skill in {"MOVE", "FOLLOW", "RECOVER", "APPROACH_TARGET", "VISUAL_APPROACH", "REACH_OBJECT", "REACH_LOCATION"}:
        return "PATH_BLOCKED"
    if skill in {"INSPECT", "OPEN_MAP", "CLOSE_MAP"}:
        return "VISION_UNCERTAIN"
    if skill in {"INTERACT", "TALK", "USE", "OBJECT_USE", "LOOT", "HERB", "MINE", "GATHER", "FISH",
                 "ASSIST", "USE_ON_TARGET", "REPAIR", "BUY_VENDOR", "OPEN_BAGS", "SELL_VENDOR"}:
        return "INTERACTION_FAILED"
    if skill in {"COMBAT", "DEFEND", "ESCAPE", "FOLLOW_INSTRUCTION"}:
        return "COMBAT_FAILURE"
    if skill in {"QUEST_DIALOG", "FIELD_TURN_IN"}:
        return "QUEST_STATE_UNEXPECTED"
    return "UNKNOWN"


def classify_prediction_error(reason: str) -> str:
    value = str(reason or "").casefold()
    if any(token in value for token in ("telemetry_stalled", "observation_missing", "unobserved")):
        return "UNOBSERVED"
    if any(token in value for token in ("sensor", "stale", "capture")):
        return "SENSOR_UNRELIABLE"
    if any(token in value for token in ("identity", "wrong target", "unexpected")):
        return "WRONG_EFFECT"
    if any(token in value for token in ("closer", "out of range", "too far", "partial")):
        return "PARTIAL_EFFECT"
    if any(token in value for token in ("heading", "direction", "overshoot")):
        return "DIRECTION_ERROR"
    if any(token in value for token in ("deadline", "timeout", "no_effect", "no effect")):
        return "NO_EFFECT"
    if "timing" in value or "too early" in value:
        return "TIMING_ERROR"
    return "PARTIAL_EFFECT"
