"""Who Lurks in the Pit cocoon order (offline, live 2026-10-20 09:36-09:37).

After the first Thick Cocoon (z 60.4) the server-spot rule took the nearest
cocoon in straight 3D: the bottom one (z -0.7) 61 yd right below.  The MOVE
walked down the spiral past the 2nd (4.5 yd, z 33) and the 3rd (2.1 yd,
z 17) with the cursor on them and never stopped; the user pressed F12.  The
first cocoon was also pressed twice: the quest log credited it 0.7 s before
the server removed it.  Coordinates and GUIDs are the live server values.
"""
from types import SimpleNamespace

from wowbot.agent.engine_runtime_projection import movement_visual_interrupt
from wowbot.agent.models import Outcome, Prediction, Proposal
from wowbot.agent.object_interaction_flow import ObjectInteractionFlow
from wowbot.agent.terminal_result import TerminalResultProcessor

PREFIX = "GameObject-0-1465-2175-71046-339568-"
TOP, BOTTOM_EAST, SECOND, BOTTOM, THIRD = (PREFIX + suffix for suffix in (
    "000153399A", "000053399A", "0001D3399A", "000253399A", "0000D3399A"))
COCOONS = {TOP: (80.5, -2279.5, 60.4), BOTTOM_EAST: (123.6, -2238.9, -5.9),
           SECOND: (111.1, -2217.9, 33.0), BOTTOM: (65.3, -2276.6, -0.7),
           THIRD: (36.0, -2199.5, 17.0)}


def cocoon(guid, flags=0xC204, removed=False):
    x, y, z = COCOONS[guid]
    value = {"guid": guid, "kind": "GAMEOBJECT", "entry_id": 339568, "map_id": 2175,
             "info": {"object_kind": "GAMEOBJECT", "quest_objective_id": 391939, "go_type": 10},
             "dynamic_flags": {"value": flags},
             "position": {"x": x, "y": y, "z": z, "source": "PACKET_CREATE_STATIONARY", "age": 5.}}
    if removed:
        value["removed"] = {"reason": "OUT_OF_RANGE", "age": .1}
    return value


def pit(x, y, z, *, spent=(), removed=(), combat=False, now=100.):
    entities = {guid: cocoon(guid, flags=0x200 if guid in spent else 0xC204, removed=guid in removed)
                for guid in COCOONS}
    return {"monotonic_time": now, "map_id": 1409, "is_in_combat": combat, "orientation": 0.,
            "soft_targets": [], "soft_targets_sample_time": now-.1,
            "player_world_position": {"x": x, "y": y, "z": z, "instance_id": 2175,
                                      "coordinate_space": "WORLD_YARDS"},
            "active_quests": [{"quest_id": 55639, "is_complete": False, "objectives": [
                {"objective_id": "55639:0", "type": "INTERACT", "raw_type": "object",
                 "current": 1, "required": 5, "is_complete": False}]}],
            "reference_knowledge": {"quests": {"55639": {"objectives": [
                {"objective_id": 391939, "credit_kind": "GAMEOBJECT", "credit_object_id": 339568,
                 "object_template": {"object_id": 339568, "name": "Thick Cocoon"}, "order": 0}]}}},
            "packet_entities": entities}


def move_to(guid):
    x, y, z = COCOONS[guid]
    return {"x": x, "y": y, "z": z, "purpose": "APPROACH_QUEST_OBJECT_SPAWN", "quest_id": 55639,
            "objective_id": "55639:0", "server_entity_guid": guid, "stop_distance": 2.0}


def test_the_next_cocoon_is_down_the_spiral_not_straight_below():
    flow = ObjectInteractionFlow()
    # 09:36:42: the top cocoon used, the navigation's player layer 61.13.
    spot, known = flow.packet_use_spot(pit(81.4, -2278.4, 61.13, removed={TOP}), 55639, 61.13)
    assert known is True and spot["guid"] == SECOND       # was BOTTOM (61 yd below)


def test_the_spiral_order_is_level_by_level():
    flow = ObjectInteractionFlow()
    order, used = [], {TOP}
    x, y, z = COCOONS[TOP]
    for _ in range(4):
        spot, _known = flow.packet_use_spot(pit(x, y, z, removed=used), 55639, z)
        order.append(spot["guid"])
        used.add(spot["guid"])
        x, y, z = COCOONS[spot["guid"]]
    assert order == [SECOND, THIRD, BOTTOM, BOTTOM_EAST]


def test_a_cocoon_passed_on_the_way_stops_the_walk_to_another():
    flow = ObjectInteractionFlow()
    # 09:37:00: walking to the bottom cocoon, the 2nd one 4.5 yd away, same level.
    live = pit(107.0, -2218.0, 34.04, removed={TOP})
    handoff = flow.object_move_handoff(live, move_to(BOTTOM), 34.04)
    assert handoff["kind"] == "SERVER_QUEST_OBJECT_PASSING" and handoff["guid"] == SECOND
    # The planner then walks to that one; its own MOVE is never interrupted.
    assert flow.packet_use_spot(live, 55639, 34.04)[0]["guid"] == SECOND
    assert flow.object_move_handoff(live, move_to(SECOND), 34.04) is None
    # 09:37:19: the 3rd one 2.1 yd away.
    third = flow.object_move_handoff(pit(37.0, -2197.0, 18.02, removed={TOP, SECOND}), move_to(BOTTOM), 18.02)
    assert third["guid"] == THIRD
    # Passing above/below one, or fighting, does not stop the walk.
    assert flow.object_move_handoff(pit(80.5, -2279.5, 60.4, removed={TOP}), move_to(SECOND), 60.4) is None
    assert flow.object_move_handoff(pit(107.0, -2218.0, 34.04, removed={TOP}, combat=True),
                                    move_to(BOTTOM), 34.04) is None
    assert flow.object_move_handoff(live, move_to(BOTTOM), None) is None    # floor unknown


def test_a_spent_or_removed_target_stops_the_walk():
    flow = ObjectInteractionFlow()
    for live in (pit(81.4, -2278.4, 61.13, removed={TOP}, spent={SECOND}),
                 pit(81.4, -2278.4, 61.13, removed={TOP, SECOND})):
        handoff = flow.object_move_handoff(live, move_to(SECOND), 61.13)
        assert handoff["kind"] == "SERVER_QUEST_OBJECT_CHANGED" and handoff["guid"] == SECOND


def test_the_route_interrupt_hands_the_walk_back_to_the_planner():
    flow = ObjectInteractionFlow()
    live = pit(107.0, -2218.0, 34.04, removed={TOP})
    attempt = SimpleNamespace(proposal=SimpleNamespace(skill="MOVE", parameters=move_to(BOTTOM)))
    interrupt = movement_visual_interrupt(
        attempt, live, object_handoff=lambda params: flow.object_move_handoff(live, params, 34.04))
    assert interrupt["kind"] == "SERVER_QUEST_OBJECT_PASSING"
    # The fast lane (identity only) never acts on it.
    assert movement_visual_interrupt(
        attempt, live, identity_only=True,
        object_handoff=lambda params: flow.object_move_handoff(live, params, 34.04)) is None


def test_a_credited_cocoon_is_not_pressed_again_before_the_server_removes_it():
    flow = ObjectInteractionFlow()
    x, y, z = COCOONS[TOP]
    live = pit(x+1., y, z, now=200.)                    # credit seen, server still shows it
    assert flow.packet_use_spot(live, 55639, z)[0]["guid"] == TOP
    flow.note_result({"action_id": "f55ea071", "skill": "OBJECT_USE", "outcome": "SUCCESS",
                      "reason": "object_use_credit_verified", "object_guid": TOP}, live)
    assert flow.packet_use_spot(live, 55639, z)[0]["guid"] == SECOND
    later = pit(x+1., y, z, now=261.)                   # a respawn may be used again
    assert flow.packet_use_spot(later, 55639, z)[0]["guid"] == TOP


def test_the_result_keeps_the_used_object_guid():
    class Failures:
        def record_failure(self, **kwargs):
            return None
    proposal = Proposal.make("OBJECT_USE", "use", {
        "activation_source": "INTERACT_KEY_PACKET", "object_guid": TOP, "quest_ids": [55639]})
    attempt = SimpleNamespace(proposal=proposal, prediction=Prediction("p", "a", "credit", 1., 3., "o"),
                              action_id="a", plan_id="plan", observation_id="o")
    result = TerminalResultProcessor(Failures(), None).assess(
        attempt, Outcome.SUCCESS, "object_use_credit_verified", 2.,
        latest_observation_id="o2").result_projection
    assert result["object_guid"] == TOP
