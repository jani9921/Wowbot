from wowbot.runtime import FailureReason
from wowbot.skills.interaction_result import InteractionEffectKind, InteractionResultClassifier, InteractionResultKind


def test_classifier_maps_recoverable_verifier_reasons_without_semantic_guessing():
    classifier = InteractionResultClassifier()

    assert classifier.classify(FailureReason.OUT_OF_RANGE) is InteractionResultKind.OUT_OF_RANGE
    assert classifier.classify(FailureReason.FACING_FAILED) is InteractionResultKind.FACING
    assert classifier.classify(FailureReason.TARGET_LOST) is InteractionResultKind.TARGET_LOST
    assert classifier.classify(FailureReason.NO_RESPONSE) is InteractionResultKind.NO_RESPONSE


def test_classifier_distinguishes_explicit_wrong_ui_from_generic_failure():
    classifier = InteractionResultClassifier()

    assert classifier.classify(FailureReason.INVALID_TARGET, after_snapshot={"wrong_dialog_open": True}) is InteractionResultKind.WRONG_ENTITY
    assert classifier.classify(FailureReason.INVALID_TARGET) is InteractionResultKind.WRONG_ENTITY
    assert classifier.classify(None) is InteractionResultKind.SUCCESS


def test_effect_classifier_reports_observable_ui_delta_separately_from_success():
    classifier = InteractionResultClassifier()
    assert classifier.classify_effect(
        {"quest_ui": {"open": False}},
        {"quest_ui": {"open": True, "action": "OFFER"}},
    ) is InteractionEffectKind.QUEST_DETAIL_OPEN
    assert classifier.classify_effect(
        {"quest_ui": {"open": False}},
        {"quest_ui": {"open": True, "action": "REWARD"}},
    ) is InteractionEffectKind.QUEST_COMPLETE_OPEN
