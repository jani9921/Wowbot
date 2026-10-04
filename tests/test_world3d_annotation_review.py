from wowbot.vision.world3d.annotation_review import (
    AnnotationBox,
    bootstrap_box,
    proposal_from_candidate,
    suppress_overlapping_proposals,
    supported_review_proposal,
    suggested_class,
    yolo_line,
)
from wowbot.vision.world3d.models import PixelRect, WorldCandidate


def candidate(kind="unknown_subject_candidate", confidence=.8, labels=(), rect=None):
    return WorldCandidate(kind, rect or PixelRect(10, 20, 50, 80), confidence,
                          candidate_labels=tuple(labels))


def test_proposals_are_unaccepted_and_unknown_first() -> None:
    item = WorldCandidate(
        "unknown_subject_candidate", PixelRect(10, 20, 50, 80), .8,
        appearance={"track_hits": 2}, candidate_labels=("possible_nameplate_like",))
    proposal = proposal_from_candidate(item, 100, 100)

    assert proposal is not None
    assert proposal.class_id == 0
    assert proposal.status == "PROPOSED"
    assert proposal.source == "WORLD3D_V3_PROPOSAL"


def test_generic_scenery_like_subject_does_not_become_review_burden() -> None:
    noisy = candidate(labels=("generic_subject_like",))
    supported = WorldCandidate(
        "unknown_subject_candidate", PixelRect(10, 20, 50, 80), .8,
        appearance={"track_hits": 2}, candidate_labels=("possible_nameplate_like",))

    assert not supported_review_proposal(noisy)
    assert proposal_from_candidate(noisy, 100, 100) is None
    assert supported_review_proposal(supported)


def test_sparse_video_motion_without_anchor_is_not_prelabel_ground_truth() -> None:
    item = WorldCandidate(
        "unknown_subject_candidate", PixelRect(10, 10, 40, 80), .78,
        appearance={"track_hits": 4, "static_scene_score": .1,
                    "independent_motion": .8, "body_geometry": .9},
        candidate_labels=("generic_subject_like",),
    )

    assert not supported_review_proposal(item)


def test_visual_families_only_suggest_appearance_classes() -> None:
    assert suggested_class(candidate("unknown_symbol_candidate")) == 5
    assert suggested_class(candidate("unknown_object_candidate")) == 4
    assert suggested_class(candidate("unknown_object_candidate", labels=("outline_like_cue",))) == 3
    assert suggested_class(candidate(labels=("learned_corpse_like",))) == 2
    assert suggested_class(candidate("unknown_scene_candidate")) is None


def test_nms_reduces_duplicate_proposals_but_keeps_separate_boxes() -> None:
    boxes = [
        AnnotationBox("a", 0, 0, 40, 40, 0, .9),
        AnnotationBox("b", 1, 1, 41, 41, 1, .8),
        AnnotationBox("c", 60, 10, 90, 50, 0, .7),
    ]
    kept = suppress_overlapping_proposals(boxes)

    assert [box.box_id for box in kept] == ["a", "c"]


def test_yolo_export_uses_only_normalized_geometry() -> None:
    box = AnnotationBox("a", 10, 20, 50, 80, 1, 1.0, status="ACCEPTED")

    assert yolo_line(box, 100, 100) == "1 0.300000 0.500000 0.400000 0.600000"


def test_generic_pretrained_bootstrap_is_allowlisted_and_excludes_hud_centres() -> None:
    hud = PixelRect(0, 0, 100, 30)

    person = bootstrap_box("person", .8, (10, 40, 40, 90), 100, 100, excluded=(hud,))
    animal = bootstrap_box("dog", .7, (50, 40, 90, 90), 100, 100, excluded=(hud,))
    ui_false_class = bootstrap_box("traffic light", .9, (10, 40, 40, 90), 100, 100)
    hud_person = bootstrap_box("person", .9, (10, 0, 40, 20), 100, 100, excluded=(hud,))

    assert person is not None and person.class_id == 0
    assert animal is not None and animal.class_id == 1
    assert ui_false_class is None
    assert hud_person is None


def test_review_model_class_names_remain_proposals_with_explicit_provenance() -> None:
    proposal = bootstrap_box(
        "corpse_like", .8, (10, 40, 60, 90), 100, 100)

    assert proposal is not None
    assert proposal.class_id == 2
    assert proposal.status == "PROPOSED"
    assert proposal.source == "LEARNED_ANNOTATION_ASSIST_REVIEW"


def test_review_model_proposal_floor_is_configurable_without_accepting_box() -> None:
    default_rejected = bootstrap_box(
        "creature_unit_like", .15, (10, 40, 60, 90), 100, 100)
    review_candidate = bootstrap_box(
        "creature_unit_like", .15, (10, 40, 60, 90), 100, 100,
        minimum_confidence=.15)

    assert default_rejected is None
    assert review_candidate is not None
    assert review_candidate.status == "PROPOSED"
    assert review_candidate.confidence == .15
