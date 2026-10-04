import pytest

from wowbot.agent.target_manager import TargetLifecycle, TargetManager, TargetScoringPolicy


def test_target_manager_keeps_current_target_until_margin_is_exceeded():
    manager=TargetManager(); manager.select([{"guid":"a","hostility":1,"quest_relevance":1}])
    assert manager.select([{"guid":"a","hostility":1,"quest_relevance":1},{"guid":"b","hostility":1,"quest_relevance":1.01}]).entity_id=="a"


def test_target_switch_requires_strictly_more_than_the_configured_margin():
    manager = TargetManager(switch_margin=.20)
    manager.select([{"guid": "a", "reachability": 0., "visibility": 0.,
                     "quest_relevance": .5}])
    # quest weight is 2.0, so +.10 input is exactly +.20 total score.
    tied_margin = manager.select([
        {"guid": "a", "reachability": 0., "visibility": 0., "quest_relevance": .5},
        {"guid": "b", "reachability": 0., "visibility": 0., "quest_relevance": .6},
    ])
    assert tied_margin.entity_id == "a"
    switched = manager.select([
        {"guid": "a", "reachability": 0., "visibility": 0., "quest_relevance": .5},
        {"guid": "b", "reachability": 0., "visibility": 0., "quest_relevance": .61},
    ])
    assert switched.entity_id == "b"


def test_target_manager_keeps_scores_as_evidence_and_requires_a_live_guid():
    policy = TargetScoringPolicy(quest_relevance=3.0, hostility=0.0)
    manager = TargetManager(policy=policy)

    chosen = manager.select([
        {"quest_relevance": 1.0},  # A visual/template proposal is not selectable.
        {"guid": "Creature-0-0-0-0-12-00000001", "quest_relevance": 0.5},
    ])

    assert chosen is not None
    assert chosen.total_score == 3.3  # quest 1.5 + default reachability 1 + visibility .8
    assert chosen.components["quest_relevance"] == 1.5
    assert manager.lifecycle is TargetLifecycle.CANDIDATE
    assert len(manager.snapshot()["candidates"]) == 1


def test_candidate_contract_exposes_normalized_scores_and_weighted_penalties():
    candidate = TargetManager().select([{
        "guid": "Creature-12", "quest_relevance": 2., "hostility": -1.,
        "reachability": .7, "visibility": .6, "threat": .5,
        "distance_preference": .4, "recent_failure_penalty": .3,
        "unreachable_penalty": .2,
    }])
    assert candidate.quest_relevance_score == 1.
    assert candidate.hostility_score == 0.
    assert candidate.reachability_score == .7
    assert candidate.visibility_score == .6
    assert candidate.threat_score == .5
    assert candidate.distance_score == .4
    assert candidate.recent_failure_penalty == .3
    assert candidate.unreachable_penalty == .2
    assert candidate.total_score == pytest.approx(2.83)


def test_target_lifecycle_is_driven_by_selected_target_telemetry():
    guid = "Creature-0-0-0-0-12-00000001"
    manager = TargetManager()
    manager.select([{"guid": guid, "hostility": 1.0}])

    assert manager.mark_acquiring(guid)
    assert manager.lifecycle is TargetLifecycle.ACQUIRING
    assert manager.observe_selected({"guid": guid, "attackable": True}) is TargetLifecycle.ACQUIRED
    assert manager.observe_selected({"guid": guid, "attackable": True}, in_combat=True) is TargetLifecycle.ENGAGED
    assert manager.observe_selected({"guid": guid, "dead": True}) is TargetLifecycle.DEAD


def test_selected_guid_change_reacquires_instead_of_promoting_a_new_entity():
    manager = TargetManager()
    manager.select([{"guid": "a", "hostility": 1.0}])

    assert manager.observe_selected({"guid": "b", "attackable": True}) is TargetLifecycle.REACQUIRING
    assert manager.current_id == "a"


def test_committed_target_survives_occlusion_and_requires_selected_guid_to_confirm_reacquisition():
    guid, track_id = "Creature-12", "WORLD3D:17"
    manager = TargetManager()
    manager.select([{"guid": guid, "hostility": 1.0}])
    assert manager.observe_selected(
        {"guid": guid, "attackable": True, "visual_track_id": track_id},
        in_combat=True, at=1.0,
    ) is TargetLifecycle.ENGAGED

    # The candidate feed and selected target may both briefly disappear. The
    # exact committed GUID/track identity must survive that observation.
    assert manager.select([]) is None
    assert manager.observe_selected(
        {}, in_combat=True, at=1.2,
        visual_tracks=[{"track_id": track_id, "lifecycle": "OCCLUDED"}],
    ) is TargetLifecycle.OCCLUDED
    assert manager.current_id == guid
    assert manager.current_track_id == track_id

    # A matching visual track returning is evidence for reacquisition, not CV
    # authority to claim that the client target is already selected.
    assert manager.observe_selected(
        {}, in_combat=True, at=1.5,
        visual_tracks=[{"track_id": track_id, "lifecycle": "REACQUIRED"}],
    ) is TargetLifecycle.REACQUIRING
    assert manager.current_id == guid

    # Only addon selected-target telemetry closes the loop.
    assert manager.observe_selected(
        {"guid": guid, "attackable": True, "visual_track_id": track_id},
        in_combat=True, at=1.6,
    ) is TargetLifecycle.ENGAGED
    assert manager.snapshot()["current_track_id"] == track_id


def test_committed_target_occlusion_budget_terminates_as_lost():
    manager = TargetManager()
    manager.select([{"guid": "Creature-12", "hostility": 1.0}])
    manager.observe_selected({"guid": "Creature-12", "attackable": True}, at=1.0)
    assert manager.observe_selected({}, at=1.1) is TargetLifecycle.OCCLUDED
    assert manager.observe_selected({}, at=2.7) is TargetLifecycle.LOST
