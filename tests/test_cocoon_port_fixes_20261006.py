"""Fixes made while porting the working copy's cocoon/cave changes (2026-10-06).

Live evidence: the user's 09:42 run (hunter pet hover, frozen world) and the
working copy's 20:07-20:14 runs (late cocoon credit, ambiguous floor stalls).
"""
import json
from types import SimpleNamespace

from adapters.telemetry_packets import PacketAssembler
from test_agent_core import state
from wowbot.agent.engine_runtime_projection import movement_visual_interrupt
from wowbot.agent.models import Attempt, Observation, Prediction, Proposal
from wowbot.agent.navigation import AgentNavigator
from wowbot.agent.object_interaction_flow import only_object_objectives_open
from wowbot.agent.world import WorldModel
from wowbot.runtime import ActiveSkillRuntime, Intent, SkillStatus
from wowbot.skills import ObjectUseSkill


# -- OBJECT_USE: the credit arrives with the next complete STATE ------------

def _cocoon(**extra):
    return {"mouseover": {"tooltip": "Thick Cocoon"}, "cursor_position": {"nx": .4, "ny": .6},
            "active_quests": [{"quest_id": 55639, "objectives": [
                {"objective_id": "0", "current": 0, "required": 5, "is_complete": False}]}],
            **extra}


def _use():
    params = {"x": .4, "y": .6, "mouseover_tooltip": "Thick Cocoon",
              "quest_ids": [55639], "objective_ids": ["55639:0"]}
    before = _cocoon()
    attempt = Attempt("action", Proposal.make("OBJECT_USE", "test", params), before,
                      "obs", 1., 9., (), Prediction("prediction", "action", "state", 1., 9., "obs"))
    return ActiveSkillRuntime().start(intent=Intent("OBJECT_USE", params, None, "55639:0"),
                                       attempt=attempt, now=1., before_snapshot=before)


def test_object_use_waits_for_a_full_snapshot_sampled_after_the_click():
    """Live 20:07: 0/5 -> 1/5 was visible 2 s after the 8 s deadline."""
    skill, run = ObjectUseSkill(), _use()
    assert skill.begin(run, _cocoon()).commands[0].kind == "HOVER"
    run.phase = "VERIFY"
    clicked = skill.verify(run, _cocoon(), 1.2)
    assert clicked.commands[0].kind == "CLICK"
    old_snapshot = _cocoon(state_sample_time=.9)
    late = skill.verify(run, old_snapshot, 9.5)
    assert late.status is SkillStatus.RUNNING and not late.commands
    credited = _cocoon(state_sample_time=10.5, active_quests=[{"quest_id": 55639, "objectives": [
        {"objective_id": "0", "current": 1, "required": 5, "is_complete": False}]}])
    assert skill.verify(run, credited, 11.).status is SkillStatus.SUCCESS


def test_object_use_still_fails_when_a_newer_snapshot_shows_no_credit():
    skill, run = ObjectUseSkill(), _use()
    skill.begin(run, _cocoon())
    run.phase = "VERIFY"
    skill.verify(run, _cocoon(), 1.2)
    newer = skill.verify(run, _cocoon(state_sample_time=5.), 9.5)
    assert newer.status is SkillStatus.FAILURE
    # ... and the grace is bounded even without any newer snapshot.
    skill2, run2 = ObjectUseSkill(), _use()
    skill2.begin(run2, _cocoon())
    run2.phase = "VERIFY"
    skill2.verify(run2, _cocoon(), 1.2)
    assert skill2.verify(run2, _cocoon(state_sample_time=.9), 19.5).status is SkillStatus.FAILURE


# -- FAST packets without an epoch timestamp ---------------------------------

def _packet(seq, kind, body):
    return f"AIPC5|s|{seq}|0|1|{kind}|{json.dumps(body)}"


def test_bounded_fast_variant_gets_a_timestamp_and_is_not_dropped_as_old():
    """Live 09:42: hovering a hunter pet overflowed FAST into the edge variant
    without ``timestamp``; WorldModel dropped 25 s of packets as out-of-order."""
    assembler = PacketAssembler()
    assembler.feed(_packet(1, "STATE", {"monotonic_time": 10., "timestamp": 1000,
                                        "character_name": "Test", "map_id": 1409}), 10.)
    stamped = assembler.feed(_packet(2, "FAST", {"monotonic_time": 11., "timestamp": 1001,
                                                 "map_id": 1409}), 11.)
    edge = assembler.feed(_packet(3, "FAST", {"monotonic_time": 13.7, "map_id": 1409,
                                              "mouseover": {"name": "Gruffhorn"}}), 13.7)
    assert stamped["timestamp"] == 1001 and edge["timestamp"] == 1003   # floor(1001 + 2.7)

    world = WorldModel()
    assert world.ingest(Observation.create(state(1., timestamp=1000), 1.))
    unstamped = {**state(2.), "transport_kind": "FAST", "frame_id": "s:FAST:9"}
    unstamped.pop("timestamp", None)
    assert world.ingest(Observation.create(unstamped, 2.))


# -- standing (INSPECT, loot) is not a circling route ------------------------

def _nav_world(position):
    return SimpleNamespace(state={"map_id": 1409},
                           distance=lambda destination: .1,
                           player_position=lambda: position)


def test_route_is_not_blocked_while_the_player_stands_still():
    """Live 09:42: a 6 s INSPECT after a MOVE banned the zone-sweep hop."""
    navigator, destination = AgentNavigator(), {"x": .5, "y": .5}
    standing = _nav_world((.3, .3))
    assert all(navigator.permits(standing, destination, at) for at in (0., 5., 13., 20., 30.))


def test_circling_without_getting_closer_is_still_blocked():
    navigator, destination = AgentNavigator(), {"x": .5, "y": .5}
    assert navigator.permits(_nav_world((.3, .3)), destination, 0.)
    allowed = [navigator.permits(_nav_world((.3 + .002*(i % 2), .3 + .002*i)), destination, float(i))
               for i in range(1, 16)]
    assert allowed[-1] is False


# -- a cocoon objective: passing creatures are no cue ------------------------

COCOON_QUEST = [{"quest_id": 55639, "is_complete": False, "objectives": [
    {"raw_type": "object", "type": "INTERACT", "is_complete": False,
     "description": "0/5 Trapped Expedition Member rescued from cocoons"}]}]


def test_only_object_objectives_detects_a_cocoon_quest():
    assert only_object_objectives_open({"active_quests": COCOON_QUEST})
    kill = [{"quest_id": 1, "objectives": [{"raw_type": "monster", "is_complete": False}]}]
    assert not only_object_objectives_open({"active_quests": COCOON_QUEST + kill})
    assert not only_object_objectives_open({"active_quests": [{**COCOON_QUEST[0], "is_complete": True}]})
    assert not only_object_objectives_open({"active_quests": []})


def test_hunter_pet_does_not_interrupt_the_cocoon_sweep():
    attempt = SimpleNamespace(proposal=Proposal.make("MOVE", "sweep", {
        "purpose": "SEARCH_LOCAL_OBJECTIVE_AREA", "quest_id": 55639,
        "coordinate_space": "WORLD_YARDS", "instance_id": 2175, "x": 85., "y": -2208.}))
    pet = {"source": "WORLD3D", "kind": "unknown_subject_candidate", "track_id": "WORLD3D_30",
           "confidence": .8, "stable_frames": 30, "lifecycle": "STABLE", "inspectable": True,
           "observed_at": 4., "candidate_labels": ["learned_subject_like"],
           "appearance": {"learned_label_hypothesis": "creature_unit_like"}}
    observed = {"monotonic_time": 4., "active_quests": COCOON_QUEST,
                "player_world_position": {"x": 86., "y": -2210., "instance_id": 2175},
                "visual_candidates": [pet]}
    assert movement_visual_interrupt(attempt, observed) is None


# -- "You are too far away." -> approach, then use ---------------------------

def test_too_far_cocoon_is_approached_before_another_click():
    """Live 21:16: a lower cocoon answered the click with "You are too far
    away."; the agent clicked again and walked off.  Approach to a larger box
    first (6 s, or until the approach finishes)."""
    from wowbot.agent.object_interaction_flow import ObjectInteractionFlow
    flow = ObjectInteractionFlow()
    box = {"source": "WORLD3D", "track_id": "WORLD3D:41", "confidence": .7, "stable_frames": 9,
           "lifecycle": "ACTIVE", "bbox_height_fraction": .2,
           "candidate_labels": ["quest_object_like"]}
    seen = {"monotonic_time": 100., "visual_candidates": [box]}
    flow.note_result({"action_id": "a1", "skill": "OBJECT_USE", "outcome": "FAILURE",
                      "reason": "out_of_range"}, seen)
    assert flow.range_blocked(seen) and abs(flow.object_ready_height() - .26) < 1e-9
    objective = SimpleNamespace(objective_id="55639:0", type="INTERACT", target_object={},
                                raw={"raw_type": "object"},
                                description="0/5 Trapped Expedition Member rescued from cocoons")
    seek = flow.propose_object_steps(objective, SimpleNamespace(quest_id=55639), seen)[0]
    assert seek.skill == "SEEK_VISUAL_CUE" and seek.priority == 93
    assert seek.parameters["ready_bbox_height"] == flow.object_ready_height()
    flow.note_result({"action_id": "a2", "skill": "SEEK_VISUAL_CUE", "outcome": "SUCCESS"}, seen)
    assert not flow.range_blocked(seen)
    flow.note_result({"action_id": "a3", "skill": "OBJECT_USE", "reason": "out_of_range"}, seen)
    assert not flow.range_blocked({"monotonic_time": 106.5})


# -- the ramp under the rim: follow the route, never turn back ---------------

def test_continuity_follows_the_route_down_a_ramp_under_the_rim():
    """Live 21:29: from the entrance the ramp descends under an overhanging
    rim polygon; continuity kept the rim (93.5) for a player at ~78."""
    from wowbot.navigation.z_resolver import ZResolver

    class _RampUnderRim:
        def walkable_heights_at(self, _instance, point, _radius=2.5):
            return sorted({93.5, 92.5 - 1.2*abs(point["x"]-86.)})

    resolver = ZResolver(_RampUnderRim())
    resolver.seed_player(2175, 86., -2239., 92.5, 1.)
    on_ramp = resolver.observe_player(
        {"player_world_position": {"x": 74., "y": -2220.4, "instance_id": 2175}}, 6., route_z=78.)
    assert abs(on_ramp.z - 78.1) < .2 and on_ramp.confidence >= .85
    without_route = ZResolver(_RampUnderRim())
    without_route.seed_player(2175, 86., -2239., 92.5, 1.)
    assert without_route.observe_player(
        {"player_world_position": {"x": 74., "y": -2220.4, "instance_id": 2175}}, 6.).z == 93.5


def test_a_waypoint_passed_between_samples_is_not_walked_back_to():
    from wowbot.navigation.service import NavigationService
    nav = NavigationService()
    anchors = tuple({"x": x, "y": y, "z": z} for x, y, z in (
        (86.4, -2240.2, 93.2), (85.3, -2240., 92.4), (81.8, -2222.9, 83.1), (79.5, -2221., 81.4),
        (72.2, -2219.7, 78.3), (69., -2220.8, 76.4), (66.9, -2223.2, 75.3)))
    nav._active_route = SimpleNamespace(anchors=anchors)
    nav._route_waypoint_index = 2
    nav._z.seed_player(2175, 73.2, -2220.4, 78.6, 1.)
    assert nav._on_next_leg((73.19, -2220.38), 81.8, -2222.9)
    # a leg of the spiral one floor below at the same X/Y is not ours
    nav._z.seed_player(2175, 73.2, -2220.4, 60., 1.)
    assert not nav._on_next_leg((73.19, -2220.38), 81.8, -2222.9)


# -- the full 21:41 run --------------------------------------------------------

def test_an_up_arrow_means_another_storey_not_a_slope():
    """Live 21:44: ABOVE from the pit bottom (-4.9) chose -1.8 on the same
    floor; the MOVE "arrived" under the cocoon's ledge."""
    from wowbot.navigation.z_resolver import ResolvedPosition, ZResolver

    class _Column:
        def walkable_heights_at(self, _instance, point, _radius=2.5):
            return [-1.8, 45.6, 60.5] if point["x"] < 90 else [-4.9]

    resolver = ZResolver(_Column())
    player = ResolvedPosition(123.3, -2244.5, -4.9, .95, "MMAP", 2175)
    target = resolver.resolve_target(2175, 81.9, -2277.8, player=player, floor_hint="ABOVE")
    assert target is not None and target.z == 45.6


def test_a_passed_sweep_hop_is_recorded_in_the_sweep():
    """Live 21:44: the same rim hop was offered 30 times in 4 s."""
    from wowbot.navigation.service import NavigationService
    from wowbot.navigation.z_resolver import ResolvedPosition
    nav = NavigationService()
    nav._zone_sweeps = {"k": {"hops": [{"x": 85.4, "y": -2240.1, "z": 92.4}], "visited": set(),
                              "upward": False, "done": False}}
    nav._last_sweep_key = "k"
    nav._active_request = SimpleNamespace(destination={"sweep_direction": "DOWN", "z": 92.4,
                                                       "layer_z": 92.4, "sweep_hop": 0})
    nav._z.player = ResolvedPosition(82., -2279., -2.9, .95, "MMAP", 2175)
    assert nav._sweep_hop_passed().reason == "zone_sweep_hop_passed"
    assert nav._zone_sweeps["k"]["visited"] == {0}


def test_an_unknown_target_height_is_not_z_zero():
    """Live 21:54: Ralia's height was unknown; ``or 0.`` sent the route back
    down into the pit after the quest was done."""
    import inspect
    from wowbot.agent import quest_target_planning
    source = inspect.getsource(quest_target_planning)
    assert 'number(target_position.get("z")) or 0.' not in source
    assert '{"z_known": False, "floor_hint": "SAME"}' in source


def test_timestampless_fast_clock_advances_and_prefers_newer_full_anchor():
    """Issue #80: restored FAST timestamps froze at one second and an older
    FAST anchor beat a newer full snapshot."""
    assembler = PacketAssembler()
    assembler.feed(_packet(1, "STATE", {"monotonic_time": 100., "timestamp": 1000,
                                        "character_name": "Test", "map_id": 1409}), 100.)
    stamps = [assembler.feed(_packet(seq, "FAST", {"monotonic_time": mono, "map_id": 1409}),
                             mono)["timestamp"]
              for seq, mono in enumerate((100.2, 100.9, 101.6, 102.3, 102.9, 112.5), 2)]
    assert stamps == [1000, 1000, 1001, 1002, 1002, 1012]
    assembler.feed(_packet(20, "STATE", {"monotonic_time": 113., "timestamp": 1013,
                                         "character_name": "Test", "map_id": 1409}), 113.)
    after = assembler.feed(_packet(21, "FAST", {"monotonic_time": 113.2, "map_id": 1409}), 113.2)
    assert after["timestamp"] == 1013

    world = WorldModel()
    seen = []
    for seq, mono in enumerate((100., 100.5, 101.2, 102.1), 30):
        payload = {**state(mono, timestamp=None), "transport_kind": "FAST",
                   "frame_id": f"s:FAST:{seq}"}
        restored = assembler.feed(_packet(seq, "FAST", {"monotonic_time": mono + 13.,
                                                        "map_id": 1409}), mono + 13.)
        payload["timestamp"] = restored["timestamp"]
        seen.append(world.ingest(Observation.create(payload, mono)))
    assert all(seen)
