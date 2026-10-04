from wowbot.agent.quest_info_hierarchy import (
    QuestInfoSource,
    rank_quest_info_source,
    resolve_first_available,
)


def test_ranking_follows_the_spec_letters_a_through_h_in_order():
    assert rank_quest_info_source(QuestInfoSource.QUEST_TRACKER) == 0
    assert rank_quest_info_source(QuestInfoSource.WORLD_MAP) == 1
    assert rank_quest_info_source(QuestInfoSource.SUPERTRACK_MARKER) == 2
    assert rank_quest_info_source(QuestInfoSource.MINIMAP) == 3
    assert rank_quest_info_source(QuestInfoSource.WORLD_3D) == 4
    assert rank_quest_info_source(QuestInfoSource.TARGET_NAMEPLATE_TOOLTIP) == 5
    assert rank_quest_info_source(QuestInfoSource.QUEST_SPECIFIC_UI) == 6
    assert rank_quest_info_source(QuestInfoSource.TEMPORAL_HISTORY) == 7


def test_quest_tracker_wins_over_every_other_available_source():
    available = {
        QuestInfoSource.QUEST_TRACKER: "tracker-value",
        QuestInfoSource.WORLD_MAP: "map-value",
        QuestInfoSource.WORLD_3D: "3d-value",
    }
    result = resolve_first_available(available)
    assert result == (QuestInfoSource.QUEST_TRACKER, "tracker-value")


def test_world_3d_is_only_used_when_nothing_higher_ranked_is_available():
    # This is the literal "do not reduce the system to 3D object
    # detection" guard: E only wins when A-D are absent.
    available = {
        QuestInfoSource.QUEST_TRACKER: None,
        QuestInfoSource.WORLD_MAP: None,
        QuestInfoSource.MINIMAP: None,
        QuestInfoSource.WORLD_3D: "3d-value",
    }
    result = resolve_first_available(available)
    assert result == (QuestInfoSource.WORLD_3D, "3d-value")


def test_temporal_history_is_the_last_resort():
    available = {source: None for source in QuestInfoSource if source is not QuestInfoSource.TEMPORAL_HISTORY}
    available[QuestInfoSource.TEMPORAL_HISTORY] = "history-value"
    result = resolve_first_available(available)
    assert result == (QuestInfoSource.TEMPORAL_HISTORY, "history-value")


def test_nothing_available_returns_none():
    assert resolve_first_available({}) is None
    assert resolve_first_available({QuestInfoSource.QUEST_TRACKER: None}) is None
