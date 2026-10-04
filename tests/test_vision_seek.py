from wowbot.agent.vision_seek import SeekVisualCueController, SeekVisualCuePhase
from wowbot.agent.models import Goal, Observation, Proposal
from wowbot.agent.planner import Planner
from wowbot.agent.skills import SkillRegistry
from wowbot.agent.world import WorldModel
import json
import math


def subject(*, track="far", x=.68, height=.035, stable=5, confidence=.82,
            static=.1, overhead=True):
    return {
        "source": "WORLD3D", "semantic_type": "UNKNOWN",
        "kind": "unknown_subject_candidate",
        "detector_kind": "unknown_subject_candidate",
        "track_id": track, "x": x, "y": .58,
        "bbox_height_fraction": height, "stable_frames": stable,
        "confidence": confidence, "inspectable": True, "lifecycle": "STABLE",
        "appearance": {"proposal_score": .78, "body_geometry": .7,
                       "static_scene_score": static},
        "visual_signature": {"signature_id": "appearance-far"},
        "visual_relations": ([{"type": "ABOVE", "belief": "SUPPORTED"}]
                             if overhead else []),
    }


def test_seek_scans_four_bounded_sectors_then_exhausts():
    seek = SeekVisualCueController()
    seek.begin({"purpose": "FIND_LOCAL_QUEST_RELEVANT_SUBJECT"}, {}, 1.)
    commands = []
    for index in range(4):
        now = 1. + index*seek.scan_step_interval
        assessment = seek.observe({"visual_candidates": []}, f"frame-{index}", now)
        assert not assessment.terminal
        command = seek.command({}, f"frame-{index}", now)
        assert command and command[0].kind == "BIND"
        assert command[0].binding == "TURNLEFT"
        assert command[0].duration == seek.scan_drag_duration
        commands.append(command[0].binding)
    assert commands == ["TURNLEFT"] * len(seek.sectors)
    done = seek.observe(
        {"visual_candidates": []}, "frame-final",
        1. + len(seek.sectors)*seek.scan_step_interval)
    assert done.terminal and not done.success
    assert done.reason == "seek_visual_cue_sectors_exhausted"


def test_seek_waits_for_observation_window_before_next_camera_step():
    seek = SeekVisualCueController()
    seek.begin({"purpose": "FIND_LOCAL_QUEST_RELEVANT_SUBJECT"}, {}, 1.)
    seek.observe({"visual_candidates": []}, "frame-a", 1.)
    assert seek.command({}, "frame-a", 1.)

    seek.observe({"visual_candidates": []}, "frame-b", 1.5)
    assert seek.command({}, "frame-b", 1.5) == ()

    next_at = 1. + seek.scan_step_interval
    seek.observe({"visual_candidates": []}, "frame-c", next_at)
    assert seek.command({}, "frame-c", next_at)


def test_seek_visually_approaches_distant_unknown_then_hands_it_to_inspect():
    seek = SeekVisualCueController()
    far = subject()
    seek.begin({**far, "purpose": "IMPROVE_UNKNOWN_OBSERVATION"},
               {"visual_candidates": [far]}, 1.)
    assessment = seek.observe({"visual_candidates": [far]}, "frame-a", 1.)
    assert assessment.phase == SeekVisualCuePhase.INVESTIGATING
    command = seek.command({}, "frame-a", 1.)[0]
    assert command.binding == "MOVEFORWARD" and command.simultaneous == ("TURNRIGHT",)

    close = subject(x=.51, height=.09)
    assessment = seek.observe({"visual_candidates": [close]}, "frame-b", 1.2)
    assert not assessment.terminal
    assert assessment.reason == "visual_cue_ready_for_hover_identification"
    hover = seek.command({"visual_candidates": [close]}, "frame-b", 1.2)
    assert hover and hover[0].kind == "HOVER"


def test_derived_symbol_probe_is_hovered_before_any_forward_movement():
    """Live repro: a torch flame must not turn an invented body box into a route."""
    seek = SeekVisualCueController()
    probe = subject(track="torch-probe", x=.52, height=.048, confidence=.66)
    probe.update({
        "kind": "unknown_subject_probe",
        "detector_kind": "unknown_subject_probe",
        "inspectable": False,
        "candidate_labels": ["subject_below_symbol_probe"],
        "appearance": {
            "derived_from": "overhead_symbol_like_cue",
            "anchor_candidate_labels": ["learned_symbol_like"],
        },
    })
    seek.begin({**probe, "purpose": "IDENTIFY"},
               {"visual_candidates": [probe]}, 1.)

    ready = seek.observe({"visual_candidates": [probe]}, "frame-a", 1.)

    assert ready.phase == SeekVisualCuePhase.CANDIDATE_READY
    assert ready.reason == "derived_subject_probe_ready_for_hover_identification"
    command = seek.command({"visual_candidates": [probe]}, "frame-a", 1.)
    assert len(command) == 1
    assert command[0].kind == "HOVER"
    assert (command[0].x, command[0].y) == (.52, .58)


def test_derived_symbol_probe_can_continue_only_from_fresh_mouseover_identity():
    seek = SeekVisualCueController()
    probe = subject(track="quest-glyph-probe", x=.79, height=.045, confidence=.66)
    probe.update({
        "kind": "unknown_subject_probe",
        "detector_kind": "unknown_subject_probe",
        "inspectable": False,
        "candidate_labels": ["subject_below_symbol_probe"],
        "appearance": {"derived_from": "overhead_symbol_like_cue"},
    })
    seek.begin({**probe, "purpose": "IDENTIFY"},
               {"visual_candidates": [probe]}, 1.)
    seek.observe({"visual_candidates": [probe]}, "frame-a", 1.)
    seek.command({"visual_candidates": [probe]}, "frame-a", 1.)

    identified = seek.observe({
        "visual_candidates": [probe],
        "character_guid": "Player-1",
        "mouseover": {"guid": "Creature-1", "name": "Lady Jaina Proudmoore"},
        "mouseover_sample_time": 1.1,
    }, "frame-b", 1.1)

    assert identified.terminal and identified.success
    assert identified.reason == "identity_available_during_visual_seek"


def test_ready_visual_cue_requires_hover_then_fresh_addon_identity_before_success():
    seek = SeekVisualCueController()
    close = subject(x=.51, height=.09)
    seek.begin({**close, "purpose": "IDENTIFY"}, {"visual_candidates": [close]}, 1.)
    ready = seek.observe({"visual_candidates": [close]}, "frame-a", 1.)
    assert not ready.terminal
    hover = seek.command({"visual_candidates": [close]}, "frame-a", 1.)
    assert hover[0].kind == "HOVER" and (hover[0].x, hover[0].y) == (.51, .58)
    identified = seek.observe({"visual_candidates": [close], "character_guid": "Player-1",
                               "mouseover": {"guid": "Creature-1", "name": "Lady Jaina Proudmoore"},
                               "mouseover_sample_time": 1.1, "cursor_sample_time": 1.1},
                              "frame-b", 1.1)
    assert identified.terminal and identified.success
    assert identified.reason == "identity_available_during_visual_seek"


def test_guidless_world_object_is_identified_only_by_expected_fresh_addon_id():
    seek = SeekVisualCueController()
    close = subject(x=.51, height=.09)
    seek.begin({**close, "purpose": "SEARCH_LOCAL_OBJECT", "object_id": 77},
               {"visual_candidates": [close]}, 1.)
    seek.observe({"visual_candidates": [close]}, "frame-a", 1.)
    assert seek.command({"visual_candidates": [close]}, "frame-a", 1.)[0].kind == "HOVER"

    wrong = seek.observe({"visual_candidates": [close],
                          "mouseover": {"object_id": 88, "tooltip": "Ancient Chest"},
                          "mouseover_sample_time": 1.1}, "frame-b", 1.1)
    assert not wrong.terminal
    identified = seek.observe({"visual_candidates": [close],
                               "mouseover": {"object_id": 77, "tooltip": "Ancient Chest"},
                               "mouseover_sample_time": 1.2}, "frame-c", 1.2)
    assert identified.terminal and identified.success
    assert identified.reason == "identity_available_during_visual_seek"


def test_entity_search_rejects_wrong_hover_and_requires_declared_hostility():
    seek = SeekVisualCueController()
    close = subject(x=.51, height=.09)
    seek.begin({**close, "purpose": "LOCALIZE_KILL_TARGET",
                "expected_name": "murlocs", "objective_type": "KILL",
                "objective_description": "0/3 Murlocs slain", "require_attackable": True},
               {"visual_candidates": [close]}, 1.)
    seek.observe({"visual_candidates": [close]}, "frame-a", 1.)
    seek.command({"visual_candidates": [close]}, "frame-a", 1.)

    friendly = seek.observe({"visual_candidates": [close],
        "mouseover": {"guid": "Creature-friendly", "name": "Murloc Watershaper",
                      "attackable": False}, "mouseover_sample_time": 1.1}, "frame-b", 1.1)
    assert not friendly.terminal
    hostile = seek.observe({"visual_candidates": [close],
        "mouseover": {"guid": "Creature-hostile", "name": "Murloc Watershaper",
                      "attackable": True}, "mouseover_sample_time": 1.2}, "frame-c", 1.2)
    assert hostile.terminal and hostile.success


def test_seek_never_labels_unknown_and_identity_requires_addon_mouseover():
    seek = SeekVisualCueController()
    far = subject()
    seek.begin({**far}, {"visual_candidates": [far]}, 1.)
    assert "semantic_type" not in seek.snapshot()
    assessment = seek.observe({"visual_candidates": [far], "character_guid": "Player-1",
                               "mouseover": {"guid": "Creature-1", "npc_id": 156626},
                               "mouseover_sample_time": 1.1,
                               "cursor_sample_time": 1.1},
                              "frame-b", 1.1)
    assert assessment.terminal and assessment.success
    assert assessment.reason == "identity_available_during_visual_seek"


def test_seek_visual_cue_has_no_guid_or_selected_target_precondition():
    world = WorldModel()
    world.ingest(Observation.create({"session_id": "seek:no-guid", "timestamp": 1.,
        "monotonic_time": 1., "frame_id": "one", "world_map_open": False,
        "is_in_combat": False, "is_casting": False, "target": None,
        "visual_candidates": [subject()]}, 1.))
    proposal = Proposal.make("SEEK_VISUAL_CUE", "unknown cue",
                             {**subject(), "purpose": "IDENTIFY"}, priority=78)
    assert SkillRegistry().available(proposal, world)


def test_nonviable_exact_track_never_leaks_nonfinite_score_to_status_json():
    seek = SeekVisualCueController()
    far = subject()
    seek.begin(far, {"visual_candidates": [far]}, 1.)
    hidden = {**far, "inspectable": False}
    seek.observe({"visual_candidates": [hidden]}, "frame-hidden", 1.1)
    snapshot = seek.snapshot()
    assert math.isfinite(snapshot["candidate_score"])
    json.dumps(snapshot, allow_nan=False)


def test_identify_servo_ignores_selected_target_dead_and_combat_range_facts():
    seek = SeekVisualCueController()
    far = subject()
    noisy_selected_target_state = {
        "visual_candidates": [far],
        "target": {"guid": "old-target", "dead": True},
        "actionbar": [{"is_harmful": True, "in_range": True}],
    }
    seek.begin({**far, "purpose": "IDENTIFY"}, noisy_selected_target_state, 1.)
    assessment = seek.observe(noisy_selected_target_state, "frame-a", 1.)
    assert not assessment.terminal
    assert assessment.phase == SeekVisualCuePhase.INVESTIGATING


def test_planner_prefers_seek_for_small_high_information_unknown_subject():
    world = WorldModel()
    world.ingest(Observation.create({"session_id": "seek:test", "timestamp": 1.,
        "monotonic_time": 1., "frame_id": "one", "map_id": 1409,
        "world_map_open": False, "position": {"x": .5, "y": .5},
        "orientation": 0., "player_present": True, "target": None,
        "active_quests": [], "visual_candidates": [subject()]}, 1.))
    proposal = Planner(SkillRegistry()).candidates(Goal.parse("Questelj", 1.), world, 1.)[0]
    assert proposal.skill == "SEEK_VISUAL_CUE"
    assert proposal.parameters["track_id"] == "far"
    assert proposal.parameters["semantic_type"] == "UNKNOWN"


def test_static_low_information_subject_is_not_approached():
    world = WorldModel()
    item = subject(static=1., overhead=False)
    item["appearance"]["proposal_score"] = .4
    world.ingest(Observation.create({"session_id": "seek:test", "timestamp": 1.,
        "monotonic_time": 1., "frame_id": "one", "map_id": 1409,
        "world_map_open": False, "position": {"x": .5, "y": .5},
        "orientation": 0., "player_present": True, "target": None,
        "active_quests": [], "visual_candidates": [item]}, 1.))
    proposals = Planner(SkillRegistry()).candidates(Goal.parse("Questelj", 1.), world, 1.)
    assert not any(p.skill == "SEEK_VISUAL_CUE" and p.parameters.get("track_id") == "far"
                   for p in proposals)


def test_seek_ignores_probable_self_avatar_but_not_overlapping_npc_evidence():
    own = subject(track="self", overhead=False)
    own["appearance"]["self_avatar_suppression_hint"] = True
    assert SeekVisualCueController._score(own) < 0

    nearby_npc = subject(track="nearby", overhead=True)
    nearby_npc["appearance"]["self_avatar_suppression_hint"] = True
    assert SeekVisualCueController._score(nearby_npc) > 0


def test_green_overhead_probe_without_body_evidence_is_not_quest_seek_target():
    world = WorldModel()
    item = subject(track="green-probe", overhead=True)
    item["kind"] = item["detector_kind"] = "unknown_subject_probe"
    item["appearance"] = {
        "anchor_appearance": {"hue_family": "green"},
        "anchor_candidate_labels": ["overhead_symbol_like_cue"],
        "proposal_score": 0., "body_geometry": 0.,
    }
    world.ingest(Observation.create({"session_id": "seek:green", "timestamp": 1.,
        "monotonic_time": 1., "frame_id": "one", "map_id": 1409,
        "world_map_open": False, "position": {"x": .5, "y": .5},
        "orientation": 0., "player_present": True, "target": None,
        "active_quests": [], "visual_candidates": [item]}, 1.))
    proposals = Planner(SkillRegistry()).candidates(Goal.parse("Questelj", 1.), world, 1.)
    assert not any(p.skill == "SEEK_VISUAL_CUE" and
                   p.parameters.get("track_id") == "green-probe" for p in proposals)


def test_supported_unknown_symbol_subject_group_is_visual_seek_target():
    world = WorldModel()
    item = subject(track="supported-probe", overhead=True, confidence=.66)
    item["kind"] = item["detector_kind"] = "unknown_subject_probe"
    item["semantic_type"] = "UNKNOWN"
    item["appearance"] = {
        "anchor_appearance": {"hue_family": "unknown"},
        "anchor_candidate_labels": ["learned_symbol_like"],
        "proposal_score": 0., "body_geometry": 0.,
    }
    item["visual_group"] = {
        "belief": "SUPPORTED", "appearance_labels": ["learned_symbol_like"]}
    world.ingest(Observation.create({"session_id": "seek:supported", "timestamp": 1.,
        "monotonic_time": 1., "frame_id": "one", "map_id": 1409,
        "world_map_open": False, "position": {"x": .5, "y": .5},
        "orientation": 0., "player_present": True, "target": None,
        "active_quests": [], "visual_candidates": [item]}, 1.))

    proposals = Planner(SkillRegistry()).candidates(Goal.parse("Questelj", 1.), world, 1.)

    seek = next(p for p in proposals if p.skill == "SEEK_VISUAL_CUE"
                and p.parameters.get("track_id") == "supported-probe")
    assert seek.parameters["semantic_type"] == "UNKNOWN"
    assert seek.parameters["purpose"] == "IDENTIFY"


def test_badge_group_is_preferred_over_higher_utility_generic_distant_subject():
    world = WorldModel()
    generic = subject(track="generic", x=.45)
    generic["appearance"]["proposal_score"] = .95
    badge = subject(track="badge", x=.65, confidence=.7)
    badge["candidate_labels"] = ["quest_badge_like"]
    badge["visual_group"] = {"belief": "SUPPORTED",
                             "appearance_labels": ["quest_badge_like"]}
    world.ingest(Observation.create({"session_id": "seek:badge", "timestamp": 1.,
        "monotonic_time": 1., "frame_id": "one", "map_id": 1409,
        "world_map_open": False, "position": {"x": .5, "y": .5},
        "orientation": 0., "player_present": True, "target": None,
        "active_quests": [], "visual_candidates": [generic, badge]}, 1.))
    proposal = Planner(SkillRegistry()).candidates(Goal.parse("Questelj", 1.), world, 1.)[0]
    assert proposal.skill == "SEEK_VISUAL_CUE"
    assert proposal.parameters["track_id"] == "badge"


def test_agent_starts_one_persistent_seek_instead_of_planner_camera_pulses():
    from test_agent_core import agent, state

    value, executor = agent()
    result = value.tick(state(1, world_map_open=False, visual_candidates=[]), 1.)
    assert result["pending"]["proposal"]["skill"] == "SEEK_VISUAL_CUE"
    assert executor.commands[-1].kind == "BIND"
    assert executor.commands[-1].binding == "TURNLEFT"
    assert value.vision_seek.snapshot()["scan_index"] == 1
    assert value.vision_seek.snapshot()["view_control_mode"] == "PLAYER_YAW_FOLLOW_CAMERA"
    assert value.vision_seek.snapshot()["player_turn_updates"] == 1


def test_agent_seek_uses_movement_lease_for_distant_unknown():
    from test_agent_core import agent, state

    value, executor = agent()
    far = subject()
    result = value.tick(state(1, world_map_open=False,
                              visual_candidates=[far]), 1.)
    assert result["pending"]["proposal"]["skill"] == "SEEK_VISUAL_CUE"
    command = executor.commands[-1]
    assert command.binding == "MOVEFORWARD"
    assert command.simultaneous == ("TURNRIGHT",)


def test_seek_keeps_persistent_ownership_when_first_visual_sample_is_stale():
    from test_agent_core import agent, state

    value, executor = agent()
    stale = {**subject(), "observed_at": .1}
    result = value.tick(state(1, world_map_open=False,
                              visual_candidates=[stale]), 1.)
    assert result["pending"]["proposal"]["skill"] == "SEEK_VISUAL_CUE"
    assert not executor.commands

    fresh = {**subject(), "observed_at": 1.1}
    result = value.tick(state(1.1, world_map_open=False,
                              visual_candidates=[fresh]), 1.1)
    assert result["pending"]["proposal"]["skill"] == "SEEK_VISUAL_CUE"
    assert executor.commands[-1].binding == "MOVEFORWARD"
