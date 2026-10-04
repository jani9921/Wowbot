from wowbot.agent.models import Attempt, Prediction, Proposal
from wowbot.runtime import (LoopGuard, LoopSignatureKind, Supervisor,
                            SupervisorDirectiveKind, WorldStateSignature)

def test_loop_guard_distinguishes_suspected_and_confirmed_repetition():
    guard = LoopGuard()
    assert guard.record_failure("interact:npc:1", 0).level == "NONE"
    assert guard.record_failure("interact:npc:1", 2).level == "NONE"
    assert guard.record_failure("interact:npc:1", 4).level == "SUSPECTED"
    assert guard.record_failure("interact:npc:1", 6).level == "SUSPECTED"
    assert guard.record_failure("interact:npc:1", 8).level == "CONFIRMED"

def test_loop_guard_can_clear_one_skill_target_chain_after_verified_success():
    guard = LoopGuard(); guard.record_failure("INTERACT:npc:1:NO_RESPONSE", 1)
    guard.clear_prefix("INTERACT:npc:1:")
    assert guard.snapshot() == {}


def _attempt(skill="INTERACT", params=None, baseline=None):
    proposal = Proposal.make(skill, "anti-loop test", params or {"guid": "npc-1"})
    return Attempt("action", proposal, baseline or {}, "before", 0., 8., (),
                   Prediction("prediction", "action", "effect", 0., 8., "before"))


def test_world_state_signature_ignores_volatile_vision_noise_but_keeps_semantic_delta():
    first = WorldStateSignature.from_state({
        "position": {"x": 10., "y": 20., "z": 3.},
        "target": {"guid": "npc-1", "health": 50},
        "world3d_batch": {"captured_at": 1., "candidates": [1, 2, 3]},
    })
    noisy = WorldStateSignature.from_state({
        "position": {"x": 10., "y": 20., "z": 3.},
        "target": {"guid": "npc-1", "health": 50},
        "world3d_batch": {"captured_at": 9., "candidates": [99]},
    })
    progressed = WorldStateSignature.from_state({
        "position": {"x": 11., "y": 20., "z": 3.},
        "target": {"guid": "npc-1", "health": 40},
    })
    assert first == noisy
    assert first != progressed


def test_typed_attempt_failure_detects_equivalent_action_without_world_delta():
    state = {"position": {"x": 10., "y": 20.}, "target": {"guid": "npc-1"}}
    guard = LoopGuard()
    current = _attempt(baseline=state)
    decisions = [guard.record_attempt_failure(current, "NO_RESPONSE", float(index), state)
                 for index in range(3)]
    assert decisions[-1].level == "SUSPECTED"
    assert decisions[-1].kind == LoopSignatureKind.ACTION.value
    assert decisions[-1].signature.startswith("ACTION:")


def test_semantic_world_delta_prevents_same_action_no_delta_chain():
    baseline = {"position": {"x": 10., "y": 20.}, "target": {"guid": "npc-1"}}
    guard = LoopGuard()
    current = _attempt(baseline=baseline)
    for index in range(3):
        progressed = {"position": {"x": 11. + index, "y": 20.},
                      "target": {"guid": "npc-1", "health": 50 - index}}
        guard.record_attempt_failure(current, "NO_RESPONSE", float(index), progressed)
    assert not any(key.startswith("ACTION:") for key in guard.snapshot())
    assert any(key.startswith("SKILL:") for key in guard.snapshot())


def test_route_target_and_interaction_failures_have_distinct_typed_signatures():
    route_guard = LoopGuard(suspect_count=1)
    route = route_guard.record_attempt_failure(
        _attempt("MOVE", {"map_id": 2175, "route_id": "r1", "segment_id": 4}),
        "PATH_BLOCKED", 1., {})
    target = LoopGuard(suspect_count=1).record_attempt_failure(
        _attempt("TARGET", {"guid": "npc-1"}), "TARGET_NOT_FOUND", 1., {})
    interaction = LoopGuard(suspect_count=1).record_attempt_failure(
        _attempt("INTERACT", {"guid": "npc-1"}), "NO_RESPONSE", 1., {})
    assert any(value.startswith("ROUTE_SEGMENT:")
               for value in route.matching_signatures)
    assert any(value.startswith("TARGET_FAILURE:")
               for value in target.matching_signatures)
    assert any(value.startswith("INTERACTION_CLICK:")
               for value in interaction.matching_signatures)


def test_alternating_opposite_movement_is_detected_and_windowed():
    guard = LoopGuard()
    decisions = [guard.observe_action(binding, float(index)) for index, binding in enumerate(
        ("TURNLEFT", "TURNRIGHT", "TURNLEFT", "TURNRIGHT",
         "TURNLEFT", "TURNRIGHT", "TURNLEFT", "TURNRIGHT"))]
    assert decisions[5].level == "SUSPECTED"
    assert decisions[-1].level == "CONFIRMED"
    assert decisions[-1].kind == LoopSignatureKind.MOVEMENT_OSCILLATION.value


def test_signature_storage_is_globally_bounded():
    guard = LoopGuard(max_signatures=32)
    for index in range(100):
        guard.record_failure(f"failure:{index}", float(index))
    assert len(guard.snapshot()) == 32


def test_supervisor_consumes_loop_signal_as_one_interrupting_replan():
    guard = LoopGuard(suspect_count=1)
    decision = guard.record_failure("interaction:npc-1", 1.)
    supervisor = Supervisor()
    supervisor.notify_loop(decision, 1.)
    directive = supervisor.evaluate({}, None, 2.)
    assert directive.kind is SupervisorDirectiveKind.REPLAN
    assert directive.event.event_type == "LOOP_SUSPECTED_ESCALATED"
    assert supervisor.evaluate({}, None, 3.).kind is SupervisorDirectiveKind.CONTINUE
