from __future__ import annotations

from wowbot.agent.models import Observation
from wowbot.agent.world import WorldModel


def _observation(payload: dict, at: float, frame: str) -> Observation:
    return Observation.create({
        "session_id": "test:player", "timestamp": at, "frame_id": frame,
        "player_present": True, **payload,
    }, at, source="ADDON_TELEMETRY")


def test_full_then_fast_same_guid_preserves_detail_identity_fields() -> None:
    model = WorldModel()
    full = _observation({
        "transport_kind": "STATE", "target": {
            "guid": "Creature-1", "name": "Murloc Spearhunter",
            "npc_id": 150228, "unit_type": "NPC", "attackable": True,
        }, "active_quests": [], "position": {"x": .5, "y": .5},
    }, 1., "full-1")
    assert model.ingest(full)
    fast = _observation({
        "transport_kind": "FAST", "target": {
            "guid": "Creature-1", "health": 73, "name": None,
        }, "position": {"x": .51, "y": .5},
    }, 2., "fast-1")

    assert model.ingest(fast)

    assert model.state["target"]["name"] == "Murloc Spearhunter"
    assert model.state["target"]["npc_id"] == 150228
    assert model.state["target"]["health"] == 73
    assert model.last_received == 2.


def test_fast_different_guid_never_inherits_previous_identity() -> None:
    model = WorldModel()
    assert model.ingest(_observation({
        "transport_kind": "STATE", "target": {
            "guid": "Creature-1", "name": "Old", "npc_id": 1,
        }, "active_quests": [],
    }, 1., "full-1"))

    assert model.ingest(_observation({
        "transport_kind": "FAST", "target": {
            "guid": "Creature-2", "health": 100,
        },
    }, 2., "fast-1"))

    assert model.state["target"]["guid"] == "Creature-2"
    assert "name" not in model.state["target"]
    assert "npc_id" not in model.state["target"]


def test_full_addon_reducer_keeps_worldmodel_as_only_state_owner() -> None:
    model = WorldModel()
    reducer = model._addon_reducer
    assert vars(reducer) == {}

    assert model.ingest(_observation({
        "transport_kind": "STATE", "quest_ui_open": True,
        "active_quests": [{"quest_id": 54951, "title": "Emergency First Aid",
                           "objectives": []}],
        "events": [{"sequence": 1, "event_type": "QUEST_ACCEPTED",
                    "quest_id": 54951}],
    }, 1., "full-quest"))

    assert model.latest.observation_id
    assert model.quest_model.records
    assert any(record.event_type == "QUEST_ACCEPTED" for record in model.event_records)
    assert model.state["quest_ui_open"] is True


def test_fast_addon_reducer_preserves_map_context_for_resolver_and_query() -> None:
    model = WorldModel()
    context = {"player_map_id": 2175, "displayed_map_id": 1409,
               "active_map_id": 1409, "parent_map_id": 13,
               "parent_map_name": "Eastern Kingdoms", "world_map_open": True}
    assert model.ingest(_observation({
        "transport_kind": "FAST", "map_id": 2175,
        "world_map_open": True, "map_context": context,
    }, 1., "fast-map"))
    assert model.state["map_context"] == context
    assert model.query.player()["map_context"]["parent_map_id"] == 13
    assert model.belief("map_context", now=1.)["value"]["active_map_id"] == 1409


def test_fast_closed_quest_ui_invalidates_stale_full_reward_dialog() -> None:
    model = WorldModel()
    assert model.ingest(_observation({
        "transport_kind": "STATE",
        "active_quests": [{"quest_id": 7, "is_complete": False,
                           "objectives": [{"current": 1, "required": 6}]}],
        "quest_ui": {
            "open": True, "action": "REWARD_SELECT", "quest_id": 0,
            "reward_choices": [{"index": 1, "item_id": 57255, "x": 0, "y": 0}],
        },
    }, 1., "full-stale-reward"))
    assert model.state["quest_ui"]["open"] is True

    assert model.ingest(_observation({
        "transport_kind": "FAST", "quest_ui_open": False,
        "quest_ui_action": "", "quest_ui_x": 0, "quest_ui_y": 0,
        "quest_ui_quest_id": 0,
    }, 1.1, "fast-closed"))

    assert model.state["quest_ui"] == {
        "open": False, "action": "", "x": 0, "y": 0,
        "quest_id": 0, "entries": [], "reward_choices": [],
        "reward_selected_index": 0,
    }
    assert model.state["quest_ui_open"] is False
