"""Live 2026-10-04 09:15: inside the Quilboar Shadow Magic area at 1/7 the
agent left for Down with the Quilboar (its route MOVE and its minimap dot
won while no quilboar was in view) -- the user saw it pick the farther quest."""
from wowbot.agent.models import Observation
from wowbot.agent.quest_location_planning import QuestLocationPlanningPolicy
from wowbot.agent.world import WorldModel


def _poi(quest_id, x, y):
    return {"quest_id": quest_id, "map_id": 1409, "x": .6, "y": .7, "source": "QUEST_POI",
            "coordinate_space": "NORMALIZED_MAP",
            "world_position": {"x": x, "y": y, "instance_id": 2175, "ui_map_id": 1409,
                               "coordinate_space": "WORLD_YARDS", "source": "C_MAP_WORLD_POS"}}


QUESTS = [{"quest_id": 55186, "is_complete": False, "objectives": [{"description": "0/1 Geolord Grek'og slain"}]},
          {"quest_id": 55184, "is_complete": False, "objectives": [{"description": "1/7 Quilboar slain"}]}]
DOTS = {"kind": "minimap_quest_dot", "source": "MINIMAP_CV", "view_radius_yards": 233.3,
        "dots": [{"offset": [0., -.3], "distance_fraction": .3, "pixels": 4}]}   # ~70 yd north: Grek'og


def _world(at):
    world = WorldModel()
    world.ingest(Observation.create({
        "session_id": "f", "timestamp": at, "frame_id": f"f{at}", "monotonic_time": at, "map_id": 1409,
        "orientation": 0., "position": {"x": .6, "y": .7}, "player_present": True,
        "player_world_position": {"x": 25., "y": -2591., "instance_id": 2175, "coordinate_space": "WORLD_YARDS"},
        "active_quests": QUESTS, "quest_locations": [_poi(55186, 18., -2509.), _poi(55184, 37., -2601.)],
        "visual_candidates": [DOTS], "world_map_open": False}, at))
    return world


def test_other_quest_moves_wait_while_inside_an_open_quest_area():
    policy = QuestLocationPlanningPolicy()
    inside = policy.propose_known_locations(_world(100.))
    assert not any(p.parameters.get("quest_id") == 55186 for p in inside)
    # Bounded: after the focus window the other quest may be pursued.
    later = policy.propose_known_locations(_world(100. + policy.LOCAL_AREA_FOCUS_SECONDS + 1.))
    assert any(p.parameters.get("quest_id") == 55186 for p in later)
