"""Regression cases from the user's second 2026-10-18 live run.

No client input: only command data, recorded executor output and Lua mocks.
Track IDs below are cue/pointer references, never proof of NPC identity.
"""
from types import SimpleNamespace

import pytest

from test_active_pointer_tracking import scene
from test_agent_map_discovery import world
from test_m0_target_skill import active
from wowbot.agent.engine_runtime_projection import movement_visual_interrupt
from wowbot.agent.models import Proposal
from wowbot.agent.planner import Planner
from wowbot.agent.skills import SkillRegistry
from wowbot.runtime import SkillStatus
from wowbot.skills import TargetSkill
from wowbot.skills.hover_confirm import hover_confirm_step


def hover_context():
    return {"hovered_at": 10., "hovers": 1, "track_id": "WORLD3D:npc",
            "hover_point": (.55, .6)}


def feedback(now, sampled, *, guid="henry", kind="FAST"):
    state = scene(now, .56)
    state.update(transport_kind=kind, mouseover={"guid": guid},
                 mouseover_sample_time=sampled, cursor_sample_time=sampled,
                 cursor_position={"nx": .55, "ny": .6})
    return state


def test_the_initial_hover_also_gets_a_feedback_hold_before_pointer_following():
    context = hover_context()
    result = hover_confirm_step(context, feedback(10.04, 9.99), 10.04,
                                expected_guid="henry", deadline=12.)
    assert result == ("WAIT", ())
    assert not context.get("pointer_follow") and context["hovers"] == 1


def test_slow_full_state_feedback_is_not_invalidated_by_a_second_pointer_move():
    context = hover_context()
    for now in (10.04, 10.48, 10.65):
        assert hover_confirm_step(context, feedback(now, 9.99, kind="STATE_Z"), now,
                                  expected_guid="henry", deadline=12.) == ("WAIT", ())
    outcome, commands = hover_confirm_step(
        context, feedback(10.72, 10.6, kind="STATE_Z"), 10.72,
        expected_guid="henry", deadline=12.)
    assert outcome == "CLICK" and [c.kind for c in commands] == ["CLICK_CURRENT_CURSOR"]
    assert context["hovers"] == 1


def test_full_state_hold_does_not_add_latency_when_exact_feedback_is_already_here():
    outcome, commands = hover_confirm_step(
        hover_context(), feedback(10.08, 10.04, kind="STATE_Z"), 10.08,
        expected_guid="henry", deadline=12.)
    assert outcome == "CLICK" and commands[0].kind == "CLICK_CURRENT_CURSOR"


def test_full_state_feedback_hold_is_bounded_and_does_not_extend_the_deadline():
    context = hover_context()
    outcome, commands = hover_confirm_step(
        context, feedback(11.01, 9.99, kind="STATE_Z"), 11.01,
        expected_guid="henry", deadline=12.)
    assert outcome == "HOVER" and commands[0].kind == "POINTER"
    assert hover_confirm_step(context, feedback(12., 9.99), 12.,
                              expected_guid="henry", deadline=12.) == ("FAILED", ())


def test_wrong_post_hover_guid_is_rejected_even_before_the_first_follow_update():
    assert hover_confirm_step(
        hover_context(), feedback(10.08, 10.04, guid="kee-la"), 10.08,
        expected_guid="henry", deadline=12.) == ("FAILED", ())


@pytest.mark.parametrize("sampled", [None, 9.9])
def test_an_unacknowledged_hover_never_clicks_from_a_retained_guid(sampled):
    for now in (10.04, 10.4, 10.8):
        outcome, commands = hover_confirm_step(
            hover_context(), feedback(now, sampled, kind="STATE_Z"), now,
            expected_guid="henry", deadline=12.)
        assert outcome != "CLICK" and not any(c.kind.startswith("CLICK") for c in commands)


def test_target_begin_consumes_the_current_world_proof_not_an_older_baseline():
    state = active({"guid": "henry", "x": .55, "y": .6,
                    "hover_x": .7, "hover_y": .6,
                    "ground_truth_handoff": True, "click_current_cursor": True})
    state.before_snapshot = {"mouseover": {"guid": "henry"},
                             "mouseover_sample_time": .1, "cursor_sample_time": .1,
                             "cursor_position": {"nx": .55, "ny": .6}}
    current = {"mouseover": {"guid": "henry"}, "mouseover_sample_time": 1.,
               "cursor_sample_time": 1., "cursor_position": {"nx": .55, "ny": .6}}
    result = TargetSkill().begin(state, current)
    assert result.status is SkillStatus.RUNNING
    assert [command.kind for command in result.commands] == ["CLICK_CURRENT_CURSOR"]


def route(**extra):
    return Proposal.make("MOVE", "turn-in route", {
        "purpose": "LOCATE_TURN_IN_REGION", "quest_id": 7,
        "x": 355., "y": -2264., "instance_id": 2175,
        "coordinate_space": "WORLD_YARDS", **extra})


def cue_scene(now=10., track="turnin-cue", **extra):
    return world(monotonic_time=now, active_quests=[{"quest_id": 7, "is_complete": True}],
        player_world_position={"x": 345., "y": -2264., "instance_id": 2175},
        visual_candidates=[{
            "source": "WORLD3D", "kind": "unknown_subject_candidate",
            "track_id": track, "x": .6, "y": .45, "observed_at": now,
            "confidence": .9, "stable_frames": 12, "lifecycle": "ACTIVE",
            "candidate_labels": ["quest_badge_like", "quest_marker_like"],
        }], **extra)


def test_same_cue_cannot_cancel_the_same_resumed_route_again_without_a_pause():
    planner = Planner(SkillRegistry())
    attempt, observed = SimpleNamespace(proposal=route()), cue_scene()
    handoff = movement_visual_interrupt(attempt, observed.state)
    planner.arm_movement_visual_handoff(handoff, 10., route=attempt.proposal,
                                       world_state=observed.state)
    later = cue_scene(11.)
    suppressed = planner.suppressed_movement_visual_tracks(attempt.proposal, later.state, 11.)
    assert "turnin-cue" in suppressed
    assert movement_visual_interrupt(attempt, later.state, skip_track_ids=suppressed) is None
    assert planner._active_movement_visual_handoff(11.)["track_id"] == "turnin-cue"


def test_cue_cooldown_is_route_and_session_scoped_and_expires():
    planner = Planner(SkillRegistry())
    original, observed = route(), cue_scene()
    handoff = movement_visual_interrupt(SimpleNamespace(proposal=original), observed.state)
    planner.arm_movement_visual_handoff(handoff, 10., route=original, world_state=observed.state)
    for changed, state in [(route(quest_id=8), observed.state),
                           (route(x=370.), observed.state),
                           (original, {**observed.state, "session_id": "another"})]:
        assert not planner.suppressed_movement_visual_tracks(changed, state, 11.)
    assert not planner.suppressed_movement_visual_tracks(original, observed.state, 20.)


def test_a_different_cue_remains_eligible_while_the_first_one_cools_down():
    planner = Planner(SkillRegistry())
    original, observed = route(), cue_scene()
    handoff = movement_visual_interrupt(SimpleNamespace(proposal=original), observed.state)
    planner.arm_movement_visual_handoff(handoff, 10., route=original, world_state=observed.state)
    other = cue_scene(11., track="new-cue")
    suppressed = planner.suppressed_movement_visual_tracks(original, other.state, 11.)
    result = movement_visual_interrupt(SimpleNamespace(proposal=original), other.state,
                                       skip_track_ids=suppressed)
    assert result["track_id"] == "new-cue"


def test_session_reset_drops_cue_cooldowns():
    planner = Planner(SkillRegistry())
    original, observed = route(), cue_scene()
    handoff = movement_visual_interrupt(SimpleNamespace(proposal=original), observed.state)
    planner.arm_movement_visual_handoff(handoff, 10., route=original, world_state=observed.state)
    planner.reset_session()
    assert not planner.suppressed_movement_visual_tracks(original, observed.state, 11.)


def test_fresh_route_npc_id_bypasses_visual_cue_cooldown_but_never_claims_arrival():
    guid = "Creature-0-1465-2175-71046-149899-000053399A"
    move = SimpleNamespace(proposal=route(npc_ids=[149899]))
    observed = cue_scene(11., mouseover={
        "guid": guid, "npc_id": 149899, "is_attackable": False},
        mouseover_sample_time=11.)
    for identity_only in (False, True):
        result = movement_visual_interrupt(
            move, observed.state, skip_track_ids=frozenset({"turnin-cue"}),
            identity_only=identity_only)
        assert result["kind"] == "QUEST_ROUTE_NPC_HOVERED"
        assert result["guid"] == guid


@pytest.mark.parametrize("changes", [
    {"mouseover_sample_time": 9.},
    {"mouseover_sample_time": 12.},
    {"mouseover_sample_time": None},
    {"mouseover": {"guid": "Creature-0-1465-2175-71046-149915-000053399A",
                   "npc_id": 149915, "is_attackable": False}},
    {"mouseover": {"guid": "Creature-0-1465-2175-71046-149899-000053399A",
                   "npc_id": 1, "is_attackable": False}},
])
def test_unverified_or_wrong_npc_does_not_bypass_a_visual_cue_cooldown(changes):
    observed = cue_scene(11., mouseover={
        "guid": "Creature-0-1465-2175-71046-149899-000053399A",
        "npc_id": 149899, "is_attackable": False}, mouseover_sample_time=11.)
    observed.state.update(changes)
    assert movement_visual_interrupt(
        SimpleNamespace(proposal=route(npc_ids=[149899])), observed.state,
        skip_track_ids=frozenset({"turnin-cue"})) is None


def test_terminal_loop_escalation_is_consumed_before_admitting_a_replacement_target():
    from test_active_pointer_tracking import attempt
    from test_agent_core import state
    from wowbot.agent.active_skill_supervision import ActiveSkillSupervisionStep
    from wowbot.agent.engine import AutonomousAgent
    from wowbot.agent.executor import RecordingExecutor
    from wowbot.agent.models import Observation, Outcome
    from wowbot.runtime import FailureReason, LoopGuard, SupervisorDirectiveKind

    agent = AutonomousAgent(RecordingExecutor())
    agent.set_goal("Questelj", 9.9)
    agent.world.ingest(Observation.create(state(10.), 10.))
    agent.loop_guard = LoopGuard(suspect_count=1)
    agent.terminal_results.loop_guard = agent.loop_guard
    agent.pending = attempt("TARGET", {"guid": "henry", "x": .55, "y": .6})
    should_yield = agent._apply_active_supervision(ActiveSkillSupervisionStep(
        terminal_outcome=Outcome.FAILURE, reason="target_not_found",
        typed_reason=FailureReason.TARGET_NOT_FOUND), 10.2)
    assert agent.pending is None and should_yield
    # The next top-level supervision pass has no replacement skill to cancel.
    directive = agent.supervisor.evaluate(agent.world.state, None, 10.24)
    assert directive.kind is SupervisorDirectiveKind.REPLAN and not directive.cancel_active
    assert agent.supervisor.evaluate(agent.world.state, None, 10.28).kind is SupervisorDirectiveKind.CONTINUE
