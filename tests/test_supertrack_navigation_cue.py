from wowbot.agent.supertrack_navigation_cue import (
    KNOWN_DISAPPEARANCE_REASONS,
    NavigationCueSource,
    resolve_navigation_cue,
)


def test_supertrack_cue_wins_when_present():
    available = {
        NavigationCueSource.SUPERTRACK_CUE: "cue-value",
        NavigationCueSource.MINIMAP_BELIEF: "minimap-value",
    }
    assert resolve_navigation_cue(available) == (NavigationCueSource.SUPERTRACK_CUE, "cue-value")


def test_absent_cue_falls_back_to_minimap_belief():
    # "Never confuse 'no navigation arrow' with 'quest has no location'" --
    # absence just means fall through to the next source.
    available = {
        NavigationCueSource.SUPERTRACK_CUE: None,
        NavigationCueSource.MINIMAP_BELIEF: "minimap-value",
    }
    assert resolve_navigation_cue(available) == (NavigationCueSource.MINIMAP_BELIEF, "minimap-value")


def test_falls_back_through_world_map_to_location_belief():
    available = {
        NavigationCueSource.SUPERTRACK_CUE: None,
        NavigationCueSource.MINIMAP_BELIEF: None,
        NavigationCueSource.WORLD_MAP_BELIEF: None,
        NavigationCueSource.LOCATION_BELIEF: "location-value",
    }
    assert resolve_navigation_cue(available) == (NavigationCueSource.LOCATION_BELIEF, "location-value")


def test_nothing_available_returns_none_not_a_guess():
    assert resolve_navigation_cue({}) is None
    assert resolve_navigation_cue({NavigationCueSource.SUPERTRACK_CUE: None}) is None


def test_known_disappearance_reasons_match_the_spec_list():
    assert KNOWN_DISAPPEARANCE_REASONS == {
        "FOCUS_CHANGED", "QUEST_TURNED_IN", "MAP_CONTEXT_CHANGED",
        "OBJECTIVE_CHANGED", "ROUTE_UNSUPPORTED",
    }
