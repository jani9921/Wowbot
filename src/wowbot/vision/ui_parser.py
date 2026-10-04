"""Frame-stamped UI-state normalization for the Retail addon telemetry path."""
from __future__ import annotations

from typing import Any


def _dialog_open(payload: dict[str, Any], name: str) -> bool:
    value = payload.get(name)
    return bool(value.get("open")) if isinstance(value, dict) else bool(payload.get(f"{name}_open"))


def parse_ui_observations(payload: dict[str, Any], *, frame_id: str, observed_at: float) -> list[dict[str, Any]]:
    """Return source-labelled UI observations, never an action or success claim."""
    target = payload.get("target") or {}
    player_present = payload.get("player_present") is True or bool(payload.get("character_guid"))
    observations: list[tuple[str, bool, float, dict[str, Any]]] = [
        ("PLAYER_FRAME", player_present, 1. if player_present else 0., {
            "health": payload.get("health"), "max_health": payload.get("max_health"),
            "power": payload.get("power"), "max_power": payload.get("max_power")}),
        ("TARGET_FRAME", bool(target), .95 if target.get("guid") else .6 if target else 0., {
            "guid": target.get("guid"), "name": target.get("name"),
            "health": target.get("health"), "dead": target.get("dead", target.get("is_dead"))}),
        ("CAST_BAR", bool(payload.get("is_casting") or payload.get("cast")), .9 if payload.get("is_casting") else .0, {
            "casting": bool(payload.get("is_casting")), "cast": payload.get("cast")}),
        ("QUEST_DIALOG", _dialog_open(payload, "quest_ui"), .98 if _dialog_open(payload, "quest_ui") else 0.,
         {"action": (payload.get("quest_ui") or {}).get("action") if isinstance(payload.get("quest_ui"), dict) else payload.get("quest_ui_action")}),
        ("GOSSIP", _dialog_open(payload, "gossip_ui"), .98 if _dialog_open(payload, "gossip_ui") else 0., {}),
        ("MERCHANT", _dialog_open(payload, "vendor_ui"), .98 if _dialog_open(payload, "vendor_ui") else 0., {}),
        ("LOOT", bool(payload.get("loot_open") or payload.get("loot_pending")), .9 if payload.get("loot_open") else .55 if payload.get("loot_pending") else 0., {}),
        ("QUEST_TRACKER", bool(payload.get("active_quests")), .9 if payload.get("active_quests") else 0.,
         {"quest_count": len(payload.get("active_quests") or [])}),
        ("ERROR_STATE", bool(payload.get("ui_error") or payload.get("error_message")), .9 if payload.get("ui_error") or payload.get("error_message") else 0.,
         {"text": payload.get("ui_error") or payload.get("error_message")}),
        ("LOADING_SCREEN", bool(payload.get("loading")), 1. if payload.get("loading") else 0., {}),
    ]
    return [{"ui_element": name, "state": "VISIBLE" if visible else "ABSENT",
             "confidence": confidence, "frame_id": str(frame_id),
             "timestamp_monotonic": float(observed_at), "source": "ADDON_UI_TELEMETRY",
             "details": details, "fact": False}
            for name, visible, confidence, details in observations]
