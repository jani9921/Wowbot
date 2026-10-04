from wowbot.agent.quest_model import OBJECTIVE_TYPES, ObjectiveClassifier


def test_all_spec_minimum_types_are_present_in_the_supported_set():
    # V4-016's own minimum list, translated to this module's raw-type names
    # (SPEAK/INTERACT_NPC/TRAVEL/REACH_AREA/etc. map onto TALK_TO plus the
    # newly-added raw types; UNKNOWN was already present).
    required = {
        "TALK_TO", "INTERACT_NPC", "KILL", "KILL_NAMED", "COLLECT", "LOOT",
        "INTERACT", "USE_OBJECT", "USE_ITEM_ON_TARGET", "TRAVEL_TO", "REACH_AREA",
        "FOLLOW", "ESCORT", "DEFEND", "WAIT", "EMOTE", "GOSSIP_CHOICE", "VEHICLE",
        "EXTRA_ACTION", "QUEST_TOOL_BUTTON", "SPECIAL_UI", "SCRIPTED_EVENT",
        "FIELD_TURN_IN", "MULTI_STAGE", "UNKNOWN",
    }
    assert required <= OBJECTIVE_TYPES


def test_new_types_classify_via_addon_normalized_evidence():
    classifier = ObjectiveClassifier()
    for new_type in ("KILL_NAMED", "GOSSIP_CHOICE", "VEHICLE", "EXTRA_ACTION",
                      "QUEST_TOOL_BUTTON", "SPECIAL_UI", "SCRIPTED_EVENT",
                      "FIELD_TURN_IN", "MULTI_STAGE", "EMOTE", "USE_ITEM_ON_TARGET",
                      "REACH_AREA", "INTERACT_NPC"):
        result = classifier.classify({"type": new_type})
        assert result.type == new_type
        assert result.confidence == .95
        assert result.canonical_kind == new_type


def test_loot_stays_aliased_to_collect_new_type_did_not_shadow_the_existing_alias():
    # "LOOT" was already a pre-existing alias for COLLECT (_ALIASES); adding
    # LOOT to OBJECTIVE_TYPES/​_canonical for V4-016 must not shadow that.
    classifier = ObjectiveClassifier()
    result = classifier.classify({"type": "LOOT"})
    assert result.type == "COLLECT"


def test_existing_classification_behavior_is_unchanged_for_pre_existing_inputs():
    # Regression guard: the additive change must not alter any input that
    # already classified correctly before V4-016's types were added.
    classifier = ObjectiveClassifier()
    assert classifier.classify({"type": "KILL"}).type == "KILL"
    assert classifier.classify({"raw_type": "monster"}).type == "KILL"
    assert classifier.classify({"description": "Kill 5 wolves"}).type == "KILL"
    assert classifier.classify({"description": "Collect 3 pelts"}).type == "COLLECT"
    assert classifier.classify({}).type == "UNKNOWN"
