"""18:14-18:17 live regression: close-in must not become another quest MOVE."""
from types import SimpleNamespace

import pytest

from wowbot.agent.destination_distance import arrived
from wowbot.agent.models import Goal, Proposal
from wowbot.agent.planner import Planner
from wowbot.agent.proposal_ranking import ProposalRanker
from wowbot.agent.quest_location_planning import QuestLocationPlanningPolicy
from test_server_positions_20261020 import HENRY, turn_in_state


@pytest.mark.parametrize("radius_key", ["stop_distance", "arrival_radius"])
def test_explicit_sub_four_yard_radius_is_not_expanded_to_four(radius_key):
    state = turn_in_state()
    state["player_world_position"]["x"] = 37.
    target = {"x": 40., "y": 0., "instance_id": 2175,
              "coordinate_space": "WORLD_YARDS", radius_key: .8}
    assert not arrived(state, target)
    state["player_world_position"]["x"] = 39.3
    assert arrived(state, target)


@pytest.mark.parametrize("invalid", [-1., 0., float("nan"), float("inf"), "bad"])
def test_invalid_explicit_radius_cannot_prove_arrival(invalid):
    assert not arrived(turn_in_state(), {"x": 0., "y": 0., "instance_id": 2175,
        "coordinate_space": "WORLD_YARDS", "stop_distance": invalid})


def test_real_turnin_policy_close_in_survives_ranking_and_keeps_other_quest_out():
    live = turn_in_state(server_mode={"active": True}, soft_targets=[{
        "source_unit": "softinteract", "guid": "Creature-0-1-2175-1-999-1"}],
        soft_targets_sample_time=100.)
    live["player_world_position"]["x"] = 37.
    record = SimpleNamespace(quest_id="55881", current_state="COMPLETED", known_locations=())
    (close_in,) = QuestLocationPlanningPolicy().propose_turnins({"55881": record}, live, {})
    assert close_in.parameters["stop_distance"] == .8
    other = Proposal.make("MOVE", "other quest", {
        "x": 80., "y": 0., "instance_id": 2175, "coordinate_space": "WORLD_YARDS",
        "purpose": "LOCATE_QUEST_OBJECTIVE_REGION", "quest_id": 999, "stop_distance": 8.}, priority=96)
    world = SimpleNamespace(state=live, distance=lambda _: None)
    registry = SimpleNamespace(available=lambda *_: True, contracts={})
    ranked = ProposalRanker.rank([close_in, other], goal=Goal.parse("Questelj", 1),
        world=world, now=100., registry=registry, memory=None,
        blocked_until={}, recent={}, evidence=()).proposals
    assert ranked[0].parameters["server_entity_guid"] == HENRY
    preferred = Planner.prefer_server_targets(list(ranked), server_mode=True)
    assert [p.parameters.get("server_entity_guid") for p in preferred] == [HENRY]


def test_at_the_close_in_point_unknown_recipient_means_wait_not_other_quest():
    live = turn_in_state(server_mode={"active": True})
    live["player_world_position"]["x"] = 39.3
    record = SimpleNamespace(quest_id="55881", current_state="COMPLETED", known_locations=())
    (hold,) = QuestLocationPlanningPolicy().propose_turnins({"55881": record}, live, {})
    assert hold.skill == "WAIT" and hold.parameters["waiting_for"] == ["SOFT_INTERACT_GUID_MATCH"]
