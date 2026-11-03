from pathlib import Path

from wowbot.packetio.ymir_bridge import (
    EXPECTED_BUILD,
    YmirAgentBridge,
    parse_console_line,
)


def test_ymir_console_identity_and_dump_are_parsed():
    assert parse_console_line("Allowed build: 12.1.5.70575") == (
        "allowed_build", EXPECTED_BUILD)
    assert parse_console_line("Automatically selected process: 'Wow' (PID: 13664)") == (
        "selected_pid", 13664)
    assert parse_console_line("Writing dump to dumps/dump_12.1.0.70448_foo.pkt") == (
        "dump_path", "dumps/dump_12.1.0.70448_foo.pkt")


def test_ymir_bridge_refuses_unpinned_binary_before_process_start(tmp_path):
    executable = tmp_path / "ymir.exe"
    executable.write_bytes(b"not-the-reviewed-binary")
    bridge = YmirAgentBridge(
        executable=executable,
        selected_pid=13664,
        endpoint_path=tmp_path / "packet_endpoint.json",
        output=tmp_path / "packet-telemetry")

    assert bridge.run() == 2
    status = bridge.snapshot()
    assert status["state"] == "ERROR"
    assert "SHA-256 mismatch" in status["error"]
    assert bridge.process is None


def test_ymir_bridge_requires_positive_authoritative_pid(tmp_path):
    bridge = YmirAgentBridge(
        executable=Path(tmp_path / "missing.exe"),
        selected_pid=0,
        endpoint_path=tmp_path / "packet_endpoint.json",
        output=tmp_path / "packet-telemetry")

    assert bridge.run() == 2
    assert "positive selected PID required" in bridge.snapshot()["error"]


def test_prelaunched_ymir_can_bind_later_to_the_detected_pid(tmp_path):
    bridge = YmirAgentBridge(
        executable=tmp_path / "ymir.exe",
        output=tmp_path / "packet-telemetry")
    bridge._set(detected_pid=13664, pid_verified=True, build_verified=True)

    bridge.bind(selected_pid=13664, endpoint_path=tmp_path / "packet_endpoint.json")

    assert bridge.snapshot()["requested_pid"] == 13664
    assert bridge.endpoint_path == (tmp_path / "packet_endpoint.json").resolve()


def test_prelaunched_ymir_rejects_a_different_gui_pid(tmp_path):
    bridge = YmirAgentBridge(
        executable=tmp_path / "ymir.exe",
        output=tmp_path / "packet-telemetry")
    bridge._set(detected_pid=13664, pid_verified=True, build_verified=True)

    try:
        bridge.bind(selected_pid=4242, endpoint_path=tmp_path / "packet_endpoint.json")
    except RuntimeError as error:
        assert "detected PID 13664" in str(error)
    else:
        raise AssertionError("different authoritative PID must be rejected")
