"""Check launcher configuration without launching GUI, capture or FULL_AI."""
from pathlib import Path
import pytest


@pytest.mark.parametrize("name", ["START_AGENT.bat", "START_AGENT_DXGI.bat", "START_AGENT_LIVE_VISION.bat"])
def test_gui_launchers_enable_passive_packet_receiver_without_arming(name):
    text = (Path(__file__).resolve().parents[1]/name).read_text(encoding="utf-8").lower()
    setting = 'set "aipc_packet_telemetry=1"'
    assert text.index("call config\\local_env.bat") < text.index(setting) < text.index("tools\\run_agent.py --gui")
    commands = [line.strip() for line in text.splitlines() if not line.strip().startswith("rem ")]
    assert not any("wow_auto_start" in line or "run_packet_sidecar" in line or "--full-ai" in line for line in commands)


@pytest.mark.parametrize("name", ["START_AGENT.bat", "START_AGENT_DXGI.bat", "START_AGENT_LIVE_VISION.bat"])
def test_production_gui_launchers_state_the_server_profile(name):
    text = (Path(__file__).resolve().parents[1]/name).read_text(encoding="utf-8").lower()
    assert 'if not defined aipc_runtime_profile set "aipc_runtime_profile=server"' in text
    assert text.index('set "aipc_runtime_profile=server"') < text.index("tools\\run_agent.py --gui")


def test_unattended_start_resolves_the_server_profile_with_packets(monkeypatch):
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from tools.wow_auto_start import agent_environment
    from wowbot.runtime_profile import RuntimeProfile
    for key in ("AIPC_RUNTIME_PROFILE", "AIPC_PACKET_TELEMETRY", "AIPC_SERVER_MODE"):
        monkeypatch.delenv(key, raising=False)
    env = agent_environment()
    assert env["AIPC_RUNTIME_PROFILE"] == "SERVER" and env["AIPC_PACKET_TELEMETRY"] == "1"
    for key, value in env.items():
        if key.startswith("AIPC_"):
            monkeypatch.setenv(key, value)
    assert RuntimeProfile.resolve() is RuntimeProfile.SERVER
    monkeypatch.setenv("AIPC_RUNTIME_PROFILE", "LEGACY_VISION")         # an explicit user choice stays
    assert agent_environment()["AIPC_RUNTIME_PROFILE"] == "LEGACY_VISION"


VISION_DEFAULTS = ("AIPC_LIVE_VISION", "AIPC_WORLD3D_PROPOSAL_MODE", "AIPC_YOLO_PROCESS")


@pytest.mark.parametrize("name", ["START_AGENT.bat", "START_AGENT_DXGI.bat", "START_AGENT_LIVE_VISION.bat"])
def test_server_launchers_set_no_dead_vision_defaults(name):
    # REV4 visual retirement: the SERVER profile builds no vision worker and
    # never read these; the capture (addon pixel strip) stays.
    lines = [line.strip().upper() for line in
             (Path(__file__).resolve().parents[1]/name).read_text(encoding="utf-8").splitlines()
             if not line.strip().lower().startswith("rem ")]
    assert not [line for line in lines if any(f"{key}" in line for key in VISION_DEFAULTS)]
    assert any('"AIPC_CAPTURE_BACKEND=DXGI"' in line for line in lines)


def test_unattended_start_sets_no_vision_defaults(monkeypatch):
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from tools.wow_auto_start import agent_environment
    for key in [k for k in __import__("os").environ if k.startswith(VISION_DEFAULTS)]:
        monkeypatch.delenv(key, raising=False)
    env = agent_environment()
    assert not [key for key in env if key.startswith(VISION_DEFAULTS)]
    assert env["AIPC_CAPTURE_BACKEND"] == "dxgi" and env["AIPC_CAPTURE_PROCESS"] == "1"
