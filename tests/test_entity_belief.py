from wowbot.agent.entity_belief import (
    EntityBelief,
    IdentityEvidence,
    fuse_identity,
    rank_identity_source,
)


def test_identity_source_ranking_matches_spec_order():
    assert rank_identity_source("addon_quest_reference") == 0
    assert rank_identity_source("target_frame_tooltip_name") == 1
    assert rank_identity_source("stable_nameplate_text") == 2
    assert rank_identity_source("quest_marker_and_context") == 3
    assert rank_identity_source("visual_appearance_classifier") == 4
    assert rank_identity_source("something_unknown") == 5


def test_no_evidence_yields_an_empty_zero_confidence_belief():
    belief = fuse_identity("Creature-1", ())
    assert belief.identity_belief is None
    assert belief.confidence == 0.0


def test_stronger_ranked_source_wins_over_weaker_even_if_weaker_is_more_confident():
    evidence = (
        IdentityEvidence("visual_appearance_classifier", "Wolf", 0.95, 10.0),
        IdentityEvidence("addon_quest_reference", "Timberstrider", 0.6, 10.0),
    )
    belief = fuse_identity("Creature-1", evidence, now=10.0)
    assert belief.identity_belief == "Timberstrider"


def test_weak_visual_evidence_alone_is_capped_below_confirmed():
    evidence = (IdentityEvidence("visual_appearance_classifier", "Wolf", 0.99, 10.0),)
    belief = fuse_identity("Creature-1", evidence, now=10.0)
    assert belief.identity_belief == "Wolf"
    assert belief.confidence <= 0.45


def test_contradiction_between_sources_reduces_confidence():
    agreeing = fuse_identity("Creature-1", (
        IdentityEvidence("addon_quest_reference", "Timberstrider", 0.9, 10.0),
        IdentityEvidence("stable_nameplate_text", "Timberstrider", 0.8, 10.0),
    ), now=10.0)
    conflicting = fuse_identity("Creature-1", (
        IdentityEvidence("addon_quest_reference", "Timberstrider", 0.9, 10.0),
        IdentityEvidence("stable_nameplate_text", "Some Other Wolf", 0.8, 10.0),
    ), now=10.0)
    assert conflicting.confidence < agreeing.confidence


def test_old_evidence_decays_toward_zero_rather_than_staying_at_face_value():
    fresh = fuse_identity("Creature-1", (
        IdentityEvidence("addon_quest_reference", "Timberstrider", 0.9, 100.0),
    ), now=100.0)
    stale = fuse_identity("Creature-1", (
        IdentityEvidence("addon_quest_reference", "Timberstrider", 0.9, 100.0),
    ), now=140.0)
    assert stale.confidence < fresh.confidence


def test_first_seen_and_last_seen_span_the_evidence_timestamps():
    belief = fuse_identity("Creature-1", (
        IdentityEvidence("addon_quest_reference", "Timberstrider", 0.9, 5.0),
        IdentityEvidence("stable_nameplate_text", "Timberstrider", 0.7, 12.0),
    ), now=12.0)
    assert belief.first_seen == 5.0
    assert belief.last_seen == 12.0


def test_entity_belief_carries_the_full_evidence_trail():
    evidence = (IdentityEvidence("addon_quest_reference", "Timberstrider", 0.9, 5.0),)
    belief = fuse_identity("Creature-1", evidence, now=5.0)
    assert isinstance(belief, EntityBelief)
    assert belief.evidence == evidence
    assert belief.entity_ref == "Creature-1"
