from wowbot.agent.next_quest_source_hierarchy import NextQuestSource, resolve_next_quest_source


def test_order_matches_the_spec_exactly():
    assert list(NextQuestSource) == [
        NextQuestSource.RESULTING_UI, NextQuestSource.SAME_NPC,
        NextQuestSource.LOCAL_MARKERS, NextQuestSource.TRACKER_LOG,
        NextQuestSource.WORLD_MAP, NextQuestSource.CAMPAIGN_CLASSIFICATION,
    ]


def test_resulting_ui_wins_over_every_other_available_source():
    available = {
        NextQuestSource.RESULTING_UI: "quest-from-ui",
        NextQuestSource.SAME_NPC: "quest-from-npc",
        NextQuestSource.CAMPAIGN_CLASSIFICATION: "quest-from-campaign",
    }
    assert resolve_next_quest_source(available) == (NextQuestSource.RESULTING_UI, "quest-from-ui")


def test_does_not_assume_same_npc_when_it_has_no_evidence():
    available = {
        NextQuestSource.RESULTING_UI: None,
        NextQuestSource.SAME_NPC: None,
        NextQuestSource.LOCAL_MARKERS: "quest-from-markers",
    }
    assert resolve_next_quest_source(available) == (NextQuestSource.LOCAL_MARKERS, "quest-from-markers")


def test_campaign_classification_is_the_last_resort():
    available = {source: None for source in NextQuestSource if source is not NextQuestSource.CAMPAIGN_CLASSIFICATION}
    available[NextQuestSource.CAMPAIGN_CLASSIFICATION] = "campaign-quest"
    assert resolve_next_quest_source(available) == (NextQuestSource.CAMPAIGN_CLASSIFICATION, "campaign-quest")


def test_nothing_available_returns_none():
    assert resolve_next_quest_source({}) is None
    assert resolve_next_quest_source({NextQuestSource.SAME_NPC: None}) is None
