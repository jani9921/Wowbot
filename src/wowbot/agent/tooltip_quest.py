"""Which unfinished active quest a unit's own tooltip names (no I/O).

Same rule as the addon's ``quest_related`` (tooltip contains the quest
title).  Live 2026-10-03 09:43: the tooltip read "Prickly Porcupine ~
Level 3 ~ Beast ~ Cooking Meat ~ 1/5 Raw Meat collected from wildlife", yet
``quest_related`` arrived empty.  The tooltip must start with the unit's own
name, so a stale tooltip of another unit is never used.
"""
from __future__ import annotations

import re
import math

from .models import number

_COUNT = re.compile(r"^(\d+)\s*/\s*(\d+)\b")


def tooltip_quest_id(unit: dict, state: dict):
    text = str(unit.get("tooltip") or "")
    name = str(unit.get("name") or "").strip().casefold()
    if not text or not name:
        return None
    parts = [part.strip().casefold() for part in text.split("~")]
    if not parts or parts[0] != name:
        return None
    if tooltip_objectives_done(unit):
        return None
    if (unit.get("attackable", unit.get("is_attackable")) is True
            and not tooltip_open_objectives(unit)):
        # Live 2026-10-03 14:19: tooltips often arrive truncated after the
        # title ("Coastal Goat ~ ... ~ Cooking Meat"); after 5/5 that made a
        # goat "relevant" again.  A creature counts only with an open n/m line.
        return None
    body = " ~ ".join(parts[1:])
    for quest in state.get("active_quests") or ():
        if not isinstance(quest, dict) or quest.get("is_complete") is True:
            continue
        title = str(quest.get("title") or "").strip().casefold()
        if title and title in body:
            return quest.get("quest_id")
    return None


def tooltip_objectives_done(unit: dict) -> bool:
    """Every "n/m" objective line in the unit's tooltip is complete.

    Live 2026-10-03 13:52:47: after 5/5 Raw Meat the goat's tooltip still
    listed "Cooking Meat ~ 5/5 Raw Meat collected from wildlife" (greyed), so
    the title rule (addon ``quest_related`` and ours) kept goats relevant and
    the agent killed three more.  Lines without counts decide nothing.
    """
    counts = []
    for part in str(unit.get("tooltip") or "").split("~"):
        match = _COUNT.match(part.strip())
        if match:
            counts.append((int(match.group(1)), int(match.group(2))))
    return bool(counts) and all(have >= need for have, need in counts)


def objective_key(text) -> str:
    """Objective text without its "n/m" counter, case-folded."""
    return _COUNT.sub("", str(text or "").strip()).strip().casefold()


def tooltip_open_objectives(unit: dict) -> list[str]:
    """Unfinished "n/m" objective lines of the unit's tooltip (keys)."""
    result = []
    for part in str(unit.get("tooltip") or "").split("~"):
        match = _COUNT.match(part.strip())
        if match and int(match.group(1)) < int(match.group(2)):
            result.append(objective_key(part))
    return result


def objective_still_open(state: dict, quest_id, keys) -> bool:
    """The quest is open and (when keys are known) one of them is unfinished."""
    if not keys:
        # Without the objective line the type memory proves nothing.
        return False
    for quest in state.get("active_quests") or ():
        if not isinstance(quest, dict) or str(quest.get("quest_id")) != str(quest_id):
            continue
        if quest.get("is_complete") is True:
            return False
        return any(objective_key(obj.get("description")) in keys
                   and obj.get("is_complete") is not True
                   for obj in quest.get("objectives") or () if isinstance(obj, dict))
    return False


# Objective kinds a creature can never serve (objects, talking, travel).
_NON_CREATURE_OBJECTIVES = {"INTERACT", "USE_OBJECT", "TALK_TO", "INTERACT_NPC", "TRAVEL_TO",
                            "EXPLORE", "RETURN", "REACH_AREA", "EMOTE", "GOSSIP_CHOICE",
                            "SELL", "BUY", "FIELD_TURN_IN", "QUEST_TOOL_BUTTON", "SPECIAL_UI"}


def quest_has_open_creature_objective(state: dict, quest_id) -> bool:
    """The quest still has an unfinished objective a creature can serve."""
    from .quest_model import objective_type
    for quest in state.get("active_quests") or ():
        if not isinstance(quest, dict) or str(quest.get("quest_id")) != str(quest_id):
            continue
        return any(isinstance(obj, dict) and obj.get("is_complete") is not True
                   and objective_type(obj)[0] not in _NON_CREATURE_OBJECTIVES
                   for obj in quest.get("objectives") or ())
    return False


def creature_tooltip_open(unit: dict, state: dict | None = None) -> bool:
    """An open n/m line in the tooltip; without text, the quest log decides.

    Live 2026-10-03 14:23: the FAST lane named a Coastal Goat
    ``quest_related`` for Cooking Meat with no text, after 5/5 Raw Meat --
    only "Cook the meat on the campfire" (an object) was left.
    """
    if str(unit.get("tooltip") or "").strip():
        return bool(tooltip_open_objectives(unit))
    if state is None:
        return True
    return quest_has_open_creature_objective(state, unit.get("quest_id"))


MOUSEOVER_EVENT_STILL_SECONDS = .8
MOUSEOVER_EVENT_MAX_STILL_SECONDS = 3.
MOUSEOVER_EVENT_MAX_AGE_SECONDS = 3.


def cursor_view(state: dict) -> dict:
    """Screen geometry at a hover: cursor coordinates alone do not anchor it."""
    position = state.get("player_world_position") or {}
    return {"orientation": number(state.get("orientation")),
            "camera_yaw": number(state.get("camera_yaw_estimate")),
            "player_x": number(position.get("x")),
            "player_y": number(position.get("y"))}


def same_cursor_view(origin: dict | None, state: dict, *, check_camera: bool = True) -> bool:
    """A prior hover cannot identify a pixel after the view/player has moved."""
    current = cursor_view(state)
    if not isinstance(origin, dict):
        return not any(value is not None for value in current.values())
    old, new = origin.get("orientation"), current["orientation"]
    if old is not None and new is not None:
        angular = abs((new-old+math.pi) % (2*math.pi)-math.pi)
        if angular > .07:
            return False
    old, new = origin.get("camera_yaw"), current["camera_yaw"]
    if check_camera and old is not None and new is not None and abs(new-old) > 18.:
        return False
    if all(origin.get(key) is not None and current[key] is not None
           for key in ("player_x", "player_y")):
        if math.hypot(current["player_x"]-origin["player_x"],
                      current["player_y"]-origin["player_y"]) > .5:
            return False
    return True


def effective_mouseover(state: dict, memory: dict | None = None) -> dict:
    """The live mouseover, with a world object's name from its change event.

    Live 2026-10-03 14:16: hovering the quest Campfire, the FAST mouseover was
    only ``{"quest_related": true, "quest_id": 55174}`` (no unit, no text) and
    the slow lane had no mouseover text either; the name came only in the
    ``MOUSEOVER_CHANGED`` event ("Campfire ~ Cooking Meat ~ 0/1 Cook the meat
    on the campfire").  The newest such event names what is under the cursor
    until the next change, so it is merged in only while the live sample
    still reports a quest-related non-unit of the same quest.
    """
    mouse = dict(state.get("mouseover") or {})
    if mouse.get("tooltip") or mouse.get("guid") or mouse.get("name"):
        return mouse
    object_memory = memory if memory is not None else state.get("mouseover_object_memory")
    remembered = _remembered_object(state, mouse, object_memory)
    if remembered is not None:
        return remembered
    # A tracked event was considered and rejected.  The live FAST quest flag
    # may still confirm the object during the first <.8 s of cursor dwell,
    # before the remembered-event rule matures (Campfire replay).  But a view
    # change/aged event must never be resurrected by the loose fallback.
    if object_memory is not None:
        now = number(state.get("monotonic_time"))
        ingested = number(object_memory.get("ingested_at"))
        cursor = state.get("cursor_position") or {}
        ex, ey = (object_memory.get("event_cursor") or (None, None))
        x, y = number(cursor.get("nx")), number(cursor.get("ny"))
        if (mouse.get("quest_related") is not True
                or not same_cursor_view(object_memory.get("cursor_view"), state)
                or (number(object_memory.get("still_for")) or 0.) > MOUSEOVER_EVENT_MAX_STILL_SECONDS
                or None in (x, y, ex, ey) or abs(x-ex) > .004 or abs(y-ey) > .004
                or (now is not None and ingested is not None
                    and not -.5 <= now-ingested <= MOUSEOVER_EVENT_MAX_AGE_SECONDS)):
            return mouse
    if mouse.get("quest_related") is not True:
        return mouse
    events = [event for event in state.get("events") or ()
              if isinstance(event, dict) and event.get("event_type") == "MOUSEOVER_CHANGED"]
    if not events:
        return mouse
    latest = max(events, key=lambda event: float(event.get("sequence") or -1))
    payload = latest.get("payload") or {}
    metadata = payload.get("tooltip_data") or {}
    if (payload.get("guid") or metadata.get("guid") or metadata.get("unit_guid")
            or not payload.get("tooltip")
            or str(payload.get("quest_id")) != str(mouse.get("quest_id"))):
        return mouse
    return {**mouse, "tooltip": payload["tooltip"],
            "name": metadata.get("unit_name") or str(payload["tooltip"]).split(" ~ ", 1)[0],
            "object_id": payload.get("object_id"),
            "identity_source": "MOUSEOVER_CHANGED_EVENT"}


def _remembered_object(state: dict, mouse: dict, memory: dict | None) -> dict | None:
    """The object named by the newest change event while the cursor is still.

    The change event arrives late (slow lane); it is attributed to the cursor
    position only when the cursor had already been still for a moment when
    the event was ingested and has not moved since.
    """
    if not memory or not isinstance(memory.get("payload"), dict):
        return None
    payload = memory["payload"]
    metadata = payload.get("tooltip_data") or {}
    tooltip = str(payload.get("tooltip") or "")
    continuity = memory.get("live_continuity") or {}
    cursor = state.get("cursor_position") or {}
    x, y = number(cursor.get("nx")), number(cursor.get("ny"))
    now = number(state.get("monotonic_time"))
    live = (mouse.get("quest_related") is True
            and str(mouse.get("quest_id")) == str(payload.get("quest_id"))
            and continuity.get("sequence") == memory.get("sequence")
            and str(continuity.get("quest_id")) == str(mouse.get("quest_id"))
            and now is not None and number(continuity.get("at")) is not None
            and -.5 <= now-float(continuity["at"]) <= 1.5)
    if (live and tooltip and not payload.get("guid") and not metadata.get("guid")
            and not metadata.get("unit_guid") and None not in (x, y)
            and continuity.get("cursor") is not None
            and abs(x-continuity["cursor"][0]) <= .004
            and abs(y-continuity["cursor"][1]) <= .004):
        return {**mouse, "tooltip": tooltip,
                "name": metadata.get("unit_name") or tooltip.split(" ~ ", 1)[0],
                "object_id": payload.get("object_id"),
                "identity_source": "CONTINUOUS_LIVE_QUEST_OBJECT_MOUSEOVER"}
    now, ingested_at = number(state.get("monotonic_time")), number(memory.get("ingested_at"))
    still_for = number(memory.get("still_for")) or 0.
    if (not tooltip or payload.get("guid") or metadata.get("guid") or metadata.get("unit_guid")
            or not MOUSEOVER_EVENT_STILL_SECONDS <= still_for <= MOUSEOVER_EVENT_MAX_STILL_SECONDS
            or (now is not None and ingested_at is not None
                and not -.5 <= now-ingested_at <= MOUSEOVER_EVENT_MAX_AGE_SECONDS)
            or not same_cursor_view(memory.get("cursor_view"), state)
            or memory.get("event_cursor") is None or memory.get("cursor") != memory.get("event_cursor")):
        return None
    if mouse.get("quest_id") is not None and str(mouse.get("quest_id")) != str(payload.get("quest_id")):
        return None
    cursor = state.get("cursor_position") or {}
    try:
        x, y = float(cursor["nx"]), float(cursor["ny"])
    except (KeyError, TypeError, ValueError):
        return None
    ex, ey = memory["event_cursor"]
    if abs(x-ex) > .004 or abs(y-ey) > .004:
        return None
    return {**mouse, "tooltip": tooltip,
            "name": metadata.get("unit_name") or tooltip.split(" ~ ", 1)[0],
            "object_id": payload.get("object_id"),
            "quest_related": payload.get("quest_related"), "quest_id": payload.get("quest_id"),
            "identity_source": "MOUSEOVER_CHANGED_EVENT_AT_STILL_CURSOR"}
