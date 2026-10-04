from wowbot.agent.active_perception import ActivePerception
from wowbot.agent.memory import AgentMemory
from wowbot.agent.models import Goal, Observation
from wowbot.agent.planner import Planner
from wowbot.agent.skills import SkillRegistry
from wowbot.agent.world import WorldModel
from wowbot.agent.world_state_projection import WorldStateProjector


def world(**extra):
    value = WorldModel()
    value.ingest(Observation.create({"session_id": "s", "frame_id": "f", "timestamp": 1,
        "map_id": 1409, "position": {"x": .5, "y": .5}, "orientation": 0,
        "player_present": True, **extra}, 1))
    return value


def test_unknown_novel_stable_track_has_explicit_information_gain_and_cost():
    marker = {"source": "WORLD3D", "detector_kind": "object_candidate", "semantic_type": "UNKNOWN",
              "track_id": "t1", "stable_frames": 3, "x": .4, "y": .5}
    result = ActivePerception().evaluate(marker, world(), Goal.parse("Explore", 1))
    assert result["expected_information_gain"] > 0
    assert result["cost"] > 0 and result["utility"] > 0
    assert result["recommended_observation"] == "MOUSEOVER"


def test_self_avatar_hint_suppresses_attention_not_detection_and_overhead_overrides_it():
    marker = {"source": "WORLD3D", "detector_kind": "unknown_subject_candidate",
              "semantic_type": "UNKNOWN", "track_id": "self", "stable_frames": 5,
              "x": .5, "y": .65,
              "appearance": {"self_avatar_suppression_hint": True,
                             "self_avatar_region_overlap": .95}}
    suppressed = ActivePerception().evaluate(marker, world(), Goal.parse("Questelj", 1))
    assert suppressed["world3d_features"]["self_avatar_suppressed"] is True

    npc = {**marker, "track_id": "nearby-npc",
           "visual_relations": [{"type": "ABOVE", "belief": "SUPPORTED"}]}
    retained = ActivePerception().evaluate(npc, world(), Goal.parse("Questelj", 1))
    assert retained["world3d_features"]["self_avatar_suppressed"] is False
    assert retained["expected_information_gain"] > suppressed["expected_information_gain"]


def test_projected_self_player_is_named_and_never_inspected_without_masking_nearby_npc():
    own = {"source": "WORLD3D", "track_id": "own", "inspectable": True,
           "appearance": {"self_avatar_suppression_hint": True}}
    nearby = {"source": "WORLD3D", "track_id": "nearby", "inspectable": True,
              "appearance": {"self_avatar_region_overlap": .92,
                             "self_avatar_suppression_hint": False}}
    state = {"character_name": "Vbmnm", "character_guid": "Player-1",
             "visual_candidates": [own, nearby]}

    WorldStateProjector._project_self_player_tracks(state)

    assert own["display_name"] == "Vbmnm"
    assert own["visual_identity"]["kind"] == "SELF_PLAYER"
    assert own["visual_identity"]["fact"] is False
    assert own["inspectable"] is False
    assert own["appearance"]["self_player_guid"] == "Player-1"
    assert nearby["inspectable"] is True
    assert "visual_identity" not in nearby

    evaluation = ActivePerception().evaluate(own, world(), Goal.parse("Questelj", 1))
    assert evaluation["expected_information_gain"] == 0
    assert evaluation["world3d_features"]["self_player_name"] == "Vbmnm"


def test_symbol_inside_own_body_top_does_not_exempt_a_duplicate_self_track():
    """Live 2026-09-30: head/hair read as a symbol kept WORLD3D:41 inspectable."""
    def track(track_id, relation_to=None, bbox=None):
        item = {"source": "WORLD3D", "track_id": track_id, "inspectable": True,
                "bbox": bbox or {"left": 418, "top": 231, "right": 474, "bottom": 353},
                "appearance": {"self_avatar_suppression_hint": True}}
        if relation_to:
            item["visual_relations"] = [{"type": "ABOVE", "belief": "SUPPORTED",
                                         "subject_track_id": track_id, "symbol_track_id": relation_to}]
            item["visual_group"] = {"belief": "SUPPORTED", "member_track_ids": [relation_to, track_id]}
        return item

    inside_symbol = {"source": "WORLD3D", "track_id": "sym-in", "inspectable": False,
                     "bbox": {"left": 436, "top": 236, "right": 458, "bottom": 268}}
    duplicate_self = track("WORLD3D:41", relation_to="sym-in")
    above_symbol = {"source": "WORLD3D", "track_id": "sym-up", "inspectable": False,
                    "bbox": {"left": 436, "top": 190, "right": 458, "bottom": 228}}
    npc_behind = track("npc-behind", relation_to="sym-up")
    state = {"character_name": "Vbmnm", "character_guid": "Player-1",
             "visual_candidates": [inside_symbol, duplicate_self, above_symbol, npc_behind]}

    WorldStateProjector._project_self_player_tracks(state)

    assert duplicate_self["visual_identity"]["kind"] == "SELF_PLAYER"
    assert duplicate_self["inspectable"] is False
    assert npc_behind["inspectable"] is True and "visual_identity" not in npc_behind


def test_planner_does_not_inspect_self_avatar_hint_but_keeps_overlapping_npc_eligible():
    base = {"source": "WORLD3D", "kind": "unknown_subject_candidate",
            "detector_kind": "unknown_subject_candidate", "semantic_type": "UNKNOWN",
            "track_id": "self", "stable_frames": 5, "confidence": .9,
            "bbox_height_fraction": .12, "x": .5, "y": .65,
            "inspectable": True, "lifecycle": "STABLE",
            "appearance": {"self_avatar_suppression_hint": True,
                           "self_avatar_region_overlap": .95}}
    proposals = Planner(SkillRegistry()).candidates(
        Goal.parse("Questelj", 1), world(visual_candidates=[base]), 1)
    assert not any(proposal.parameters.get("track_id") == "self" for proposal in proposals)

    npc = {**base, "track_id": "overlapping-npc",
           "visual_relations": [{"type": "ABOVE", "belief": "SUPPORTED"}]}
    proposals = Planner(SkillRegistry()).candidates(
        Goal.parse("Questelj", 1), world(visual_candidates=[npc]), 1)
    assert any(proposal.parameters.get("track_id") == "overlapping-npc"
               for proposal in proposals)


def test_degraded_sensor_increases_observation_cost(tmp_path):
    memory = AgentMemory(tmp_path / "m.sqlite3")
    value = world(game_build="12.1.0")
    context = memory.learning_context(value.state, "SENSOR")
    for i in range(8):
        memory.record_sensor_outcome("MINIMAP_CV", "quest_giver", context, correct=False,
                                     at=i, latency=.1, error="false_positive", provenance={})
    marker = {"source": "MINIMAP_CV", "kind": "quest_giver", "semantic_type": "UNKNOWN",
              "track_id": "t1", "stable_frames": 3, "x": .8, "y": .8}
    degraded = ActivePerception(memory).evaluate(marker, value, Goal.parse("Questelj", 1))
    baseline = ActivePerception().evaluate(marker, value, Goal.parse("Questelj", 1))
    assert degraded["sensor_health"] == "DEGRADED"
    assert degraded["cost"] > baseline["cost"] and degraded["utility"] < baseline["utility"]


def test_planner_exposes_active_perception_decision():
    marker = {"source": "MINIMAP_CV", "kind": "quest_giver", "semantic_type": "UNKNOWN",
              "track_id": "t1", "stable_frames": 3, "confidence": .9, "x": .8, "y": .8}
    proposal = Planner(SkillRegistry()).candidates(Goal.parse("Questelj", 1),
        world(world_map_open=False, visual_candidates=[marker]), 1)[0]
    assert proposal.skill == "INSPECT"
    assert proposal.parameters["active_perception"]["expected_information_gain"] > 0


def test_stable_world3d_subject_below_symbol_is_inspected_before_opening_map():
    marker = {"source": "WORLD3D", "kind": "unknown_subject_candidate",
              "detector_kind": "unknown_subject_candidate", "semantic_type": "UNKNOWN",
              "track_id": "WORLD3D:quest-start-probe", "stable_frames": 5,
              "confidence": .74, "x": .5, "y": .68, "inspectable": True,
              "information_value": "HIGH",
              "visual_relations": [{"type": "ABOVE", "belief": "SUPPORTED",
                                    "symbol_track_id": "WORLD3D:symbol"}],
              "appearance": {"body_geometry": .9, "foreground_contrast": .7,
                             "screen_center_relevance": 1., "static_scene_score": .7}}
    proposal = Planner(SkillRegistry()).candidates(
        Goal.parse("Questelj", 1),
        world(world_map_open=False, active_quests=[], visual_candidates=[marker]), 1)[0]
    assert proposal.skill == "INSPECT"
    assert proposal.parameters["track_id"] == marker["track_id"]
    assert proposal.parameters["semantic_type"] == "UNKNOWN"


def test_supported_center_subject_probe_outranks_candidate_overhead_false_cue():
    false_cue = {"source": "WORLD3D", "kind": "unknown_subject_candidate",
        "detector_kind": "unknown_subject_candidate", "semantic_type": "UNKNOWN",
        "track_id": "WORLD3D:false-right", "stable_frames": 6, "confidence": .78,
        "x": .734, "y": .601, "inspectable": True, "information_value": "CANDIDATE",
        "visual_relations": [{"type": "ABOVE", "belief": "CANDIDATE",
                              "symbol_track_id": "WORLD3D:green-fragment"}],
        "appearance": {"screen_center_relevance": .45}}
    center_probe = {"source": "WORLD3D", "kind": "unknown_subject_probe",
        "detector_kind": "unknown_subject_probe", "semantic_type": "UNKNOWN",
        "track_id": "WORLD3D:center-probe", "stable_frames": 3, "confidence": .68,
        "x": .519, "y": .55, "inspectable": True, "information_value": "HIGH",
        "visual_relations": [{"type": "ABOVE", "belief": "SUPPORTED",
                              "symbol_track_id": "WORLD3D:bright-center-symbol"}],
        "appearance": {"screen_center_relevance": .96,
                       "derived_from": "overhead_symbol_like_cue"}}
    proposal = Planner(SkillRegistry()).candidates(
        Goal.parse("Questelj", 1),
        world(world_map_open=False, active_quests=[],
              visual_candidates=[false_cue, center_probe]), 1)[0]
    assert proposal.skill == "INSPECT"
    assert proposal.parameters["track_id"] == "WORLD3D:center-probe"


def test_stable_world3d_candidate_suppresses_camera_fallback_even_after_map_exhaustion():
    marker = {"source": "WORLD3D", "kind": "unknown_subject_candidate",
              "detector_kind": "unknown_subject_candidate", "semantic_type": "UNKNOWN",
              "track_id": "WORLD3D:visible-subject", "stable_frames": 5,
              "track_state": "ACTIVE", "confidence": .78, "x": .52, "y": .66,
              "inspectable": True, "appearance": {"body_geometry": .8,
                                                     "screen_center_relevance": .9}}
    planner = Planner(SkillRegistry())
    observed_world = world(world_map_open=False, active_quests=[], visual_candidates=[marker])
    planner.map_search_context = (observed_world.session_id,
                                  observed_world.state.get("map_id"),
                                  observed_world.state.get("quest_state_revision"))
    planner.map_search_exhausted = True
    proposal = planner.candidates(Goal.parse("Questelj", 1), observed_world, 1)[0]
    assert proposal.skill == "INSPECT"
    assert proposal.parameters["track_id"] == "WORLD3D:visible-subject"
