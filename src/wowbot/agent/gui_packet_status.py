"""Bounded, read-only packet indicator. Never confuses enabled with receiving."""
from __future__ import annotations

import math
import time


def packet_status_text(state, *, now=None):
    packet = state.get("packet_telemetry")
    if not isinstance(packet, dict):
        return "Packet: — | adat: nincs"
    if not packet.get("enabled"):
        return "Packet: kikapcsolva | adat: nincs"
    if state.get("mode") == "STOPPED" or packet.get("status") == "closed":
        return "Packet: leállítva | adat: nincs"
    if packet.get("error") or packet.get("status") == "unavailable":
        return "Packet: fogadóhiba | adat: nincs"
    if packet.get("status") == "unsupported_game_build":
        build = packet.get("observed_game_build")
        label = str(build) if type(build) is int else "—"
        return f"Packet: nem támogatott build ({label}) | adat: nincs"
    if packet.get("status") == "waiting_for_addon_context":
        return "Packet: addonkontextusra vár | adat: nincs"
    if packet.get("status") == "invalid_addon_context":
        return "Packet: érvénytelen kontextus | adat: nincs"
    if packet.get("status") == "invalid_selected_pid":
        return "Packet: érvénytelen PID | adat: nincs"
    selected, runtime_pid = packet.get("selected_pid"), state.get("pid")
    if selected is not None and runtime_pid is not None and selected != runtime_pid:
        return "Packet: PID-eltérés | adat: nincs"
    if packet.get('source_restart_required') or packet.get('status') == 'source_restart_required':
        return "Packet: forrás újraindítandó | adat: nincs"
    if packet.get('status') == 'waiting_for_current_capture_epoch':
        return "Packet: capture-korszakra vár | adat: nincs"
    if packet.get("status") != "listening":
        return "Packet: indításra vár | adat: nincs"
    received, last = packet.get("received"), packet.get("last_received_at")
    count = received if type(received) is int and received >= 0 else 0
    if count == 0 or type(last) not in {int, float} or not math.isfinite(last):
        return f"Packet: aktív | adat: nincs ({count})"
    current = time.monotonic() if now is None else now
    age = current-last
    if not math.isfinite(age) or age < 0:
        return f"Packet: aktív | adat: nincs ({count})"
    if "last_accepted_at" in packet:
        accepted = packet.get("last_accepted_at")
        valid_age = current-accepted if type(accepted) in {int, float} and math.isfinite(accepted) else None
        if valid_age is None or not 0 <= valid_age <= 2.:
            label = "torlódik" if packet.get("queued", 0) or packet.get("entity_snapshot_request_pending") else "nincs friss feldolgozott"
            return f"Packet: aktív | adat: {label} ({count})"
    if age > 2.:
        return f"Packet: aktív | adat: szünetel ({count})"
    return f"Packet: aktív | adat: érkezik ({count})"
