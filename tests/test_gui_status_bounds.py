from wowbot.agent.gui import AgentWindow


def test_gui_detail_projection_excludes_unbounded_world_graphs():
    state = {"mode": "MANUAL", "world": {"session_id": "s", "fresh": True,
        "player": {"map_id": 1409, "position": {"x": .2, "y": .3},
                   "binding_catalog_page": {"rows": list(range(5000))}},
        "relations": [{"large": "x"*1000} for _ in range(5000)],
        "predictions": [{"id": i} for i in range(1000)],
        "verifications": [{"id": i} for i in range(1000)],
        "diagnostic_totals": {"relations": 5000}},
        "vision_diagnostics": {"world": {"status": "ready"},
            "tracks": [{"source": "WORLD3D", "track_id": str(i), "state": "STABLE",
                        "appearance_history": ["x"*1000]} for i in range(100)]}}
    compact = AgentWindow._compact_detail(state)
    assert "relations" not in compact["world"]
    assert "binding_catalog_page" not in compact["world"]["player"]
    assert len(compact["world"]["verifications"]) == 12
    assert compact["vision_diagnostics"]["track_total"] == 100
    assert len(compact["vision_diagnostics"]["tracks"]) == 24

