"""Regression tests for the bounded Tk diagnostics projection."""
import json

from wowbot.agent.gui import AgentWindow


def test_gui_compact_detail_excludes_unbounded_world_history_and_track_blobs():
    blob = "x" * 8_000
    state = {
        "mode": "MANUAL", "pid": 42, "binding_inventory": {"status": "complete",
        "pages_received": 4, "pages_expected": 4, "rows": [{"raw": blob}]},
        "navigation": {"authority": "NavigationService",
                       "route": {"route": ["a"] * 20, "topology": [{"raw": blob}] * 10},
                       "movement": {"phase": "IDLE"}},
        "autonomous_loop": {"phase": "IDLE", "commitment": {}, "lifecycle": [{"raw": blob}]},
        "goal_manager": {"active": True, "tasks": [{"raw": blob}] * 20},
        "world": {
            "session_id": "test", "fresh": True,
            "player": {"target": {"guid": "npc", "name": "Guide", "raw": blob},
                       "mouseover": {"guid": "npc", "raw": blob},
                       "active_quests": [{"quest_id": 1, "objectives": [{"current": 1, "raw": blob}]}]},
            "beliefs": {str(index): {"raw": blob} for index in range(20)},
            "relations": [{"raw": blob}] * 20,
            "events": [{"event_type": "EVENT", "payload": {"raw": blob}}] * 20,
            "verifications": [{"outcome": "SUCCESS", "raw": blob}] * 20,
            "prediction_errors": [{"reason": "none", "raw": blob}] * 20,
        },
        "vision_diagnostics": {"tracks": [{"track_id": str(index), "raw": blob}
                                             for index in range(50)]},
    }

    compact = AgentWindow._compact_detail(state)
    rendered = json.dumps(compact, ensure_ascii=False)

    assert compact["world"]["belief_count"] == 20
    assert "beliefs" not in compact["world"]
    assert compact["vision_diagnostics"]["track_total"] == 50
    assert "raw" not in rendered
    assert len(rendered) < 20_000
