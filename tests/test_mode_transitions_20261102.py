"""Design spec 30.2: travel-mode transitions are a first-class state machine.

preconditions -> action -> verification -> timeout -> recovery/replan.  A sent
mount key is no success (the mount state must change); a takeoff needs a
flying state or a real climb; a landing needs the client grounded and not
falling.  The machine issues no input."""
from types import SimpleNamespace

from wowbot.agent.travel_mode import TravelModePolicy
from wowbot.navigation.mode_transitions import (CONTRACTS, ModeTransitionMachine, TransitionKind, TravelMode,
                                                observed_mode)


def state(mounted=False, flying=False, falling=False, z=10.):
    return {"is_mounted": mounted, "movement": {"flying": flying, "falling": falling},
            "player_world_position": {"x": 0., "y": 0., "z": z, "z_observed": True}}


def test_every_transition_declares_its_whole_contract():
    for kind, contract in CONTRACTS.items():
        assert contract.preconditions and contract.action and contract.verification
        assert contract.timeout_seconds > 0 and contract.recovery and contract.sources
    assert observed_mode(state(mounted=True)) is TravelMode.MOUNTED_GROUND
    assert observed_mode(state(flying=True)) is TravelMode.FLIGHT


def test_a_mount_key_is_verified_only_by_the_mount_state_and_times_out_with_its_recovery():
    machine = ModeTransitionMachine()
    machine.observe(state(), 0.)
    machine.begin(TransitionKind.MOUNT, state(), 1.)
    assert machine.observe(state(), 2.) is None                         # sent, not yet mounted
    done = machine.observe(state(mounted=True), 2.5)
    assert done["outcome"] == "VERIFIED" and done["evidence"] == "mounted_state_observed"
    machine.observe(state(), 3.)
    machine.begin(TransitionKind.MOUNT, state(), 10.)
    failed = machine.observe(state(), 10.+CONTRACTS[TransitionKind.MOUNT].timeout_seconds)
    assert failed["outcome"] == "TIMEOUT" and failed["recovery"] == "avoid_mount_here_then_walk"
    assert machine.recently_failed(TransitionKind.MOUNT, state(), 20.)


def test_takeoff_needs_flight_or_a_climb_and_touchdown_needs_ground_without_falling():
    machine = ModeTransitionMachine()
    machine.observe(state(mounted=True), 0.)
    machine.begin(TransitionKind.TAKEOFF, state(mounted=True), 1.)
    assert machine.observe(state(mounted=True, z=10.5), 2.) is None
    assert machine.observe(state(mounted=True, z=13.), 3.)["outcome"] == "VERIFIED"
    machine.observe(state(mounted=True, flying=True, z=40.), 4.)
    machine.begin(TransitionKind.TOUCHDOWN, state(mounted=True, flying=True, z=40.), 5.)
    assert machine.observe(state(mounted=True, falling=True, z=12.), 6.) is None
    assert machine.observe(state(mounted=True, z=10.), 7.)["outcome"] == "VERIFIED"


def test_observed_transitions_without_an_action_are_recorded_as_facts():
    machine = ModeTransitionMachine()
    machine.observe(state(mounted=True), 0.)
    machine.observe(state(mounted=True, flying=True), 1.)
    machine.observe(state(mounted=True), 2.)
    assert [r["kind"] for r in machine.history] == ["TAKEOFF", "TOUCHDOWN"]


def test_the_travel_mode_policy_starts_a_transition_from_the_executed_mount():
    policy = TravelModePolicy()
    world = SimpleNamespace(state=state(), runtime_context={"last_result": {
        "skill": "MOUNT", "action_id": "m1", "outcome": "SUCCESS"}})
    policy.observe(world, 1.)
    assert policy.transitions.pending["kind"] == "MOUNT"
    world.state = state(mounted=True)
    policy.observe(world, 1.5)
    assert policy.transitions.history[-1]["outcome"] == "VERIFIED"
    assert policy.snapshot()["transitions"]["mode"] == "MOUNTED_GROUND"
