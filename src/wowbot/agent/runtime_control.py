"""User-facing runtime mode/goal control and FAST packet shaping."""
from __future__ import annotations

import time

from .models import Mode
from .world_addon_reducer import WorldAddonReducer


def next_medium_interval(agent, normal_hz: float) -> float:
    """Give a committed REACH an uninterrupted FAST-feedback window."""
    active_reach = bool(
        agent.mode == Mode.FULL_AI and agent.pending
        and agent.pending.proposal.skill in {
            "MOVE", "FOLLOW", "REACH_OBJECT", "REACH_LOCATION"})
    return 1.0 if active_reach else 1./normal_hz


def compact_fast_payload(payload: dict) -> dict:
    """Keep only the authoritative FAST contract from an assembled packet."""
    if payload.get("transport_kind") != "FAST":
        return payload
    return {key: value for key, value in payload.items()
            if key in WorldAddonReducer.FAST_KEYS}


def confirmed_quest_dialog(payload: dict | None, world_state: dict | None) -> bool:
    """Accept only addon-exported, click-addressable quest actions."""
    state = payload or world_state or {}
    ui = state.get("quest_ui") or {}
    action = str(ui.get("action") or state.get("quest_ui_action") or "").upper()
    x = ui.get("x") if ui.get("x") is not None else state.get("quest_ui_x")
    y = ui.get("y") if ui.get("y") is not None else state.get("quest_ui_y")
    try:
        valid_point = 0 < float(x) < 1 and 0 < float(y) < 1
    except (TypeError, ValueError):
        valid_point = False
    opened = ui.get("open") is True or state.get("quest_ui_open") is True
    return opened and valid_point and action in {
        "GOSSIP_SELECT", "REWARD_SELECT", "ACCEPT", "COMPLETE", "TURN_IN", "CONTINUE",
    }


class RuntimeControl:
    """Mutate runtime control state without participating in its control loop."""

    def __init__(self, runtime) -> None:
        self.runtime = runtime

    def goal(self, text, parameters=None) -> None:
        self.mode("MANUAL")
        self.runtime.agent.set_goal(text, time.monotonic(), parameters)

    def mode(self, mode) -> None:
        runtime = self.runtime
        # FULL_AI remains logically active while foreground/telemetry safety
        # temporarily revokes input. A second click must not restart capture,
        # reset the agent or repeat the arming handshake; returning focus to
        # the selected WoW window is sufficient for automatic recovery.
        if (mode == "FULL_AI" and runtime.agent.mode == Mode.FULL_AI
                and runtime.arm_at is None):
            return
        runtime.arm_at = runtime.arm_deadline = None
        runtime._arm_blockers = ()
        runtime._foreground_suspended = False
        runtime._not_foreground_since = None
        runtime.test_seconds = runtime.test_deadline = None
        runtime.test_dialog_grace_deadline = None
        runtime._test_dialog_grace_enabled = False
        runtime._test_dialog_grace_used = False
        if mode != "FULL_AI":
            runtime.agent.set_mode(Mode(mode))
            return
        if runtime.agent.goal is None:
            raise ValueError("Előbb adj meg egy célt")
        preflight = runtime.bindings.preflight(runtime.agent.goal.domain, ())
        if not preflight["ready"]:
            raise ValueError("Hiányzó bindingok a kiválasztott cache-ben: "
                             + ", ".join(preflight["missing"]))
        runtime.live_capture.rotate()
        runtime.agent.set_mode(Mode.MANUAL)
        runtime.agent.action_budget = None
        # Arming is a handshake, not a one-shot sample.  The GUI click itself
        # temporarily owns focus and the paged addon snapshot may need several
        # seconds to complete.  Start checking almost immediately and keep a
        # generous passive window; no input is possible until every gate is
        # simultaneously proven against the selected PID.
        runtime.arm_at = time.monotonic()+.25
        runtime.arm_deadline = runtime.arm_at+45
        runtime._arm_blockers = ("waiting_for_selected_pid_focus", "waiting_for_fresh_addon_state")

    def test_step(self, *, actions=1, seconds=30) -> None:
        runtime = self.runtime
        already_running = runtime.agent.mode == Mode.FULL_AI and runtime.arm_at is None
        self.mode("FULL_AI")
        runtime.agent.action_budget = actions
        runtime.test_seconds = seconds
        runtime._test_dialog_grace_enabled = actions > 1
        if already_running:
            # mode() returns early for an armed FULL_AI, so the arming branch
            # that normally sets the deadline never runs (issue #74).
            runtime.test_deadline = time.monotonic()+seconds
            runtime.test_dialog_grace_deadline = None
            runtime._test_dialog_grace_used = False
