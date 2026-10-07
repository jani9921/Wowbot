"""Quest objective area from the minimap's blue outline (user 2026-10-03).

Offline check on 1411 live Exile's Reach minimap crops: 597 closed outlines,
the API POI fell inside the outline's box in 585 and lay within ~4 yd of the
learned area in 90 % -- the outline is the quest area the API only points to.
"""
import numpy as np

from wowbot.agent.quest_area_memory import QuestAreaMemory
from wowbot.agent.visual_search_planning import VisualSearchPlanningPolicy
from wowbot.vision.minimap_quest_area import detect_quest_area, offsets_to_world

OUTLINE = (73, 115, 146)     # measured live
TERRAIN = (70, 60, 40)


def _minimap(rect, size=100, radius=45):
    """A terrain disc with a blue rectangle outline (left, top, right, bottom)."""
    image = np.zeros((size, size, 3), dtype=np.uint8)
    image[:] = (120, 170, 210)                       # bluish sky outside the disc
    yy, xx = np.mgrid[0:size, 0:size]
    disc = (xx-size/2)**2 + (yy-size/2)**2 <= radius**2
    image[disc] = TERRAIN
    left, top, right, bottom = rect
    image[top:bottom+1, [left, left+1, right-1, right]] = OUTLINE
    image[[top, top+1, bottom-1, bottom], left:right+1] = OUTLINE
    return image, (size/2, size/2), radius


def test_closed_outline_gives_the_area_and_whether_the_player_is_inside():
    image, centre, radius = _minimap((40, 40, 62, 62))
    area = detect_quest_area(image, centre, radius)
    assert area["closed"] and area["player_inside"]
    xs = [dx for dx, _ in area["offsets"]]
    assert min(xs) < -.15 and max(xs) > .2
    away, centre, radius = _minimap((15, 15, 35, 35))
    assert detect_quest_area(away, centre, radius)["player_inside"] is False


def test_sky_outside_the_disc_is_not_a_quest_area():
    image, centre, radius = _minimap((0, 0, 0, 0))
    image[0:2, 0:2] = TERRAIN
    assert detect_quest_area(image, centre, radius) is None


def test_offsets_follow_the_world_axes():
    # North-up: screen up = north (+x), screen left = west (+y).
    north, west = offsets_to_world([[0., -.5], [-.5, 0.]], player_x=100., player_y=200.,
                                   view_radius_yards=160.)
    assert north == (180., 200.) and west == (100., 280.)
    # Rotating minimap facing west (pi/2): screen up = west.
    up, = offsets_to_world([[0., -.5]], player_x=0., player_y=0., view_radius_yards=160.,
                           rotate=True, facing=np.pi/2)
    assert abs(up[0]) < 1e-9 and abs(up[1]-80.) < 1e-9


def _state(player, offsets, closed=True, inside=False, view=160.):
    return {"player_world_position": {"x": player[0], "y": player[1], "instance_id": 2175},
            "orientation": 0.,
            "active_quests": [{"quest_id": 55174, "is_complete": False,
                               "objectives": [{"type": "COLLECT", "is_complete": False}]}],
            "quest_locations": [{"quest_id": 55174, "map_id": 1409, "x": .58, "y": .72,
                                 "world_position": {"x": -196., "y": -2507., "instance_id": 2175,
                                                    "coordinate_space": "WORLD_YARDS"}}],
            "visual_candidates": [{"kind": "minimap_quest_area", "source": "MINIMAP_CV",
                                   "observed_at": float(len(offsets)), "view_radius_yards": view,
                                   "quest_area": {"closed": closed, "offsets": offsets,
                                                  "player_inside": inside}}]}


def test_memory_attaches_the_area_to_the_quest_whose_poi_it_contains():
    memory = QuestAreaMemory()
    # Player 60 yd south of the POI; the outline spans the POI +-20 yd.
    offsets = [[dx/160., dy/160.] for dx in range(-20, 21, 4) for dy in range(-80, -39, 4)]
    assert memory.observe(_state((-256., -2507.), offsets)) == "55174"
    assert memory.contains(55174, -196., -2507.)
    assert not memory.contains(55174, -256., -2507.)
    points = memory.coverage_points(55174)
    assert 4 <= len(points) <= 12
    assert all(abs(p["x"]+196.) <= 24 and abs(p["y"]+2507.) <= 24 for p in points)
    # An outline far from every POI is someone else's area: ignored.
    stranger = [[dx/160., dy/160.] for dx in range(60, 70, 4) for dy in range(60, 70, 4)]
    assert QuestAreaMemory().observe(_state((-256., -2507.), stranger)) is None


def test_roaming_uses_the_learned_shape():
    memory = QuestAreaMemory()
    offsets = [[dx/160., dy/160.] for dx in range(-20, 21, 4) for dy in range(-80, -39, 4)]
    state = _state((-256., -2507.), offsets)
    memory.observe(state)
    area = VisualSearchPlanningPolicy.active_quest_area(state, memory)
    assert area["search_area"]["region_source"] == "MINIMAP_QUEST_AREA_OUTLINE"
    assert area["search_area"]["coverage_points"]
    assert VisualSearchPlanningPolicy.active_quest_area(state)["search_area"]["radius"] == 30.


def test_learned_area_is_scoped_to_its_instance():
    """Issue #96: the same X/Y in another instance counted as arrival."""
    memory = QuestAreaMemory()
    offsets = [[dx/160., dy/160.] for dx in range(-20, 21, 4) for dy in range(-80, -39, 4)]
    assert memory.observe(_state((-256., -2507.), offsets)) == "55174"
    assert memory.contains(55174, -196., -2507., 2175)
    assert not memory.contains(55174, -196., -2507., 9999)

    from wowbot.agent.quest_location_planning import QuestLocationPlanningPolicy
    policy = QuestLocationPlanningPolicy.__new__(QuestLocationPlanningPolicy)
    policy.quest_areas = memory
    destination = {"x": -196., "y": -2507., "instance_id": 2}
    other = {"player_world_position": {"x": -196., "y": -2507., "instance_id": 1}}
    assert not policy._within_objective_area(destination, other, 55174)
    same = {"player_world_position": {"x": -196., "y": -2507., "instance_id": 2175}}
    assert policy._within_objective_area({**destination, "instance_id": 2175}, same, 55174)
