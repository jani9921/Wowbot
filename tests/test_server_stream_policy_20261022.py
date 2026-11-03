"""Server selection survives unhealthy input; health never enables vision."""
from wowbot.agent.models import Proposal
from wowbot.agent.planner import Planner
from wowbot.agent.server_mode import server_mode_active, server_mode_selected, status


def test_selected_server_mode_never_falls_back_when_stream_goes_stale(monkeypatch):
    monkeypatch.setenv("AIPC_SERVER_MODE", "1")
    for age, entities in ((0.1, 12), (21., 12), (300., 0), (None, 0)):
        state = {"server_mode": status(age, entities)}
        assert server_mode_selected(state)
        assert server_mode_active(state) is (age == 0.1)
        seek = Proposal.make("SEEK_VISUAL_CUE", "old fallback", {})
        loot = Proposal.make("VISUAL_APPROACH", "screen corpse", {"purpose": "LOOT"})
        kept = Planner.prefer_server_targets([seek, loot], server_mode=server_mode_selected(state))
        assert [p.skill for p in kept] == ["WAIT"]


def test_explicit_vision_mode_is_still_available(monkeypatch):
    monkeypatch.setenv("AIPC_SERVER_MODE", "0")
    assert not server_mode_selected({"server_mode": status(0.1, 10)})


def test_offline_world_without_a_configured_packet_sensor_keeps_legacy_policy(monkeypatch):
    monkeypatch.delenv("AIPC_SERVER_MODE", raising=False)
    monkeypatch.delenv("AIPC_PACKET_TELEMETRY", raising=False)
    assert not server_mode_selected({"server_mode": status(None, 0)})


def test_packet_enabled_startup_is_already_server_selected(monkeypatch):
    monkeypatch.delenv("AIPC_SERVER_MODE", raising=False)
    monkeypatch.setenv("AIPC_PACKET_TELEMETRY", "1")
    state = {"server_mode": status(None, 0)}
    assert server_mode_selected(state) and not server_mode_active(state)


def test_retained_visual_proposals_cannot_bypass_skill_admission(monkeypatch):
    from types import SimpleNamespace
    from wowbot.agent.skills import SkillRegistry
    monkeypatch.setenv("AIPC_SERVER_MODE", "1")
    world = SimpleNamespace(state={"server_mode": status(120., 0)})
    for skill in ("VISUAL_APPROACH", "SEEK_VISUAL_CUE", "INSPECT"):
        proposal = Proposal.make(skill, "retained before sensor outage", {"track_id": "old"})
        assert not SkillRegistry().available(proposal, world)
