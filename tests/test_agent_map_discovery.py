from types import SimpleNamespace
import numpy as np

from wowbot.agent.models import Goal, Observation, Proposal, Outcome
from wowbot.agent.planner import Planner
from wowbot.agent.skills import SkillRegistry
from wowbot.agent.spatial_memory import SpatialMemory
from wowbot.agent.perception import PerceptionWorker
from wowbot.agent.world import WorldModel
from wowbot.agent.engine_runtime_projection import movement_visual_interrupt


def world(**extra):
    result = WorldModel()
    result.ingest(Observation.create({"session_id": "a", "timestamp": 1., "frame_id": "one",
        "map_id": 1409, "world_map_open": False, "position": {"x": .5, "y": .5},
        "orientation": 0., "player_present": True, **extra}, 1.))
    return result


def test_minimap_quest_probe_precedes_unrelated_friendly_interaction():
    planner = Planner(SkillRegistry())
    state = world(target={"guid": "old", "attackable": False}, visual_candidates=[
        {"kind": "quest_giver", "source": "MINIMAP_CV", "x": .9, "y": .8, "confidence": .94}])
    proposal = planner.candidates(Goal.parse("Questelj", 1.), state, 1.)[0]
    assert proposal.skill == "INSPECT" and proposal.parameters["source"] == "MINIMAP_CV"
    planner.recent[proposal.key] = 31
    assert planner.candidates(Goal.parse("Questelj", 1.), state, 2.)[0].skill == "OPEN_MAP"


def test_bounded_world3d_inspection_precedes_world_map_fallback():
    planner = Planner(SkillRegistry())
    goal = Goal.parse("Questelj", 1.)
    state = world(visual_candidates=[{
        "kind": "unknown_subject_candidate", "detector_kind": "unknown_subject_candidate",
        "source": "WORLD3D", "track_id": "subject-1", "x": .58, "y": .60,
        "confidence": .9, "stable_frames": 5, "lifecycle": "STABLE",
        "appearance": {"foreground_contrast": .7, "screen_center_relevance": .8},
    }])
    assert planner.candidates(goal, state, 1.)[0].skill == "INSPECT"
    planner.world3d_probe_count = 4
    assert planner.candidates(goal, state, 2.)[0].skill == "OPEN_MAP"


def test_completed_quest_world_turnin_bypasses_generic_inspection_and_map_search():
    planner = Planner(SkillRegistry())
    state = world(
        player_world_position={
            "x": 209.7, "y": -2268.7, "z_known": False,
            "instance_id": 2175, "coordinate_space": "WORLD_YARDS"},
        active_quests=[{"quest_id": 58914, "is_complete": True, "objectives": []}],
        quest_locations=[{
            "quest_id": 58914, "map_id": 1409, "x": .516, "y": .478,
            "coordinate_space": "NORMALIZED_MAP", "source": "QUEST_POI",
            "world_position": {
                "x": 355., "y": -2264., "z_known": False,
                "instance_id": 2175, "ui_map_id": 1409,
                "coordinate_space": "WORLD_YARDS", "source": "C_MAP_WORLD_POS"}}],
        visual_candidates=[{
            "kind": "unknown_subject_candidate", "source": "WORLD3D",
            "track_id": "bush", "x": .5, "y": .5, "confidence": .95,
            "stable_frames": 20, "lifecycle": "STABLE"}],
    )

    proposals = planner.candidates(Goal.parse("Questelj", 1.), state, 1.)

    assert proposals[0].skill == "MOVE"
    assert proposals[0].parameters["purpose"] == "LOCATE_TURN_IN_REGION"
    assert all(proposal.skill not in {"INSPECT", "SEEK_VISUAL_CUE", "OPEN_MAP"}
               for proposal in proposals)


def test_completed_quest_move_hands_one_stable_quest_cue_to_visual_seek():
    planner = Planner(SkillRegistry())
    marker = {
        "kind": "unknown_subject_candidate", "source": "WORLD3D",
        "track_id": "turnin-subject", "x": .62, "y": .48,
        "confidence": .72, "stable_frames": 5, "lifecycle": "STABLE",
        "bbox_height_fraction": .04, "inspectable": True,
        "candidate_labels": ["quest_badge_like", "quest_marker_like"],
        "appearance": {"quest_badge_likeness": .9},
    }
    state = world(
        player_world_position={
            "x": 209.7, "y": -2268.7, "z_known": False,
            "instance_id": 2175, "coordinate_space": "WORLD_YARDS"},
        active_quests=[{"quest_id": 58914, "is_complete": True, "objectives": []}],
        quest_locations=[{
            "quest_id": 58914, "map_id": 1409, "x": .516, "y": .478,
            "coordinate_space": "NORMALIZED_MAP", "source": "QUEST_POI",
            "world_position": {
                "x": 355., "y": -2264., "z_known": False,
                "instance_id": 2175, "ui_map_id": 1409,
                "coordinate_space": "WORLD_YARDS", "source": "C_MAP_WORLD_POS"}}],
        visual_candidates=[marker])
    route = next(proposal for proposal in planner.candidates(
        Goal.parse("Questelj", 1.), state, 1.) if proposal.skill == "MOVE")
    attempt = SimpleNamespace(proposal=route)
    handoff = movement_visual_interrupt(attempt, state.state)

    assert handoff and handoff["track_id"] == "turnin-subject"
    planner.arm_movement_visual_handoff(handoff, 1.)
    proposals = planner.candidates(Goal.parse("Questelj", 1.), state, 1.1)

    assert proposals[0].skill == "SEEK_VISUAL_CUE"
    assert proposals[0].parameters["track_id"] == "turnin-subject"
    assert proposals[0].parameters["movement_visual_handoff"]["route_purpose"] == "LOCATE_TURN_IN_REGION"
    assert not any(proposal.skill == "OPEN_MAP" for proposal in proposals)


def test_turnin_move_does_not_stop_for_an_unmarked_creature():
    attempt = SimpleNamespace(proposal=Proposal.make(
        "MOVE", "turn in", {"purpose": "LOCATE_TURN_IN_REGION"}))
    observed = {
        "monotonic_time": 4.,
        "visual_candidates": [{
            "source": "WORLD3D", "kind": "unknown_subject_candidate",
            "track_id": "road-mob", "confidence": .9, "stable_frames": 10,
            "lifecycle": "STABLE", "inspectable": True, "observed_at": 4.,
            "candidate_labels": ["learned_subject_like"],
            "appearance": {"learned_label_hypothesis": "creature_unit_like"},
        }],
    }
    assert movement_visual_interrupt(attempt, observed) is None


def test_objective_move_visual_handoff_requires_strong_stable_subject_near_destination():
    attempt = SimpleNamespace(proposal=Proposal.make(
        "MOVE", "search objective", {
            "purpose": "LOCATE_QUEST_OBJECTIVE_REGION",
            "objective_type": "KILL",
            "coordinate_space": "WORLD_YARDS", "instance_id": 2175,
            "x": 100., "y": 100.,
        }))
    common = {
        "source": "WORLD3D", "kind": "unknown_subject_candidate",
        "stable_frames": 6, "lifecycle": "STABLE", "inspectable": True,
        "observed_at": 4., "candidate_labels": ["learned_subject_like"],
        "appearance": {"learned_label_hypothesis": "creature_unit_like"},
    }

    assert movement_visual_interrupt(attempt, {
        "monotonic_time": 4.,
        "player_world_position": {"x": 90., "y": 100., "instance_id": 2175},
        "visual_candidates": [{**common, "track_id": "weak", "confidence": .15}],
    }) is None
    handoff = movement_visual_interrupt(attempt, {
        "monotonic_time": 4.,
        "player_world_position": {"x": 90., "y": 100., "instance_id": 2175},
        "visual_candidates": [{**common, "track_id": "strong", "confidence": .30}],
    })

    assert handoff is not None
    assert handoff["track_id"] == "strong"
    assert handoff["reason"] == "quest_route_visual_cue_observed"
    assert handoff["destination_distance_yards"] == 10.


def test_talk_objective_handoff_accepts_merged_unit_class_near_destination():
    """The unit model reports every NPC body as creature_unit_like."""
    attempt = SimpleNamespace(proposal=Proposal.make(
        "MOVE", "find quest npc", {
            "purpose": "LOCATE_QUEST_OBJECTIVE_REGION", "objective_type": "TALK",
            "coordinate_space": "WORLD_YARDS", "instance_id": 2175,
            "x": 100., "y": 100.,
        }))
    handoff = movement_visual_interrupt(attempt, {
        "monotonic_time": 4.,
        "player_world_position": {"x": 90., "y": 100., "instance_id": 2175},
        "visual_candidates": [{
            "source": "WORLD3D", "kind": "unknown_subject_candidate",
            "track_id": "npc-body", "confidence": .30, "stable_frames": 6,
            "lifecycle": "STABLE", "inspectable": True, "observed_at": 4.,
            "candidate_labels": ["learned_subject_like"],
            "appearance": {"learned_label_hypothesis": "creature_unit_like"},
        }],
    })

    assert handoff is not None and handoff["track_id"] == "npc-body"


def test_objective_move_does_not_stop_for_strong_subject_far_from_destination():
    attempt = SimpleNamespace(proposal=Proposal.make(
        "MOVE", "search objective", {
            "purpose": "LOCATE_QUEST_OBJECTIVE_REGION", "objective_type": "KILL",
            "coordinate_space": "WORLD_YARDS", "instance_id": 2175,
            "x": 100., "y": 100.,
        }))
    observed = {
        "monotonic_time": 4.,
        "player_world_position": {"x": 20., "y": 20., "instance_id": 2175},
        "visual_candidates": [{
            "source": "WORLD3D", "kind": "unknown_subject_candidate",
            "track_id": "roadside-mob", "confidence": .9, "stable_frames": 20,
            "lifecycle": "STABLE", "inspectable": True, "observed_at": 4.,
            "candidate_labels": ["learned_subject_like"],
            "appearance": {"learned_label_hypothesis": "creature_unit_like"},
        }],
    }

    assert movement_visual_interrupt(attempt, observed) is None


def test_generic_supported_overhead_without_quest_appearance_does_not_interrupt_move():
    attempt = SimpleNamespace(proposal=Proposal.make(
        "MOVE", "search objective", {
            "purpose": "LOCATE_QUEST_OBJECTIVE_REGION", "objective_type": "KILL",
            "coordinate_space": "WORLD_YARDS", "instance_id": 2175,
            "x": 100., "y": 100.,
        }))
    observed = {
        "monotonic_time": 4.,
        "player_world_position": {"x": 95., "y": 100., "instance_id": 2175},
        "visual_candidates": [{
            "source": "WORLD3D", "kind": "unknown_subject_probe",
            "track_id": "generic-symbol-probe", "confidence": .9,
            "stable_frames": 20, "lifecycle": "STABLE", "inspectable": True,
            "observed_at": 4., "candidate_labels": ["subject_below_symbol_probe"],
            "visual_relations": [{"type": "ABOVE", "belief": "SUPPORTED"}],
        }],
    }

    assert movement_visual_interrupt(attempt, observed) is None


def test_active_quest_area_stops_generic_inspect_sweep_after_one_probe():
    planner = Planner(SkillRegistry())
    goal = Goal.parse("Questelj", 1.)
    state = world(active_quests=[{"quest_id": 55122, "objectives": [{
        "description": "0/6 First Aid Kits recovered from defeated Murlocs",
        "current": 0, "required": 6,
    }]}], visual_candidates=[{
        "kind": "unknown_subject_candidate", "detector_kind": "unknown_subject_candidate",
        "source": "WORLD3D", "track_id": "foreground-1", "x": .58, "y": .60,
        "confidence": .9, "stable_frames": 5, "lifecycle": "STABLE",
        "appearance": {"foreground_contrast": .7, "screen_center_relevance": .8},
    }])
    # The first best candidate can be hovered.  The next plan must not spend
    # the entire objective-area window on unrelated generic inspections.
    # Prime the session/quest search context exactly as an executed first
    # probe would; candidates() resets per-context counters on first use.
    assert planner.candidates(goal, state, 1.)[0].skill == "INSPECT"
    planner.world3d_probe_count = 1
    proposal = planner.candidates(goal, state, 2.)[0]
    assert proposal.skill == "SEEK_VISUAL_CUE"
    assert proposal.parameters["purpose"] == "SEARCH_LOCAL_OBJECTIVE_AREA"


def test_disappeared_minimap_marker_at_objective_area_replans_to_local_search():
    """M1 scenario 16: disappearance is arrival evidence, not target failure."""
    planner = Planner(SkillRegistry())
    goal = Goal.parse("Questelj", 1.)
    quest = [{"quest_id": 42, "objectives": [{
        "objective_id": "42:0", "type": "COLLECT",
        "description": "Collect training supplies", "current": 0,
        "required": 3, "search_area": {
            "map_id": 1409, "x": .5, "y": .5,
            "coordinate_space": "NORMALIZED_MAP"}}]}]
    approaching = world(active_quests=quest, visual_candidates=[{
        "kind": "minimap_candidate", "source": "MINIMAP_CV",
        "track_id": "objective-cue", "x": .72, "y": .42,
        "confidence": .9, "stable_frames": 5}])
    assert any(proposal.parameters.get("source") == "MINIMAP_CV"
               for proposal in planner.candidates(goal, approaching, 1.))

    entered = world(active_quests=quest, visual_candidates=[])
    proposal = planner.candidates(goal, entered, 2.)[0]

    assert proposal.skill == "SEEK_VISUAL_CUE"
    assert proposal.parameters["purpose"] == "SEARCH_LOCAL_OBJECTIVE_AREA"
    assert proposal.parameters["quest_id"] == 42
    assert proposal.parameters["objective_id"] == "42:0"
    assert proposal.skill != "OPEN_MAP"


def test_bounded_world3d_seek_precedes_world_map_when_no_candidate_is_visible():
    planner = Planner(SkillRegistry())
    goal = Goal.parse("Questelj", 1.)
    state = world(visual_candidates=[])
    proposal = planner.candidates(goal, state, 1.)[0]
    assert proposal.skill == "SEEK_VISUAL_CUE"
    assert proposal.parameters["purpose"] == "FIND_LOCAL_QUEST_RELEVANT_SUBJECT"
    # The persistent skill owns all four sectors; only its terminal result
    # advances this planner fallback gate.
    planner.camera_search_step = 4
    assert planner.candidates(goal, state, 6.)[0].skill == "OPEN_MAP"


def test_map_inspects_before_closing_but_has_time_and_probe_limits():
    planner = Planner(SkillRegistry())
    goal = Goal.parse("Questelj", 1.)
    assert planner.candidates(goal, world(world_map_open=True), 1.)[0].skill == "WAIT"
    state = world(world_map_open=True, visual_candidates=[
        {"kind": "quest", "source": "WORLD_MAP_CV", "x": .4, "y": .6, "confidence": .60}])
    assert planner.candidates(goal, state, 1.3)[0].skill == "INSPECT"
    planner.map_probes = 4
    assert planner.candidates(goal, state, 1.4)[0].skill == "CLOSE_MAP"
    planner.map_probes = 0
    assert planner.candidates(goal, state, 11.)[0].skill == "CLOSE_MAP"


def test_map_input_requires_selected_binding_and_known_ui_state():
    registry = SkillRegistry(SimpleNamespace(contains=lambda key: False))
    assert not registry.available(Proposal.make("OPEN_MAP", "test"), world())
    registry = SkillRegistry()
    assert not registry.available(Proposal.make("OPEN_MAP", "test"), world(world_map_open=None))
    assert not registry.available(Proposal.make("OPEN_MAP", "test"), world(is_in_combat=True))
    assert registry.commands(Proposal.make("OPEN_MAP", "test"), world())[0].binding == "TOGGLEWORLDMAP"


def test_map_probe_cannot_click_minimap_unit_as_3d_target():
    planner = Planner(SkillRegistry())
    state = world(mouseover={"guid": "npc", "is_attackable": False},
                  map_mouseover={"surface": "MINIMAP"}, cursor_position={"nx": .9, "ny": .8})
    assert not any(p.skill == "TARGET" for p in planner.candidates(Goal.parse("Questelj", 1.), state, 1.))


def test_plain_title_and_cv_marker_do_not_prove_quest_role(tmp_path):
    memory = SpatialMemory(tmp_path)
    state = {"session_id": "a", "map_id": 1409, "cursor_position": {"nx": .4, "ny": .6},
             "map_mouseover": {"surface": "WORLD_MAP", "semantic_type": "UNKNOWN",
                "tooltip": "Emergency First Aid", "map_id": 1409, "x": .62, "y": .83}}
    probe = {"source": "WORLD_MAP_CV", "kind": "quest", "x": .4, "y": .6}
    points = memory.ingest(state, 1., probe=probe)
    assert points == []
    assert memory.marker_observations[0]["semantic_type"] == "UNKNOWN"
    assert memory.marker_observations[0]["semantic_hypothesis"] == "UNKNOWN"
    assert state["map_mouseover"]["semantic_type"] == "UNKNOWN"  # raw evidence preserved
    planner = Planner(SkillRegistry())
    proposal = planner.candidates(Goal.parse("Questelj", 1.), world(remembered_locations=points), 2.)[0]
    assert proposal.skill != "MOVE"


def test_world_map_edge_tooltip_is_not_persisted_as_a_location(tmp_path):
    memory = SpatialMemory(tmp_path)
    state = {"session_id": "a", "frame_id": "f", "map_id": 1726,
             "cursor_position": {"nx": .99, "ny": .15},
             "map_mouseover": {"surface": "WORLD_MAP",
                "semantic_type": "QUEST_RELATED", "tooltip": "Warming Up",
                "map_id": 1726, "x": 1.0, "y": .153}}
    probe = {"source": "WORLD_MAP_CV", "kind": "unknown_map_marker",
             "track_id": "edge", "x": .99, "y": .15}

    assert memory.ingest(state, 1., probe=probe) == []
    assert memory.points.points(1726) == []


def test_runtime_map_validation_is_a_read_only_policy_not_world_state_mutation():
    location = {
        "semantic_type": "QUEST_GIVER", "source": "ADDON_MAP_MOUSEOVER",
        "map_id": 1409, "x": .62, "y": .83,
        "provenance": {"observed_monotonic": 5., "session_id": "a",
                       "marker_associated": True},
    }
    value = world(remembered_locations=[location])
    planner = Planner(SkillRegistry())
    planner.map_search_context = (
        value.session_id, value.state.get("map_id"),
        value.state.get("quest_state_revision"))
    planner.last_map_scan_started = 4.

    proposals = planner.candidates(Goal.parse("Questelj", 5.), value, 5.)

    assert any(proposal.skill == "MOVE" and proposal.parameters.get("x") == .62
               for proposal in proposals)
    assert "runtime_map_validated" not in value.state["remembered_locations"][0]


def test_minimap_name_is_kept_but_not_invented_as_world_position(tmp_path):
    memory = SpatialMemory(tmp_path)
    state = {"session_id": "a", "map_id": 1409, "cursor_position": {"nx": .9, "ny": .8},
             "map_mouseover": {"surface": "MINIMAP", "semantic_type": "UNKNOWN", "tooltip": "Captain Garrick",
                               "map_id": 1409, "local_x": .5, "local_y": .7}}
    probe = {"source": "MINIMAP_CV", "kind": "quest_giver", "x": .9, "y": .8}
    assert memory.ingest(state, 1., probe=probe) == []
    assert memory.marker_observations[0]["tooltip"] == "Captain Garrick"
    assert memory.marker_observations[0]["semantic_type"] == "UNKNOWN"
    assert memory.marker_observations[0]["semantic_hypothesis"] == "UNKNOWN"
    assert "x" not in memory.marker_observations[0]


def test_unknown_minimap_appearance_learns_only_from_associated_addon_unit(tmp_path):
    memory = SpatialMemory(tmp_path)
    signature = {"version": 2, "representation_space": "MINIMAP", "signature_id": "icon-a"}
    state = {"session_id": "a", "map_id": 1409, "cursor_position": {"nx": .7, "ny": .8},
             "frame_id": "f1", "map_mouseover": {"surface": "MINIMAP", "semantic_type": "UNKNOWN",
                "tooltip": "Tracked Murloc", "map_id": 1409,
                "unit": {"npc_id": 77, "guid": "Creature-77", "unit_type": "NPC"}}}
    probe = {"source": "MINIMAP_CV", "kind": "minimap_candidate", "x": .7, "y": .8,
             "visual_signature": signature}
    for index, at in enumerate((1., 4., 7.), start=1):
        state["frame_id"] = f"f{index}"
        memory.ingest(state, at, probe=probe)
    matches = memory.entities.recognize_visual(signature)
    assert matches[0]["identity_key"] == "npc:77"
    assert memory.marker_observations[0]["semantic_type"] == "UNKNOWN"

    # Same tooltip with a cursor away from the track must not train identity.
    other = dict(state)
    other["cursor_position"] = {"nx": .1, "ny": .1}
    memory.ingest(other, 10., probe={**probe, "visual_signature": {**signature, "signature_id": "other"}})
    assert memory.entities.recognize_visual({**signature, "signature_id": "other"}) == []


def test_exact_world3d_mouseover_can_learn_from_fast_lane_without_map_work(tmp_path):
    memory = SpatialMemory(tmp_path)
    signature = {"version": 2, "representation_space": "WORLD3D", "signature_id": "murloc-crop"}
    state = {"session_id": "a", "map_id": 1409, "frame_id": "f1",
             "cursor_position": {"nx": .47, "ny": .63},
             "mouseover": {"guid": "Creature-77", "npc_id": 77, "unit_type": "NPC"}}
    probe = {"source": "WORLD3D", "kind": "unknown_subject_candidate", "x": .47, "y": .63,
             "visual_signature": signature}
    for index, at in enumerate((1., 4., 7.), start=1):
        state["frame_id"] = f"f{index}"
        memory.ingest(state, at, probe=probe, learn_only=True)
    matches = memory.entities.recognize_visual(signature)
    assert matches and matches[0]["identity_key"] == "npc:77"
    assert memory.marker_observations == []


def test_unassociated_plain_tooltip_does_not_become_quest_location(tmp_path):
    memory = SpatialMemory(tmp_path)
    state = {"session_id": "a", "map_id": 1409, "cursor_position": {"nx": .1, "ny": .1},
             "map_mouseover": {"surface": "WORLD_MAP", "semantic_type": "UNKNOWN", "tooltip": "Some Tree",
                               "map_id": 1409, "x": .62, "y": .83}}
    assert memory.ingest(state, 1., probe={"source": "WORLD_MAP_CV", "kind": "quest", "x": .4, "y": .6}) == []


def test_existing_world_map_detector_emits_unknown_appearance_without_world_coordinates():
    image = np.zeros((240, 320, 4), dtype=np.uint8)
    image[100:108, 150:154, :3] = (0, 150, 235)
    result = PerceptionWorker._world((image.tobytes(), 320, 240), 1., {"world_map_open": True})
    assert result and result[0].marker_type == "unknown_world_map_marker"
    assert "gold_glyph_like" in result[0].candidate_labels


def test_open_map_requires_new_telemetry_confirmation():
    attempt = SimpleNamespace(observation_id="old", deadline=3., started_at=0.,
                              proposal=Proposal.make("OPEN_MAP", "test"), baseline={})
    assert SkillRegistry().verify(attempt, world(), 1.)[0] == Outcome.PENDING
    assert SkillRegistry().verify(attempt, world(world_map_open=True), 1.)[0] == Outcome.SUCCESS


def test_close_map_accepts_nested_fast_state_and_cannot_retoggle_closed_map():
    registry = SkillRegistry()
    proposal = Proposal.make("CLOSE_MAP", "test")
    attempt = SimpleNamespace(observation_id="old", deadline=6., started_at=0.,
                              proposal=proposal, baseline={"world_map_open": True})
    closed = world(world_map_open=True,
                   map_context={"world_map_open": False})

    assert registry.verify(attempt, closed, 1.)[0] == Outcome.SUCCESS
    assert not registry.available(proposal, closed)
    assert registry.commands(proposal, closed) == ()


def test_open_map_accepts_nested_fast_state_and_cannot_retoggle_open_map():
    registry = SkillRegistry()
    proposal = Proposal.make("OPEN_MAP", "test")
    attempt = SimpleNamespace(observation_id="old", deadline=6., started_at=0.,
                              proposal=proposal, baseline={"world_map_open": False})
    opened = world(world_map_open=False,
                   map_context={"world_map_open": True})

    assert registry.verify(attempt, opened, 1.)[0] == Outcome.SUCCESS
    assert not registry.available(proposal, opened)
    assert registry.commands(proposal, opened) == ()


def test_runtime_map_discovery_round_trip_uses_hover_then_verified_map_coordinates(tmp_path):
    from wowbot.agent.runtime import AgentRuntime
    from wowbot.agent.executor import RecordingExecutor
    from wowbot.agent.models import Mode
    from test_agent_core import binding_file, state
    from test_agent_runtime import Sensor
    sensor, executor = Sensor(), RecordingExecutor()
    runtime = AgentRuntime(42, binding_file(tmp_path, 'bind "M" "TOGGLEWORLDMAP"\n'),
                           tmp_path / "output", sensor=sensor, executor=executor, vision=False)
    try:
        runtime.agent.set_goal("Questelj", 1.)
        runtime.agent.set_mode(Mode.FULL_AI)
        # This test exercises the World Map round trip itself; local 3D SEEK
        # has already exhausted its four bounded sectors.
        runtime.agent.planner.camera_search_step = 4
        runtime.agent.planner.map_search_context = ("test:player-1", 1609, None)
        sensor.payload = state(1., world_map_open=False)
        assert runtime.step(1.)["decision"]["skill"] == "OPEN_MAP"
        marker = {"kind": "quest", "source": "WORLD_MAP_CV", "x": .4, "y": .6, "confidence": .65}
        sensor.payload = state(1.2, world_map_open=True, visual_candidates=[marker])
        assert runtime.step(1.2)["decision"]["skill"] == "INSPECT"
        mouse = {"surface": "WORLD_MAP", "semantic_type": "QUEST_RELATED", "tooltip": "Emergency First Aid",
                 "map_id": 1609, "x": .62, "y": .83}
        sensor.payload = state(1.4, world_map_open=True, visual_candidates=[marker],
                               map_mouseover=mouse, cursor_position={"nx": .4, "ny": .6})
        runtime.step(1.4)
        sensor.payload = state(3.3, world_map_open=True, visual_candidates=[marker])
        assert runtime.step(3.3)["decision"]["skill"] == "CLOSE_MAP"
        sensor.payload = state(3.5, world_map_open=False)
        result = runtime.step(3.5)
        assert result["decision"]["skill"] == "MOVE"
        assert result["world"]["player"]["remembered_locations"][0]["x"] == .62
        assert [c.kind for c in executor.commands[:3]] == ["BIND", "HOVER", "BIND"]
        assert executor.commands[0].binding == executor.commands[2].binding == "TOGGLEWORLDMAP"
    finally:
        runtime.close()


def test_local_objective_seek_that_ended_at_once_lets_inspect_through():
    # Live 2026-10-04 10:36: the SEARCH_LOCAL_OBJECTIVE_AREA SEEK's postcondition
    # already held, it ended in 0.1 s with no input, and re-proposing it every
    # tick hid the INSPECT hovers (SEEK/WAIT loop for minutes).
    planner = Planner(SkillRegistry())
    goal = Goal.parse("Questelj", 1.)
    state = world(active_quests=[{"quest_id": 55122, "objectives": [{
        "description": "0/6 First Aid Kits recovered from defeated Murlocs",
        "current": 0, "required": 6,
    }]}], visual_candidates=[{
        "kind": "unknown_subject_candidate", "detector_kind": "unknown_subject_candidate",
        "source": "WORLD3D", "track_id": "foreground-1", "x": .58, "y": .60,
        "confidence": .9, "stable_frames": 5, "lifecycle": "STABLE",
        "appearance": {"foreground_contrast": .7, "screen_center_relevance": .8},
    }])
    planner.candidates(goal, state, 1.)
    planner.world3d_probe_count = 1
    assert planner.candidates(goal, state, 2.)[0].parameters.get("purpose") == "SEARCH_LOCAL_OBJECTIVE_AREA"
    again = planner.candidates(goal, state, 2.5)[0]
    assert again.parameters.get("purpose") != "SEARCH_LOCAL_OBJECTIVE_AREA"
    assert again.skill == "INSPECT"
    later = planner.candidates(goal, state, 2. + 12.5)[0]
    assert later.parameters.get("purpose") == "SEARCH_LOCAL_OBJECTIVE_AREA"
