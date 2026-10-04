"""M1 runtime acceptance replays at the canonical engine boundary."""
from wowbot.agent.models import Attempt, Outcome, Prediction, Proposal
from test_agent_core import agent, state


def test_static_block_emits_candidate_then_confirmed_stuck_once():
    value, _ = agent()
    initial = state(1., movement={"moving": False, "speed": 0.})
    value.tick(initial, 1.)
    # The normal deterministic planner may have opened an unrelated WAIT
    # attempt for this empty synthetic quest state. This replay installs the
    # explicit M1 movement contract under test instead.
    value.pending = None
    # With the fixture's orientation=0 this point is already straight ahead;
    # the replay therefore measures absence of movement rather than a normal
    # in-place heading correction.
    proposal = Proposal.make("MOVE", "static-block replay", {"map_id": 1609, "x": .5, "y": .2})
    attempt = Attempt("move-static", proposal, dict(value.world.state),
                      value.world.latest.observation_id, 1., 90., (),
                      Prediction("prediction-static", "move-static", "reach_destination",
                                 1., 90., value.world.latest.observation_id))
    value.pending = attempt
    value.navigation.start(proposal.parameters, value.world.state,
                           value.world.latest.observation_id, 1.)

    # The controller receives several fresh, independent no-progress samples.
    # One early sample is only NO_PROGRESS_YET, then CANDIDATE, then supported
    # hard-stuck evidence. It must not jump directly to recovery.
    for at in (1.3, 1.6, 1.9, 2.2, 2.5, 3.2, 4.3):
        value.tick(state(at, movement={"moving": False, "speed": 0.}), at)

    entries = value.structured_logger.snapshot(128)
    event_types = [entry["event_type"] for entry in entries]
    assert event_types.count("POSSIBLE_STUCK") == 1
    assert event_types.count("STUCK_DETECTED") == 1
    assert next(entry for entry in entries if entry["event_type"] == "POSSIBLE_STUCK")["level"] == "WARN"
    assert next(entry for entry in entries if entry["event_type"] == "STUCK_DETECTED")["level"] == "CRITICAL"
    assert value.last_result["reason"] == "supported_stuck"
    # A fresh planner cadence observes first. Only then does the resolver
    # unlock one bounded physical recovery step; the visual-search proposal
    # that happened to be available must not bypass this chain.
    assert value.pending is None
    assert value.navigation.snapshot(4.3)["stuck_resolver"]["state"] == "STOP_AND_OBSERVE"
    value.tick(state(5., movement={"moving": False, "speed": 0.}), 5.)
    assert value.pending and value.pending.proposal.skill == "RECOVER"
    assert value.pending.proposal.parameters["recovery_step"] == "BACKWARD"

    # A verified recovery does not forget the interrupted REACH objective.
    # The normal planner gets one current-map, current-target revalidated
    # resume candidate; it is not a held-input continuation.
    value._finish(Outcome.SUCCESS, "position_changed", 5.1)
    value.tick(state(6., position={"x": .51, "y": .5},
                     movement={"moving": False, "speed": 0.}), 6.)
    assert value.pending and value.pending.proposal.skill == "MOVE"
    assert value.pending.proposal.parameters["_resume_after_recovery"] is True


def test_manual_mode_discards_a_pending_recovery_resume_context():
    value, _ = agent()
    value._recovery_resume = Proposal.make("MOVE", "old reach", {"map_id": 1609, "x": .5, "y": .2})
    value._recovery_resume_ready = True
    value.set_mode("MANUAL")
    assert value._recovery_resume is None
    assert value._recovery_resume_ready is False
