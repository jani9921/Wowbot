"""Live 2026-10-11 15:11-15:16 (Austin's two quests, 55184 and 55186).

The agent killed Grek'og (55186 complete) next to the still open Quilboar
area (55184, 3/7), then walked to turn in 55186 and came back:
* a minimap floor arrow -- the finished quest's turn-in "?" on the hill --
  was taken for 55184's objective and led the agent out of the area;
* 121 yd from 55184's POI centre the batching deferral ended (radius 120).
"""
from wowbot.agent.quest_batch_planning import QuestBatchPolicy
from wowbot.agent.quest_location_planning import minimap_vertical_objective_cues

AREA = {"x": 37., "y": -2601., "instance_id": 2175, "coordinate_space": "WORLD_YARDS"}
TURN_IN = {"x": 105., "y": -2415., "instance_id": 2175, "coordinate_space": "WORLD_YARDS"}
QUESTS = [{"quest_id": 55186, "is_complete": True}, {"quest_id": 55184, "is_complete": False}]


def _state(x, y):
    return {"active_quests": QUESTS, "monotonic_time": 1., "orientation": 0.,
            "player_world_position": {"x": x, "y": y, "instance_id": 2175,
                                      "coordinate_space": "WORLD_YARDS"},
            "quest_locations": [{"quest_id": 55184, "world_position": dict(AREA)},
                                {"quest_id": 55186, "world_position": dict(TURN_IN)}]}


def test_waiting_turn_in_keeps_waiting_at_the_objective_area_edge():
    batch = QuestBatchPolicy()
    assert batch.deferred_turnins(_state(19.7, -2523.9), 10.) == {"55186"}    # 79 yd
    assert batch.deferred_turnins(_state(80.9, -2488.5), 11.) == {"55186"}    # 121 yd
    # A fresh policy (nothing waiting yet) still uses the 120 yd start radius.
    assert QuestBatchPolicy().deferred_turnins(_state(80.9, -2488.5), 11.) == frozenset()
    # Far from the open area the turn-in goes ahead.
    assert batch.deferred_turnins(_state(100., -2380.), 12.) == frozenset()


def test_floor_arrow_nearer_a_finished_quest_is_its_turn_in_not_the_open_objective():
    state = _state(19.7, -2523.9)
    # The arrow lies 66 yd from the finished quest's POI, 132 from the open one.
    # Minimap up is world +x, right is world -y.
    offset = [-(-2480.+2523.9)/160., -(90.-19.7)/160.]
    state["visual_candidates"] = [{"kind": "minimap_floor_markers", "source": "MINIMAP_CV",
                                   "view_radius_yards": 160., "observed_at": 1.,
                                   "markers": [{"offset": offset, "floor": "ABOVE"}]}]
    assert minimap_vertical_objective_cues(state) == []
    # The same arrow without the finished quest's POI would be 55184's.
    state["quest_locations"] = state["quest_locations"][:1]
    cues = minimap_vertical_objective_cues(state)
    assert len(cues) == 1 and cues[0][2] == "55184"
    assert abs(cues[0][0]-90.) < 1. and abs(cues[0][1]+2480.) < 1.
