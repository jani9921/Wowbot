"""Pure GUI projections; no Tk window, capture, input or live packet source."""
import pytest

from wowbot.agent.gui import dashboard_projection
from wowbot.agent.gui_packet_status import packet_status_text


def state(**packet):
    return {"pid": 77, "mode": "MANUAL", "packet_telemetry": {
        "enabled": True, "status": "listening", "selected_pid": 77,
        "received": 0, "last_received_at": None, **packet}}


@pytest.mark.parametrize("changes,expected", [
    ({"enabled": False}, "kikapcsolva"),
    ({"status": "waiting_for_addon_context"}, "addonkontextusra vár"),
    ({"status": "invalid_addon_context"}, "érvénytelen kontextus"),
    ({"status": "invalid_selected_pid"}, "érvénytelen PID"),
    ({"status": "unsupported_game_build", "observed_game_build": 70392}, "nem támogatott build (70392)"),
    ({"status": "unavailable"}, "fogadóhiba"),
    ({"error": "packet_sensor_failed"}, "fogadóhiba"),
    ({"status": "closed"}, "leállítva"),
    ({"selected_pid": 78}, "PID-eltérés"),
    ({"status": "disabled"}, "indításra vár"),
    ({"status": "source_restart_required", "source_restart_required": True}, "forrás újraindítandó"),
    ({"status": "waiting_for_current_capture_epoch"}, "capture-korszakra vár"),
])
def test_enable_flag_does_not_falsely_claim_active_receiver(changes, expected):
    text = packet_status_text(state(**changes), now=10.)
    assert expected in text and "adat: nincs" in text
    assert "adat: érkezik" not in text


@pytest.mark.parametrize("changes,expected", [
    ({}, "adat: nincs (0)"),
    ({"received": 12, "last_received_at": 9.5}, "adat: érkezik (12)"),
    ({"received": 12, "last_received_at": 8.}, "adat: érkezik (12)"),
    ({"received": 12, "last_received_at": 7.99}, "adat: szünetel (12)"),
    ({"received": 12, "last_received_at": None}, "adat: nincs (12)"),
    ({"received": 12, "last_received_at": 11.}, "adat: nincs (12)"),
    ({"received": 12, "last_received_at": float("nan")}, "adat: nincs (12)"),
    ({"received": -1, "last_received_at": 9.5}, "adat: nincs (0)"),
])
def test_receipt_indicator_ages_even_when_runtime_snapshot_is_not_updated(changes, expected):
    text = packet_status_text(state(**changes), now=10.)
    assert "Packet: aktív" in text and expected in text


def test_no_runtime_and_stopped_runtime_cannot_look_like_active_receipt():
    assert "adat: nincs" in packet_status_text({})
    stopped = state(received=5, last_received_at=9.5)
    stopped["mode"] = "STOPPED"
    assert "leállítva" in packet_status_text(stopped, now=10.)


def test_indicator_is_in_the_existing_top_detector_line_and_does_not_expose_endpoint():
    value = state(received=5, last_received_at=9.5, ipc_key="must-not-render", endpoint="private-path")
    value["loop_rates"] = {"world_detector_hz": 28.}
    result = dashboard_projection(value, model_path="reviewed.engine", now=10.)
    assert "Detektor: 28.0 Hz" in result["control"]
    assert "Packet: aktív | adat: érkezik (5)" in result["control"]
    assert "must-not-render" not in str(result) and "private-path" not in str(result)


def test_socket_receipt_is_not_confused_with_fresh_accepted_semantics():
    value = state(received=300000, last_received_at=9.99, last_accepted_at=5., queued=4096)
    assert "torlódik" in packet_status_text(value, now=10.)
    assert "adat: érkezik" not in packet_status_text(value, now=10.)
    value["packet_telemetry"]["last_accepted_at"] = 9.9
    assert "adat: érkezik" in packet_status_text(value, now=10.)
