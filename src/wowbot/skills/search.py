"""Canonical bounded M0 visual-search skill.

The existing visual-search controller remains the implementation of camera
sectors and visual-servo approach.  Crucially, its mutable instance is created
per active skill and stored only in ``ActiveSkillState.skill_context``; the
engine no longer owns a long-lived search controller.
"""
from __future__ import annotations

from wowbot.agent.vision_seek import SeekVisualCueController
from wowbot.runtime import ActiveSkillState, FailureReason, SkillResult, SkillStatus
from .search_contract import SearchCapability, SearchContext, SearchOutcome


class SearchSkill:
    _CONTEXT_KEY = "search_controller"
    _SEARCH_CONTEXT_KEY = "search_context"
    _WORLD_CONTEXT_KEY = "search_world_context"

    def __init__(self, bindings=None, max_seconds: float = 22.) -> None:
        self.bindings = bindings
        self.max_seconds = max_seconds
        self._last_snapshot: dict = {"phase": "IDLE", "authority": "ActiveSkillRuntime"}

    @staticmethod
    def _reason(value: str) -> FailureReason:
        if value in {"seek_visual_cue_sectors_exhausted", "visual_track_lost"}:
            return FailureReason.TARGET_NOT_FOUND
        if "deadline" in value or "timeout" in value:
            return FailureReason.TIMEOUT
        if "identity" in value:
            return FailureReason.IDENTITY_UNCERTAIN
        return FailureReason.INTERNAL_ERROR

    def _controller(self, state: ActiveSkillState) -> SeekVisualCueController:
        controller = state.skill_context.get(self._CONTEXT_KEY)
        if not isinstance(controller, SeekVisualCueController):
            raise RuntimeError("Search skill was observed before begin")
        return controller

    def _result(self, active: ActiveSkillState, controller: SeekVisualCueController, assessment, state: dict,
                observation_id: str, now: float) -> SkillResult:
        search_context = active.skill_context.get(self._SEARCH_CONTEXT_KEY)
        self._last_snapshot = {**controller.snapshot(), "authority": "ActiveSkillRuntime"}
        if assessment.terminal:
            if assessment.success:
                return SkillResult(SkillStatus.SUCCESS, metadata={
                    "reason": assessment.reason,
                    "search_outcome": SearchOutcome.FOUND.value,
                    "search_context": self._context_snapshot(search_context),
                })
            return SkillResult(SkillStatus.FAILURE, self._reason(assessment.reason),
                               retryable=False, replan_required=True,
                               metadata={
                                   "legacy_reason": assessment.reason,
                                   "search_outcome": SearchOutcome.NOT_FOUND_WITHIN_BUDGET.value,
                                   "search_context": self._context_snapshot(search_context),
                               })
        commands = controller.command(state, observation_id, now)
        self._record_scan_progress(controller, search_context)
        self._last_snapshot = {**controller.snapshot(), "authority": "ActiveSkillRuntime"}
        return SkillResult(SkillStatus.RUNNING, commands=commands,
                           metadata={
                               "reason": assessment.reason,
                               "search_context": self._context_snapshot(search_context),
                           })

    def begin(self, active: ActiveSkillState, state: dict, observation_id: str, now: float) -> SkillResult:
        controller = SeekVisualCueController(self.bindings, max_seconds=self.max_seconds)
        active.skill_context[self._CONTEXT_KEY] = controller
        active.phase = "SEARCH"
        controller.begin(active.intent.parameters, state, now)
        capability = self._capability(
            active.intent.skill_type, active.intent.parameters)
        player = state.get("player") if isinstance(state.get("player"), dict) else state
        x, y = player.get("x"), player.get("y")
        origin = ((float(x), float(y)) if isinstance(x, (int, float))
                  and isinstance(y, (int, float)) else None)
        active.skill_context[self._SEARCH_CONTEXT_KEY] = SearchContext(
            origin=origin,
            radius=float(active.intent.parameters.get("radius", 20.0)),
            query=str(active.intent.parameters.get("query")
                      or active.intent.parameters.get("purpose") or capability.value),
            scan_budget=len(controller.sectors),
            time_budget_seconds=self.max_seconds,
            started_at=now,
        )
        active.skill_context[self._WORLD_CONTEXT_KEY] = (
            state.get("session_id"), state.get("map_id"))
        return self._result(active, controller, controller.observe(state, observation_id, now),
                            state, observation_id, now)

    def observe(self, active: ActiveSkillState, state: dict, observation_id: str, now: float) -> SkillResult:
        controller = self._controller(active)
        initial_context = active.skill_context.get(self._WORLD_CONTEXT_KEY)
        current_context = (state.get("session_id"), state.get("map_id"))
        if (initial_context and any(value is not None for value in initial_context)
                and current_context != initial_context):
            context = active.skill_context.get(self._SEARCH_CONTEXT_KEY)
            return SkillResult(
                SkillStatus.FAILURE,
                FailureReason.WRONG_MAP_CONTEXT,
                retryable=False,
                replan_required=True,
                metadata={
                    "search_outcome": SearchOutcome.CONTEXT_CHANGED.value,
                    "search_context": self._context_snapshot(context),
                },
            )
        return self._result(active, controller, controller.observe(state, observation_id, now),
                            state, observation_id, now)

    @staticmethod
    def _capability(value: str, parameters: dict | None = None) -> SearchCapability:
        requested = str((parameters or {}).get("search_capability") or "").upper()
        if requested in SearchCapability.__members__:
            return SearchCapability[requested]
        if str((parameters or {}).get("purpose") or "").upper() == "SEARCH_ENTRANCE":
            return SearchCapability.SEARCH_ENTRANCE
        normalized = str(value or "").upper()
        if normalized in SearchCapability.__members__:
            return SearchCapability[normalized]
        return SearchCapability.SEARCH_LOCAL_ENTITY

    @staticmethod
    def _record_scan_progress(controller, context: SearchContext | None) -> None:
        if context is None:
            return
        scan_index = int(controller.snapshot().get("scan_index", 0))
        for index in range(min(scan_index, len(controller.sectors))):
            context.record_sector_scanned(f"SECTOR_{index}")

    @staticmethod
    def _context_snapshot(context: SearchContext | None) -> dict:
        if context is None:
            return {}
        return {
            "origin": context.origin,
            "radius": context.radius,
            "query": context.query,
            "scan_budget": context.scan_budget,
            "time_budget_seconds": context.time_budget_seconds,
            "sectors_scanned": tuple(context.sectors_scanned),
            "visited_search_points": tuple(context.visited_search_points),
            "started_at": context.started_at,
        }

    def snapshot(self, active: ActiveSkillState | None = None) -> dict:
        if active is not None:
            controller = active.skill_context.get(self._CONTEXT_KEY)
            if isinstance(controller, SeekVisualCueController):
                return {**controller.snapshot(), "authority": "ActiveSkillRuntime"}
        return dict(self._last_snapshot)

    def reset_diagnostics(self) -> None:
        self._last_snapshot = {"phase": "IDLE", "authority": "ActiveSkillRuntime"}
