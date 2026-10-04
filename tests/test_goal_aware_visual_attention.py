from wowbot.agent.active_perception import ActivePerception
from wowbot.agent.models import Goal, Observation
from wowbot.agent.planner import Planner
from wowbot.agent.skills import SkillRegistry
from wowbot.agent.visual_tracks import VisualTrackManager
from wowbot.agent.world import WorldModel
from wowbot.vision.world3d.candidates import detect_world_candidates
from wowbot.vision.world3d.models import PixelRect, WorldSceneROI


def _world(markers, **extra):
    world = WorldModel()
    world.ingest(Observation.create({
        "session_id": "attention", "map_id": 1409, "player_present": True,
        "active_quests": [], "visual_candidates": markers, **extra,
    }, 1.0))
    return world


def test_dark_gold_badge_is_appearance_evidence_not_quest_fact():
    width, height = 180, 120
    frame = bytearray([45, 48, 50, 255] * width * height)

    def pixel(x, y, bgr):
        offset = (y * width + x) * 4
        frame[offset:offset + 3] = bytes(bgr)

    # Gold near-square badge outline plus separated exclamation glyph.
    for x in range(78, 101):
        for y in range(28, 49):
            border = x in {78, 79, 99, 100} or y in {28, 29, 47, 48}
            if border:
                pixel(x, y, (25, 205, 235))
    for y in range(33, 41):
        pixel(89, y, (20, 190, 240))
        pixel(90, y, (20, 190, 240))
    for y in range(43, 45):
        pixel(89, y, (20, 190, 240))
        pixel(90, y, (20, 190, 240))
    # A thin yellow scenery highlight must remain generic.
    for x in range(20, 24):
        for y in range(35, 43):
            pixel(x, y, (25, 190, 230))

    candidates = detect_world_candidates(bytes(frame), width, height,
                                         WorldSceneROI(PixelRect(0, 0, width, height)))
    badges = [item for item in candidates if "quest_badge_like" in item.candidate_labels]
    assert badges and badges[0].kind == "unknown_symbol_candidate"
    assert badges[0].class_name is None and badges[0].relation is None
    assert "QUEST_GIVER" not in badges[0].evidence
    assert not any("quest_badge_like" in item.candidate_labels and item.rect.left < 40
                   for item in candidates)


def test_symbol_subject_pair_forms_one_unknown_visual_group():
    manager = VisualTrackManager()
    symbol = {"kind": "unknown_symbol_candidate", "source": "WORLD3D",
              "x": .5, "y": .7, "confidence": .86,
              "bbox": {"left": 90, "top": 30, "right": 112, "bottom": 51},
              "candidate_labels": ["quest_badge_like"],
              "appearance": {"quest_badge_likeness": .8}}
    subject = {"kind": "unknown_subject_candidate", "source": "WORLD3D",
               "x": .5, "y": .62, "confidence": .74,
               "bbox": {"left": 82, "top": 55, "right": 120, "bottom": 115}}
    for at in range(3):
        items = manager.update("WORLD3D", [symbol, subject], float(at))
    pair = [item for item in items if item.get("visual_group_id")]
    assert len(pair) == 2
    assert len({item["visual_group_id"] for item in pair}) == 1
    assert all(item["visual_group"]["semantic_type"] == "UNKNOWN" for item in pair)
    assert all(item["visual_group"]["belief"] == "SUPPORTED" for item in pair)
    assert all("quest_badge_like" in item["visual_group"]["appearance_labels"] for item in pair)


def test_quest_attention_keeps_one_action_per_group_and_top_three_groups():
    markers = []
    for index in range(5):
        markers.append({
            "source": "WORLD3D", "kind": "unknown_subject_candidate",
            "detector_kind": "unknown_subject_candidate", "semantic_type": "UNKNOWN",
            "track_id": f"subject-{index}", "visual_group_id": f"group-{index}",
            "stable_frames": 4, "confidence": .72 + index * .01,
            "x": .35 + index * .05, "y": .62, "inspectable": True,
            "appearance": {"body_geometry": .5, "screen_center_relevance": .7},
        })
    # Same group as marker 4: it must not consume another attention slot.
    markers.append({**markers[4], "track_id": "subject-4-duplicate", "confidence": .99})
    proposals = Planner(SkillRegistry()).inspections(
        _world(markers), 1.0, goal=Goal.parse("Questelj", 1))
    world3d = [p for p in proposals if p.parameters.get("source") == "WORLD3D"]
    assert len(world3d) == 3
    assert len({p.parameters["visual_group_id"] for p in world3d}) == 3


def test_badge_group_increases_goal_directed_information_gain():
    plain = {"source": "WORLD3D", "kind": "unknown_subject_candidate",
             "detector_kind": "unknown_subject_candidate", "semantic_type": "UNKNOWN",
             "track_id": "plain", "stable_frames": 3, "x": .5, "y": .6}
    badge = {**plain, "track_id": "badge", "appearance": {"quest_badge_likeness": .9},
             "candidate_labels": ["quest_badge_like"],
             "visual_group": {"belief": "SUPPORTED", "appearance_labels": ["quest_badge_like"]}}
    world = _world([plain, badge])
    goal = Goal.parse("Questelj", 1)
    assert (ActivePerception().evaluate(badge, world, goal)["expected_information_gain"] >
            ActivePerception().evaluate(plain, world, goal)["expected_information_gain"])


def test_stable_visual_memory_and_interaction_scale_improve_inspection_rank_only():
    plain = {"source": "WORLD3D", "kind": "unknown_subject_candidate",
             "detector_kind": "unknown_subject_candidate", "semantic_type": "UNKNOWN",
             "track_id": "plain", "stable_frames": 4, "x": .5, "y": .6,
             "bbox_height_fraction": .10}
    remembered = {**plain, "track_id": "remembered", "bbox_height_fraction": .20}
    world = _world([plain, remembered],
        visual_recognition_candidates=[{
            "track_id": "remembered", "surface": "WORLD3D",
            "entity_candidates": [{
                "identity_key": "npc:150228", "status": "CANDIDATE",
                "similarity": .95, "temporal_support_frames": 4,
                "match_method": "MULTI_EXAMPLE_VISUAL_REIDENTIFICATION",
            }],
        }])
    goal = Goal.parse("Questelj", 1)
    active = ActivePerception()
    ranked = active.evaluate(remembered, world, goal)
    baseline = active.evaluate(plain, world, goal)
    assert ranked["utility"] > baseline["utility"]
    assert ranked["world3d_features"]["memory_recognition_strength"] == .95
    assert ranked["world3d_features"]["interaction_readiness"] > 0
    assert remembered["semantic_type"] == "UNKNOWN"


def test_manual_safe_ranking_prefers_supported_close_unknown_without_creating_a_fact():
    plain = {"source": "WORLD3D", "kind": "unknown_subject_candidate",
             "detector_kind": "unknown_subject_candidate", "semantic_type": "UNKNOWN",
             "track_id": "plain", "stable_frames": 4, "x": .5, "y": .6,
             "bbox_height_fraction": .10}
    remembered = {**plain, "track_id": "remembered", "bbox_height_fraction": .21}
    value = _world([plain, remembered])
    recognition = {"remembered": [{"track_id": "remembered", "entity_candidates": [{
        "identity_key": "npc:150228", "status": "CANDIDATE", "similarity": .95,
        "temporal_support_frames": 3,
    }]}]}
    ranked = ActivePerception().rank_world3d([plain, remembered], value,
                                             Goal.parse("Questelj", 1),
                                             recognition_by_track=recognition)
    assert [item["track_id"] for item in ranked[:2]] == ["remembered", "plain"]
    assert ranked[0]["semantic_type"] == "UNKNOWN"
    assert ranked[0]["action_authority"] == "NONE"


def test_strong_temporal_memory_probe_can_outrank_generic_overhead_cue():
    overhead = {"source": "WORLD3D", "kind": "unknown_subject_candidate",
                "detector_kind": "unknown_subject_candidate", "semantic_type": "UNKNOWN",
                "track_id": "overhead", "stable_frames": 4, "x": .42, "y": .6,
                "bbox_height_fraction": .105,
                "visual_relations": [{"type": "ABOVE", "belief": "SUPPORTED"}],
                "appearance": {"body_geometry": .97, "foreground_contrast": 1.,
                               "screen_center_relevance": .82, "static_scene_score": 1.}}
    remembered = {"source": "WORLD3D", "kind": "unknown_subject_candidate",
                  "detector_kind": "unknown_subject_candidate", "semantic_type": "UNKNOWN",
                  "track_id": "remembered", "stable_frames": 4, "x": .58, "y": .6,
                  "bbox_height_fraction": .105,
                  "appearance": {"body_geometry": .97, "foreground_contrast": .85,
                                 "screen_center_relevance": .95, "residual_motion": .34,
                                 "static_scene_score": .55}}
    value = _world([overhead, remembered])
    recognition = {"remembered": [{"track_id": "remembered", "entity_candidates": [{
        "identity_key": "npc:150229", "status": "CANDIDATE", "similarity": .9171,
        "temporal_support_frames": 4,
    }]}]}
    ranked = ActivePerception().rank_world3d([overhead, remembered], value,
                                             Goal.parse("Questelj", 1),
                                             recognition_by_track=recognition)
    assert ranked[0]["track_id"] == "remembered"
    assert ranked[0]["expected_information_gain"] > ranked[1]["expected_information_gain"]
    assert ranked[0]["semantic_type"] == "UNKNOWN"


def test_planner_inspects_canonical_top_attention_track_before_generic_nameplate_cue():
    overhead = {"source": "WORLD3D", "kind": "unknown_subject_candidate",
                "detector_kind": "unknown_subject_candidate", "semantic_type": "UNKNOWN",
                "track_id": "generic-overhead", "stable_frames": 4, "confidence": .8,
                "x": .42, "y": .6, "inspectable": True, "bbox_height_fraction": .105,
                "visual_relations": [{"type": "ABOVE", "belief": "SUPPORTED"}],
                "appearance": {"body_geometry": .97, "foreground_contrast": 1.,
                               "screen_center_relevance": .82, "static_scene_score": 1.}}
    remembered = {"source": "WORLD3D", "kind": "unknown_subject_candidate",
                  "detector_kind": "unknown_subject_candidate", "semantic_type": "UNKNOWN",
                  "track_id": "remembered", "stable_frames": 4, "confidence": .8,
                  "x": .58, "y": .6, "inspectable": True, "bbox_height_fraction": .105,
                  "appearance": {"body_geometry": .97, "foreground_contrast": .85,
                                 "screen_center_relevance": .95, "residual_motion": .34,
                                 "static_scene_score": .55}}
    value = _world([overhead, remembered], visual_recognition_candidates=[{
        "track_id": "remembered", "entity_candidates": [{
            "identity_key": "npc:150229", "status": "CANDIDATE", "similarity": .9171,
            "temporal_support_frames": 4,
        }],
    }])
    proposals = Planner(SkillRegistry()).inspections(value, 1., goal=Goal.parse("Questelj", 1))
    world3d = [proposal for proposal in proposals if proposal.parameters.get("source") == "WORLD3D"]
    assert world3d[0].parameters["track_id"] == "remembered"
    assert world3d[0].parameters["attention_rank"] == 1
    assert world3d[0].parameters["semantic_type"] == "UNKNOWN"


def test_stable_learned_humanoid_is_inspectable_without_nameplate_gate():
    learned = {
        "source": "WORLD3D", "kind": "unknown_subject_candidate",
        "detector_kind": "unknown_subject_candidate", "semantic_type": "UNKNOWN",
        "track_id": "learned-humanoid", "stable_frames": 4, "confidence": .35,
        "x": .42, "y": .62, "inspectable": True, "bbox_height_fraction": .12,
        "candidate_labels": ["learned_subject_like"],
        "appearance": {"learned_label_hypothesis": "humanoid_unit_like",
                       "body_geometry": .8, "foreground_contrast": .7},
    }
    # An unrelated nameplate used to become a mandatory gate and suppress the
    # learned visual subject even though detection must not depend on plates.
    value = _world([learned], nameplates=[{"nx": .95, "name": "Other"}])
    proposals = Planner(SkillRegistry()).inspections(
        value, 1., goal=Goal.parse("Questelj", 1))
    inspected = [item for item in proposals
                 if item.skill == "INSPECT"
                 and item.parameters.get("track_id") == "learned-humanoid"]
    assert len(inspected) == 1
    assert inspected[0].confidence == .15
    assert inspected[0].parameters["semantic_type"] == "UNKNOWN"


def test_learned_subject_inspection_uses_point_15_boundary():
    common = {
        "source": "WORLD3D", "kind": "unknown_subject_candidate",
        "detector_kind": "unknown_subject_candidate", "semantic_type": "UNKNOWN",
        "stable_frames": 4, "x": .42, "y": .62, "inspectable": True,
        "bbox_height_fraction": .12, "candidate_labels": ["learned_subject_like"],
        "appearance": {"learned_label_hypothesis": "creature_unit_like",
                       "body_geometry": .8, "foreground_contrast": .7},
    }
    below = {**common, "track_id": "below", "confidence": .149}
    boundary = {**common, "track_id": "boundary", "confidence": .15}

    below_proposals = Planner(SkillRegistry()).inspections(
        _world([below]), 1., goal=Goal.parse("Questelj", 1))
    boundary_proposals = Planner(SkillRegistry()).inspections(
        _world([boundary]), 1., goal=Goal.parse("Questelj", 1))

    assert not any(item.parameters.get("track_id") == "below"
                   for item in below_proposals)
    admitted = [item for item in boundary_proposals
                if item.parameters.get("track_id") == "boundary"]
    assert len(admitted) == 1
    assert admitted[0].confidence == .15


def test_badge_like_overhead_retains_full_attention_value():
    common = {"source": "WORLD3D", "kind": "unknown_subject_candidate",
              "detector_kind": "unknown_subject_candidate", "semantic_type": "UNKNOWN",
              "stable_frames": 4, "x": .5, "y": .6,
              "visual_relations": [{"type": "ABOVE", "belief": "SUPPORTED"}]}
    generic = {**common, "track_id": "generic"}
    badge = {**common, "track_id": "badge", "candidate_labels": ["quest_badge_like"],
             "appearance": {"quest_badge_likeness": .8}}
    value = _world([generic, badge])
    active = ActivePerception()
    generic_score = active.evaluate(generic, value, Goal.parse("Questelj", 1))
    badge_score = active.evaluate(badge, value, Goal.parse("Questelj", 1))
    assert badge_score["expected_information_gain"] > generic_score["expected_information_gain"]
    # The explicit ``quest_badge_like`` label is stronger than the raw
    # appearance score: it is a full visual-specificity cue, not a semantic
    # assertion about the subject beneath it.
    assert badge_score["world3d_features"]["overhead_specificity"] == 1.0


def test_badge_like_unknown_probe_starts_visual_seek_before_generic_inspection():
    """A quest-shaped cue is an information-gain priority, not a role fact."""
    generic = {"source": "WORLD3D", "kind": "unknown_subject_candidate",
               "detector_kind": "unknown_subject_candidate", "semantic_type": "UNKNOWN",
               "track_id": "random-foreground", "stable_frames": 8, "confidence": .9,
               "x": .65, "y": .62, "inspectable": True, "bbox_height_fraction": .14,
               "appearance": {"body_geometry": .97, "foreground_contrast": .9,
                              "screen_center_relevance": .8}}
    badge_probe = {"source": "WORLD3D", "kind": "unknown_subject_probe",
                   "detector_kind": "unknown_subject_probe", "semantic_type": "UNKNOWN",
                   "track_id": "badge-probe", "stable_frames": 8, "confidence": .75,
                   "x": .45, "y": .56, "inspectable": True, "bbox_height_fraction": .04,
                   "candidate_labels": ["quest_badge_like", "subject_below_symbol_probe"],
                   "appearance": {"quest_badge_likeness": .9,
                                  "anchor_candidate_labels": ["quest_badge_like"]}}
    proposals = Planner(SkillRegistry()).candidates(
        Goal.parse("Questelj", 1), _world([generic, badge_probe], world_map_open=False), 1.)
    world3d_inspects = [proposal for proposal in proposals
                        if proposal.skill == "INSPECT"
                        and proposal.parameters.get("source") == "WORLD3D"]
    seek = next(proposal for proposal in proposals if proposal.skill == "SEEK_VISUAL_CUE")
    assert seek.parameters["track_id"] == "badge-probe"
    assert seek.priority == 87
    assert not world3d_inspects


def test_supported_learned_glyph_probe_beats_bare_body_after_fusion_discount():
    """Live repro: Jaina glyph/body was present, but Ke-La INSPECT won."""
    generic = {"source": "WORLD3D", "kind": "unknown_subject_candidate",
               "detector_kind": "unknown_subject_candidate", "semantic_type": "UNKNOWN",
               "track_id": "kee-la", "stable_frames": 4, "confidence": .25,
               "x": .266, "y": .606, "inspectable": True,
               "bbox_height_fraction": .0905,
               "candidate_labels": ["learned_subject_like"],
               "appearance": {"learned_label_hypothesis": "humanoid_unit_like",
                              "body_geometry": .4259, "foreground_contrast": .8258}}
    jaina_probe = {
        "source": "WORLD3D", "kind": "unknown_subject_probe",
        "detector_kind": "unknown_subject_probe", "semantic_type": "UNKNOWN",
        "track_id": "jaina-probe", "stable_frames": 8, "confidence": .304,
        "x": .536, "y": .564, "inspectable": False,
        "servo_scale_fraction": .04,
        "candidate_labels": ["subject_below_symbol_probe"],
        "appearance": {"anchor_candidate_labels": ["learned_symbol_like"]},
        "visual_relations": [{"type": "ABOVE", "belief": "SUPPORTED"}],
        "visual_group": {"belief": "SUPPORTED",
                         "appearance_labels": ["learned_symbol_like"]},
    }
    proposals = Planner(SkillRegistry()).candidates(
        Goal.parse("Questelj", 1),
        _world([generic, jaina_probe], world_map_open=False), 1.)

    seek = next(proposal for proposal in proposals
                if proposal.skill == "SEEK_VISUAL_CUE")
    assert seek.parameters["track_id"] == "jaina-probe"
    assert seek.priority == 86
    assert not any(proposal.skill == "INSPECT"
                   and proposal.parameters.get("source") == "WORLD3D"
                   for proposal in proposals)
