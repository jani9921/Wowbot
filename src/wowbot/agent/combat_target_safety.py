"""Read-only elite engagement guard; a selected enemy is not an attacker."""
from .models import number
from wowbot.packetio.context import addon_entity_guid, same_player


def _public_guid(value):
    return addon_entity_guid(value) or value


def combat_target_allowed(state: dict, unit: dict, *, explicit_objective=False) -> bool:
    guid = unit.get("guid")
    events = sorted((e for e in state.get("events") or () if isinstance(e, dict)),
                    key=lambda e: (number(e.get("timestamp")) or 0., number(e.get("sequence")) or 0.))
    classification = unit.get("classification")
    if not classification and guid:
        for event in reversed(events):
            payload = event.get("payload") or {}
            if (event.get("event_type") in {"TARGET_CHANGED", "MOUSEOVER_CHANGED"}
                    and payload.get("guid") == guid and payload.get("classification")):
                classification = payload["classification"]
                break
    if str(classification or "").casefold() not in {"elite", "rareelite", "worldboss"}:
        return True  # retain ordinary multi-attacker defence, without inventing threat data
    if explicit_objective:
        return True
    if not state.get("is_in_combat") or not guid:
        return False
    player = state.get("character_guid")
    if not player:
        return False
    if unit.get("is_attacking_player") is True or unit.get("target_guid") == player:
        return True
    now, wall = number(state.get("monotonic_time")), number(state.get("timestamp"))
    for event in reversed(events):
        kind, payload = event.get("event_type"), event.get("payload") or {}
        if kind == "COMBAT_ENDED":
            return False
        if kind not in {"COMBAT_STARTED", "ATTACK_STOPPED"}:
            continue
        if (_public_guid(payload.get("attacker_guid")) != guid
                or not (payload.get("victim_guid") == player or same_player(payload.get("victim_guid"), player))):
            continue
        sampled = number(payload.get("packet_observed_at"))
        stamp = number(event.get("timestamp"))
        age = now-sampled if now is not None and sampled is not None else wall-stamp if wall is not None and stamp is not None else None
        return kind == "COMBAT_STARTED" and age is not None and 0 <= age <= 30.
    return False
