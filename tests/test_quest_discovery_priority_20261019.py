"""Post-turn-in discovery: live quest pins precede unrelated UNKNOWN bodies."""
from pathlib import Path

import pytest

from wowbot.agent.models import Goal, Proposal
from wowbot.agent.planner import Planner
from wowbot.agent.skills import SkillRegistry
from wowbot.agent.world import WorldModel


ROOT = Path(__file__).resolve().parents[1]
ADDON = ROOT / "addon" / "AIPlayerControllerExport" / "AIPlayerControllerExport.lua"


def _body(track="unrelated", *, marked=False):
    return {
        "source": "WORLD3D", "kind": "unknown_subject_candidate",
        "detector_kind": "unknown_subject_candidate", "track_id": track,
        "x": .65, "y": .45, "confidence": .9, "stable_frames": 30,
        "age": 2., "observed_at": 100., "lifecycle": "ACTIVE", "inspectable": True,
        "bbox_width_fraction": .03, "bbox_height_fraction": .075,
        "candidate_labels": ["learned_subject_like"],
        "appearance": {"learned_label_hypothesis": "creature_unit_like",
                       **({"quest_badge_likeness": .9} if marked else {})},
    }


def _pin():
    # Reduced from the user's recording: actual public map conversion, not
    # a made-up hover XYZ. The NPC must still be identified at the pin.
    return {"quest_id": 55194, "quest_name": "Stocking Up on Supplies",
            "map_id": 1409, "x": .52414, "y": .55379,
            "is_campaign": True, "source": "QUESTLINE_API",
            "coordinate_space": "NORMALIZED_MAP",
            "world_position": {"x": 185., "y": -2291., "instance_id": 2175,
                               "coordinate_space": "WORLD_YARDS", "z_known": False}}


def _world(*, pins=(), bodies=(), **overrides):
    world = WorldModel()
    world.session_id = "quest-discovery:player"
    world.state = {
        "session_id": world.session_id, "map_id": 1409, "monotonic_time": 100.,
        "state_sample_time": 100., "position": {"x": .5274, "y": .5384},
        "player_world_position": {"x": 219.6, "y": -2302.1, "instance_id": 2175,
                                  "coordinate_space": "WORLD_YARDS", "z_known": False},
        "orientation": 0., "world_map_open": False, "is_in_combat": False,
        "is_casting": False, "target": {}, "active_quests": [],
        "map_pois": {"available_quests": list(pins)},
        "visual_candidates": list(bodies), **overrides,
    }
    return world


def _plan(world, planner=None, now=100.):
    planner = planner or Planner(SkillRegistry())
    return planner, planner.candidates(Goal.parse("Questelj", now), world, now)


@pytest.mark.parametrize("marked", [False, True])
def test_live_giver_route_is_not_replaced_by_regenerated_generic_seek(marked):
    _, proposals = _plan(_world(pins=[_pin()], bodies=[_body(marked=marked)]))
    assert proposals[0].skill == "MOVE"
    assert proposals[0].parameters["purpose"] == "LOCATE_API_QUEST_GIVER"
    assert proposals[0].parameters["quest_id"] == 55194
    assert all(p.skill not in {"INSPECT", "SEEK_VISUAL_CUE", "OPEN_MAP"} for p in proposals)


def test_without_a_local_quest_cue_request_map_discovery_before_random_bodies():
    _, proposals = _plan(_world(bodies=[_body()]))
    assert proposals[0].skill == "OPEN_MAP"
    assert proposals[0].parameters["purpose"] == "DISCOVER_AVAILABLE_QUESTS"
    assert not any(p.skill in {"INSPECT", "SEEK_VISUAL_CUE"} for p in proposals)


def test_actual_local_quest_marker_keeps_a_bounded_identification_opportunity():
    _, proposals = _plan(_world(bodies=[_body(marked=True)]))
    assert proposals[0].skill in {"INSPECT", "SEEK_VISUAL_CUE"}
    planner, _ = _plan(_world(bodies=[_body(marked=True)]))
    planner.world3d_probe_count = 4
    _, exhausted = _plan(_world(bodies=[_body(marked=True)]), planner, 101.)
    assert exhausted[0].skill == "OPEN_MAP"


def test_at_a_live_giver_pin_identification_still_runs_instead_of_reopening_map():
    pin = _pin()
    pin["world_position"]["x"] = 218.
    pin["world_position"]["y"] = -2302.
    _, proposals = _plan(_world(pins=[pin], bodies=[_body()]))
    assert proposals[0].skill in {"INSPECT", "SEEK_VISUAL_CUE"}


def test_only_explicit_route_handoff_may_pause_the_api_giver_route():
    world = _world(pins=[_pin()], bodies=[_body("marked", marked=True), _body("other")])
    planner, _ = _plan(world)
    planner.arm_movement_visual_handoff(
        {"track_id": "marked", "route_purpose": "LOCATE_API_QUEST_GIVER"}, 100.)
    _, proposals = _plan(world, planner, 100.1)
    assert proposals[0].skill in {"INSPECT", "SEEK_VISUAL_CUE"}
    assert proposals[0].parameters["track_id"] == "marked"
    assert not any(p.skill in {"INSPECT", "SEEK_VISUAL_CUE"}
                   and p.parameters.get("track_id") != "marked" for p in proposals)
    _, resumed = _plan(world, planner, 102.)
    assert resumed[0].skill == "MOVE"
    assert resumed[0].parameters["purpose"] == "LOCATE_API_QUEST_GIVER"


def test_failed_route_allows_discovery_but_missing_move_capability_is_not_bypassed(monkeypatch):
    world = _world(pins=[_pin()], bodies=[_body()])
    planner, proposals = _plan(world)
    route = next(p for p in proposals if p.skill == "MOVE")
    planner.blocked_until[route.key] = 200.
    _, after = _plan(world, planner, 101.)
    assert after[0].skill != "WAIT"
    assert not any(p.key == route.key for p in after)
    original = planner.registry.available
    monkeypatch.setattr(planner.registry, "available", lambda p, w:
                        p.skill != "MOVE" and original(p, w))
    planner.blocked_until.clear()
    _, unavailable = _plan(world, planner, 102.)
    assert unavailable[0].skill == "WAIT"
    assert "MOVE" in unavailable[0].parameters["unavailable_skills"]


def test_map_discovery_cooldown_is_not_bypassed_by_unmarked_tracks():
    planner = Planner(SkillRegistry())
    planner.map_search_policy.state.reopen_blocked_until = 120.
    _, proposals = _plan(_world(bodies=[_body()]), planner)
    assert all(p.skill != "OPEN_MAP" for p in proposals)


@pytest.mark.parametrize("event", ["QUEST_TURNED_IN", "QUEST_ACCEPTED", "QUEST_REMOVED"])
def test_quest_change_requests_new_pins_without_waiting_for_old_request_throttle(event):
    lupa = pytest.importorskip("lupa")
    source = ADDON.read_text(encoding="utf-8")
    body = source[source.index("local mapPoiCache"):source.index("local function readQuestLocations")]
    harness = '''
local clock, requests, reads = 100, 0, 0
local function nowSeconds() return clock end
local function accessible(_) return true end
local function optionalNumber(v) return type(v) == "number" and v or nil end
local function optionalBool(v) return type(v) == "boolean" and v or nil end
local function bool(v) return v == true end
local function safeText(v, default) return type(v) == "string" and v or default end
local function safeCall(fn, ...) return fn(...) end
local function mapToWorldPosition(map, x, y)
    return {x=x, y=y, instance_id=2175, coordinate_space="WORLD_YARDS"}
end
C_Map = {GetMapInfo=function() return {mapType=3} end}
C_QuestLine = {
    RequestQuestLinesForMap=function(_) requests=requests+1 end,
    GetAvailableQuestLines=function(_)
        reads=reads+1
        return requests >= 2 and {{questID=55194, questName="Next", x=.5, y=.6}} or {}
    end
}
''' + body + '''
local before = readMapPOIs(1409)
assert(requests == 1 and #before.available_quests == 0)
clock = 101
invalidateMapPOIs(EVENT)
local after = readMapPOIs(1409)
assert(requests == 2 and #after.available_quests == 1)
clock = 101.1
invalidateMapPOIs("QUESTLINE_UPDATE")
readMapPOIs(1409)
assert(requests == 2 and reads == 3) -- async reply: reread, never request storm
clock = 102
invalidateMapPOIs("QUEST_LOG_UPDATE")
readMapPOIs(1409)
assert(requests == 2 and reads == 3) -- generic log ticks keep the cache
clock = 118
readMapPOIs(1409)
assert(requests == 3) -- normal periodic refresh remains available
return true
'''
    runtime = lupa.LuaRuntime()
    runtime.globals().EVENT = event
    assert runtime.execute(harness) is True
    on_event = source[source.index('frame:SetScript("OnEvent"'):]
    assert "invalidateMapPOIs(event)" in on_event
