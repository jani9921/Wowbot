from wowbot.agent.quest_model import ObjectiveClassifier, objective_type


def test_classifier_prefers_normalized_addon_type_and_exposes_m1_kind():
    result = ObjectiveClassifier().classify({"type": "TALK_TO", "description": "Kill a mob"})
    assert result.type == "TALK_TO"
    assert result.canonical_kind == "SPEAK"
    assert result.evidence[0]["source"] == "ADDON_NORMALIZED"


def test_classifier_keeps_ambiguous_text_unknown_instead_of_guessing():
    result = ObjectiveClassifier().classify({"description": "Find and kill the target"})
    assert result.type == "UNKNOWN"
    assert len(result.evidence) == 2
    assert objective_type({"raw_type": "monster"})[:2] == ("KILL", .95)
