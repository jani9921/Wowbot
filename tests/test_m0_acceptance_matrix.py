"""Deterministic M0 acceptance replay matrix.

These are component-boundary replays, not a claim of live WoW completion.
They exercise the canonical ActiveSkillRuntime across the core M0 terminal
paths repeatedly so lifecycle defects cannot hide behind one happy-path run.
"""
from wowbot.agent.models import Attempt, Prediction, Proposal
from wowbot.agent.movement_controller import MovementPhase, ReachMovementController
from wowbot.agent.camera_controller import camera_gesture
from wowbot.runtime import ActiveSkillRuntime, FailureReason, Intent, SkillStatus
from wowbot.skills import CombatSkill, InteractSkill, LootSkill, TargetSkill


def active(skill, params, before, deadline=10.):
    proposal = Proposal.make(skill, "acceptance", params)
    attempt = Attempt("action", proposal, before, "observation", 0., deadline, (),
                      Prediction("prediction", "action", "expected", 0., deadline, "observation"))
    runtime = ActiveSkillRuntime()
    state = runtime.start(intent=Intent(skill, params, params.get("guid")), attempt=attempt,
                          now=0., before_snapshot=before)
    return runtime, state


def hostile(guid="mob"):
    return {"target": {"guid": guid, "attackable": True, "dead": False, "health": 10},
            "actionbar": [{"id": 1, "kind": "spell", "action": "ACTIONBUTTON1",
                            "is_harmful": True, "is_usable": True, "in_range": True,
                            "cooldown_remaining": 0}]}


def test_m0_terminal_matrix_is_deterministic_across_100_replays():
    for _ in range(100):
        # A: visible entity -> target -> interaction UI.
        runtime, state = active("TARGET", {"guid": "npc", "x": .5, "y": .5}, {})
        assert TargetSkill().begin(state).status is SkillStatus.RUNNING
        assert TargetSkill().verify(state, {"target": {"guid": "npc"}}, 1.).status is SkillStatus.SUCCESS
        runtime.cancel(1.)
        runtime, state = active("INTERACT", {"guid": "npc"}, {"target": {"guid": "npc"}})
        assert InteractSkill().begin(state, {"target": {"guid": "npc"}}).status is SkillStatus.RUNNING
        assert InteractSkill().verify(state, {"target": {"guid": "npc"},
                                               "quest_ui": {"open": True, "action": "ACCEPT"}}, 1.).status is SkillStatus.SUCCESS
        runtime.cancel(1.)

        # A confirmed client range error is recovered inside the same
        # Interact attempt.  It emits a NavigationService-owned entity reach
        # request, not a planner-level REACH_OBJECT replacement.
        runtime, state = active("INTERACT", {"guid": "npc"}, {"target": {"guid": "npc"}})
        interact = InteractSkill()
        interact.begin(state, {"target": {"guid": "npc"}})
        remote = {
            "target": {"guid": "npc", "world_position": {"x": 10., "y": 4., "instance_id": 1}},
            "player_world_position": {"x": 1., "y": 1., "instance_id": 1},
            "ui_error": "Need to be closer",
        }
        approach = interact.verify(state, remote, 1.)
        assert approach.status is SkillStatus.RUNNING
        assert approach.metadata["approach_request"]["kind"] == "WORLD_ENTITY"
        assert interact.resume_after_approach(state, remote).commands[0].binding == "INTERACTTARGET"
        runtime.cancel(1.)

        # B/C: typed range and LOS failures remain terminal facts, then a
        # fresh combat attempt can verify a death without planner intervention.
        runtime, state = active("COMBAT", {"guid": "mob"}, hostile())
        combat = CombatSkill()
        assert combat.begin(state, hostile(), 0.).status is SkillStatus.RUNNING
        assert combat.verify(state, {**hostile(), "ui_error": "Need to be closer"}, 1.).reason is FailureReason.OUT_OF_RANGE
        runtime.cancel(1.)
        runtime, state = active("COMBAT", {"guid": "mob"}, hostile())
        combat.begin(state, hostile(), 0.)
        assert combat.verify(state, {**hostile(), "ui_error": "No line of sight"}, 1.).reason is FailureReason.LINE_OF_SIGHT
        runtime.cancel(1.)
        # A localised LOS target keeps the *same* active combat attempt.  It
        # asks NavigationService for one bounded correction, then retries a
        # cast before treating the retained UI error as a second failure.
        runtime, state = active("COMBAT", {"guid": "mob"}, hostile())
        combat.begin(state, hostile(), 0.)
        localized = {**hostile(), "ui_error": "No line of sight", "monotonic_time": 1.}
        localized["target"] = {**localized["target"],
                               "screen_position": {"x": .7, "y": .5, "sample_time": 1.}}
        local = combat.verify(state, localized, 1.)
        assert local.status is SkillStatus.RUNNING
        assert local.metadata["local_navigation_request"]["reason"] == "LINE_OF_SIGHT"
        retry = combat.verify(state, localized, 1.1)
        assert retry.commands and retry.commands[0].binding == "ACTIONBUTTON1"
        runtime.cancel(1.1)
        runtime, state = active("COMBAT", {"guid": "mob"}, hostile())
        combat.begin(state, hostile(), 0.)
        assert combat.verify(state, {"target": {"guid": "mob", "attackable": True, "dead": True, "health": 0}}, 1.).status is SkillStatus.SUCCESS
        runtime.cancel(1.)

        # D: corpse loot requires a before/after receipt evidence delta.
        before = {"target": {"guid": "corpse", "dead": True}, "inventory": {"items": []}}
        runtime, state = active("LOOT", {"guid": "corpse"}, before)
        loot = LootSkill()
        assert loot.begin(state, before).status is SkillStatus.RUNNING
        after = {**before, "events": [{"event_type": "LOOT_RECEIVED", "payload": {"source_guid": "corpse"}}]}
        assert loot.verify(state, after, 1.).status is SkillStatus.SUCCESS
        runtime.cancel(1.)


def test_m0_movement_requires_supported_stuck_evidence_before_recovery():
    controller = ReachMovementController()
    destination = {"map_id": 1, "x": .5, "y": .4}
    initial = {"map_id": 1, "position": {"x": .5, "y": .5}, "orientation": 0.,
               "movement": {"speed": 0., "moving": False}}
    controller.start(destination, initial, "o1", 1.)
    controller.command(initial, "o1", 1.)
    result = None
    for index, at in enumerate((1.4, 1.8, 2.2, 2.6, 3.0, 3.4, 3.8, 4.2, 4.6), 2):
        result = controller.observe(initial, f"o{index}", at)
        if not result.terminal:
            controller.command(initial, f"o{index}", at)
    assert result is not None and result.phase is MovementPhase.SUPPORTED_STUCK
    assert result.reason == "supported_stuck"
    controller.mark_recovery()
    assert controller.snapshot()["recovery_count"] == 1


def test_m0_interrupt_and_reacquire_gesture_are_bounded_and_cancel_safe():
    # F: an interrupt closes the one running skill; no phantom attempt remains.
    runtime, _ = active("INTERACT", {"guid": "npc"}, {"target": {"guid": "npc"}})
    cancelled = runtime.cancel(1., FailureReason.INTERRUPTED)
    assert cancelled is not None and cancelled.last_result.reason is FailureReason.INTERRUPTED
    runtime.finalize()
    assert runtime.state is None

    # G: reacquisition is a finite camera gesture, not a 360-degree loop.
    gesture = camera_gesture({"camera_action": "REACQUIRE_TRACK", "target_x": .72, "target_y": .36})
    assert 0 < gesture["x"] < 1 and 0 < gesture["y"] < 1
    assert .04 <= gesture["duration"] <= .14
