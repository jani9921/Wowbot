"""Decode one AIPC pixel-strip payload string into the telemetry state dictionary.

Split out of pixel_bridge.py (2026-10-05); unchanged and re-exported there.
"""
from __future__ import annotations
import time
from typing import Optional


def payload_to_state(payload: str, previous: Optional[dict] = None, client_id: str = "client-1") -> dict:
    fields = payload.split("|")
    if len(fields) < 19 or fields[0] not in ("AIPC1", "AIPC2", "AIPC3", "AIPC4"):
        raise ValueError("invalid AIPC pixel payload")
    payload_version = fields[0]
    state = dict(previous or {})
    state.update({
        "client_id": client_id,
        "protocol_version": payload_version,
        "timestamp": _number(fields[1], time.time()),
        "character_name": _text(fields[2]),
        "map_id": _integer(fields[3]),
        "position": {"x": _number(fields[4], 0) / 100000, "y": _number(fields[5], 0) / 100000, "z": 0},
        "orientation": _number(fields[6], 0) / 1000,
        "health": _integer(fields[7]), "max_health": _integer(fields[8]),
        "power": _integer(fields[9]), "max_power": _integer(fields[10]),
        "is_in_combat": fields[11] == "1", "is_dead": fields[12] == "1", "is_mounted": fields[13] == "1",
        "current_target": _text(fields[14]),
        "nearby_nodes": [], "visible_nodes": [], "known_spells": [],
    })
    if payload_version in ("AIPC3", "AIPC4"):
        state["zone_name"] = _text(fields[15])
        state["subzone_name"] = _text(fields[16])
        state["quest_state_revision"] = _integer(fields[17])
        quest_total = _integer(fields[18]) or 0
        quest_page = _integer(fields[19]) if len(fields) > 19 else -1
        has_quest = len(fields) > 20 and fields[20] == "1"
        cursor = 21
        quest = None
        if has_quest and cursor + 3 < len(fields):
            quest_id = _integer(fields[cursor])
            title = _text(fields[cursor + 1])
            complete = fields[cursor + 2] == "1"
            objective_count = _integer(fields[cursor + 3]) or 0
            cursor += 4
            objectives = []
            for _ in range(objective_count):
                if cursor + 6 >= len(fields):
                    break
                objective = {
                    "type": fields[cursor],
                    "current": _integer(fields[cursor + 1]) or 0,
                    "required": _integer(fields[cursor + 2]) or 1,
                    "description": fields[cursor + 3],
                    "map_id": _integer(fields[cursor + 4]),
                }
                waypoint_x = _number(fields[cursor + 5], 0) / 100000
                waypoint_y = _number(fields[cursor + 6], 0) / 100000
                if waypoint_x or waypoint_y:
                    objective["position"] = {"x": waypoint_x, "y": waypoint_y, "z": 0}
                objectives.append(objective)
                cursor += 7
            quest = {
                "quest_id": quest_id,
                "title": title or "",
                "is_accepted": True,
                "is_complete": complete,
                "objectives": objectives,
            }
        previous_total = int((previous or {}).get("_quest_page_total", -1))
        pages = dict((previous or {}).get("_quest_pages", {})) if previous_total == quest_total else {}
        if quest is not None and quest_page is not None and 0 <= quest_page < quest_total:
            pages[str(quest_page)] = quest
        pages = {key: value for key, value in pages.items() if int(key) < quest_total}
        state["_quest_pages"] = pages
        state["_quest_page_total"] = quest_total
        state["active_quests"] = [pages[str(index)] for index in range(quest_total) if str(index) in pages]
    else:
        quest_id = _integer(fields[15])
        title = _text(fields[16])
        complete = fields[17] == "1"
        objective_count = _integer(fields[18]) or 0
        cursor, objectives = 19, []
        for _ in range(objective_count):
            if cursor + 3 >= len(fields):
                break
            objective = {"type": fields[cursor], "current": _integer(fields[cursor + 1]) or 0,
                         "required": _integer(fields[cursor + 2]) or 1, "description": fields[cursor + 3]}
            cursor += 4
            if payload_version == "AIPC2" and cursor + 2 < len(fields):
                objective["map_id"] = _integer(fields[cursor])
                waypoint_x = _number(fields[cursor + 1], 0) / 100000
                waypoint_y = _number(fields[cursor + 2], 0) / 100000
                if waypoint_x or waypoint_y:
                    objective["position"] = {"x": waypoint_x, "y": waypoint_y, "z": 0}
                cursor += 3
            objectives.append(objective)
        state["active_quests"] = [] if not quest_id else [{
            "quest_id": quest_id,
            "title": title or "",
            "is_accepted": True,
            "is_complete": complete,
            "objectives": objectives,
        }]
    actionbar = []
    if cursor < len(fields):
        action_count = _integer(fields[cursor]) or 0
        cursor += 1
        for _ in range(action_count):
            if cursor + 4 >= len(fields):
                break
            actionbar.append({
                "action": fields[cursor], "kind": fields[cursor + 1], "name": _text(fields[cursor + 2]),
                "spell_id": _integer(fields[cursor + 3]) if fields[cursor + 1] == "spell" else None,
                "item_id": _integer(fields[cursor + 3]) if fields[cursor + 1] == "item" else None,
                "is_usable": fields[cursor + 4] == "1",
            })
            cursor += 5
    state["actionbar"] = actionbar
    state["known_spells"] = [
        {"name": entry["name"], "spell_id": entry["spell_id"], "is_usable": entry["is_usable"]}
        for entry in actionbar if entry["kind"] == "spell" and entry["name"]
    ]
    if payload_version in ("AIPC3", "AIPC4"):
        state["quest_ui_open"] = cursor < len(fields) and fields[cursor] == "1"
        ui_count = _integer(fields[cursor + 1]) if cursor + 1 < len(fields) else 0
        cursor += 2
        ui_entries = []
        for _ in range(ui_count or 0):
            if cursor + 5 >= len(fields):
                break
            ui_entries.append({
                "kind": fields[cursor],
                "quest_id": _integer(fields[cursor + 1]),
                "title": _text(fields[cursor + 2]) or "",
                "x": (_number(fields[cursor + 3], 0) / 10000) or None,
                "y": (_number(fields[cursor + 4], 0) / 10000) or None,
                "is_acceptable": fields[cursor + 5] == "1",
            })
            cursor += 6
        state["quest_ui_entries"] = ui_entries
        if cursor + 3 < len(fields):
            state["quest_ui_action"] = _text(fields[cursor])
            state["quest_ui_x"] = (_number(fields[cursor + 1], 0) / 10000) or None
            state["quest_ui_y"] = (_number(fields[cursor + 2], 0) / 10000) or None
            state["quest_ui_quest_id"] = _integer(fields[cursor + 3])
        else:
            state["quest_ui_action"] = None
            state["quest_ui_x"] = None
            state["quest_ui_y"] = None
            state["quest_ui_quest_id"] = None
        cursor += 4
    elif cursor + 2 < len(fields):
        state["quest_ui_open"] = bool(_text(fields[cursor]))
        state["quest_ui_entries"] = []
        state["quest_ui_action"] = _text(fields[cursor])
        state["quest_ui_x"] = (_number(fields[cursor + 1], 0) / 10000) or None
        state["quest_ui_y"] = (_number(fields[cursor + 2], 0) / 10000) or None
        state["quest_ui_quest_id"] = None
        cursor += 3
    else:
        state["quest_ui_open"] = False
        state["quest_ui_entries"] = []
        state["quest_ui_action"] = None
        state["quest_ui_x"] = None
        state["quest_ui_y"] = None
        state["quest_ui_quest_id"] = None
    if cursor + 1 < len(fields):
        state["target_is_attackable"] = fields[cursor] == "1"
        state["target_is_dead"] = fields[cursor + 1] == "1"
    else:
        state["target_is_attackable"] = None
        state["target_is_dead"] = None
    mouse_cursor = cursor + 2
    state["mouseover"] = None
    if mouse_cursor < len(fields) and fields[mouse_cursor] == "1":
        # AIPC mouseover entity block. The addon only emits this block when
        # WoW currently exposes a real mouseover unit; terrain/objects never
        # become entity identities here.
        if mouse_cursor + 20 < len(fields):
            def _flag(value: str):
                return None if value == "?" else value == "1"
            state["mouseover"] = {
                "name": _text(fields[mouse_cursor + 1]),
                "realm": _text(fields[mouse_cursor + 2]),
                "guid": _text(fields[mouse_cursor + 3]),
                "npc_id": _integer(fields[mouse_cursor + 4]),
                "unit_type": _text(fields[mouse_cursor + 5]),
                "level": _integer(fields[mouse_cursor + 6]),
                "classification": _text(fields[mouse_cursor + 7]),
                "creature_type": _text(fields[mouse_cursor + 8]),
                "creature_family": _text(fields[mouse_cursor + 9]),
                "reaction": _text(fields[mouse_cursor + 10]),
                "reaction_value": _integer(fields[mouse_cursor + 11]),
                "class_name": _text(fields[mouse_cursor + 12]),
                "class_token": _text(fields[mouse_cursor + 13]),
                "is_player": fields[mouse_cursor + 14] == "1",
                "is_dead": fields[mouse_cursor + 15] == "1",
                "is_attackable": _flag(fields[mouse_cursor + 16]),
                "is_tap_denied": _flag(fields[mouse_cursor + 17]),
                "is_connected": _flag(fields[mouse_cursor + 18]),
            }
            wx = _number(fields[mouse_cursor + 19], None)
            wy = _number(fields[mouse_cursor + 20], None)
            wz = _number(fields[mouse_cursor + 21], None) if mouse_cursor + 21 < len(fields) else None
            if wx is not None and wy is not None:
                state["mouseover"]["world_position"] = {"x": wx / 100, "y": wy / 100, "z": (wz or 0) / 100}
        mouse_cursor += 22
    elif mouse_cursor < len(fields):
        # The presence flag is always emitted, including when there is no
        # mouseover unit. Cursor/map fields start immediately after it.
        mouse_cursor += 1
    if mouse_cursor + 1 < len(fields):
        cursor_nx = _number(fields[mouse_cursor], None)
        cursor_ny = _number(fields[mouse_cursor + 1], None)
        if cursor_nx is not None and cursor_ny is not None:
            state["cursor_position"] = {
                "nx": cursor_nx / 100000,
                "ny": cursor_ny / 100000,
            }
        else:
            state["cursor_position"] = None
        mouse_cursor += 2
    else:
        state["cursor_position"] = None
    state["map_mouseover"] = None
    if payload_version == "AIPC4" and mouse_cursor + 10 < len(fields):
        surface = _text(fields[mouse_cursor])
        semantic = _text(fields[mouse_cursor + 1])
        map_id = _integer(fields[mouse_cursor + 2])
        mx = _number(fields[mouse_cursor + 3], None)
        my = _number(fields[mouse_cursor + 4], None)
        lx = _number(fields[mouse_cursor + 5], None)
        ly = _number(fields[mouse_cursor + 6], None)
        tooltip = _text(fields[mouse_cursor + 7])
        unit_name = _text(fields[mouse_cursor + 8])
        unit_npc_id = _integer(fields[mouse_cursor + 9])
        unit_guid = _text(fields[mouse_cursor + 10])
        if surface:
            state["map_mouseover"] = {
                "surface": surface,
                "semantic_type": semantic or "UNKNOWN",
                "map_id": map_id,
                "x": mx / 100000 if mx is not None else None,
                "y": my / 100000 if my is not None else None,
                "local_x": lx / 100000 if lx is not None else None,
                "local_y": ly / 100000 if ly is not None else None,
                "tooltip": tooltip,
                "unit": ({"name": unit_name, "npc_id": unit_npc_id, "guid": unit_guid}
                         if unit_name or unit_npc_id is not None or unit_guid else None),
            }
        mouse_cursor += 11
    state["ui_error"] = _text(fields[mouse_cursor]) if mouse_cursor < len(fields) else None
    state["map_tooltip"] = _text(fields[mouse_cursor + 1]) if mouse_cursor + 1 < len(fields) else None
    state["tutorial_hint"] = _text(fields[mouse_cursor + 2]) if mouse_cursor + 2 < len(fields) else None
    state["dead_corpses"] = []
    corps_cursor = mouse_cursor + 3
    if corps_cursor < len(fields):
        corpse_count = _integer(fields[corps_cursor]) or 0
        corps_cursor += 1
        for _ in range(corpse_count):
            if corps_cursor + 2 >= len(fields):
                break
            cx = _number(fields[corps_cursor], None)
            cy = _number(fields[corps_cursor + 1], None)
            cguid = _text(fields[corps_cursor + 2])
            if cx is not None and cy is not None:
                state["dead_corpses"].append({"x": cx / 100000, "y": cy / 100000, "guid": cguid})
            corps_cursor += 3
    if payload_version == "AIPC4" and corps_cursor + 5 < len(fields):
        state["addon_version"] = _text(fields[corps_cursor])
        state["schema_version"] = _integer(fields[corps_cursor + 1])
        event_sequence = _integer(fields[corps_cursor + 2])
        event_type = _text(fields[corps_cursor + 3])
        event_source = _text(fields[corps_cursor + 4])
        event_timestamp = _number(fields[corps_cursor + 5], None)
        state["latest_event"] = ({
            "sequence": event_sequence,
            "event_type": event_type,
            "source": event_source,
            "timestamp": event_timestamp,
        } if event_type or event_sequence is not None else None)
    state["heartbeat"] = {
        "timestamp": state.get("timestamp"),
        "addon_version": state.get("addon_version"),
        "protocol_version": payload_version,
        "schema_version": state.get("schema_version"),
        "player_present": bool(state.get("character_name")),
        "map_id": state.get("map_id"),
    }
    target = state.get("current_target")
    has_target = target is not None
    if not has_target:
        state["target_is_attackable"] = None
        state["target_is_dead"] = None
    state["visible_units"] = [] if not has_target else [{
        "name": target or "Selected target",
        "is_attackable": state.get("target_is_attackable"),
        "is_interactable": state.get("target_is_attackable") is False,
        "is_dead": state.get("target_is_dead"),
    }]
    state["telemetry_source"] = "retail_pixel_bridge"
    return state


def _text(value: str) -> Optional[str]:
    return None if value in ("", "?") else value


def _integer(value: str) -> Optional[int]:
    try: return int(value)
    except (TypeError, ValueError): return None


def _number(value: str, fallback: float = 0) -> float:
    try: return float(value)
    except (TypeError, ValueError): return fallback
