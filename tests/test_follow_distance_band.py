from wowbot.agent.movement_controller import MovementPhase, ReachMovementController


def _state(player_x, leader_x, *, sample_time=None):
    leader = {"map_id": 1, "x": leader_x, "y": .5}
    if sample_time is not None:
        leader["sample_time"] = sample_time
    return {"map_id": 1, "position": {"x": player_x, "y": .5}, "orientation": 0.,
            "group_state": {"leader_guid": "leader", "leader_position": leader},
            "monotonic_time": 1., "movement": {"moving": False, "speed": 0.}}


def test_follow_refreshes_leader_position_and_holds_inside_distance_band():
    controller = ReachMovementController()
    destination = {"map_id": 1, "x": .6, "y": .5, "follow_group_leader": True,
                   "follow_entity_guid": "leader", "follow_min_distance": .003,
                   "follow_max_distance": .008}
    controller.start(destination, _state(.5, .51), "one", 1.)
    assessment = controller.observe(_state(.5, .505), "two", 1.1)

    assert assessment.phase is MovementPhase.MOVING
    assert assessment.reason == "follow_distance_band"
    assert controller.command(_state(.5, .505), "two", 1.1) == ()


def test_follow_rejects_stale_or_wrong_leader_identity_instead_of_chasing_old_position():
    controller = ReachMovementController()
    destination = {"map_id": 1, "x": .6, "y": .5, "follow_group_leader": True,
                   "follow_entity_guid": "leader", "follow_max_distance": .008}
    controller.start(destination, _state(.5, .6), "one", 1.)
    stale = _state(.5, .6, sample_time=1.)
    stale["monotonic_time"] = 5.
    assessment = controller.observe(stale, "two", 5.)

    assert assessment.terminal and assessment.reason == "reach_object_identity_or_position_lost"
