"""Which unfinished active quest a unit's own tooltip names (no I/O).

Same rule as the addon's ``quest_related`` (tooltip contains the quest
title).  Live 2026-10-03 09:43: the tooltip read "Prickly Porcupine ~
Level 3 ~ Beast ~ Cooking Meat ~ 1/5 Raw Meat collected from wildlife", yet
``quest_related`` arrived empty.  The tooltip must start with the unit's own
name, so a stale tooltip of another unit is never used.
"""
from __future__ import annotations

import re

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
    if mouse.get("tooltip") or mouse.get("guid"):
        return mouse
    remembered = _remembered_object(
        state, mouse, memory if memory is not None else state.get("mouseover_object_memory"))
    if remembered is not None:
        return remembered
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
    if (not tooltip or payload.get("guid") or metadata.get("guid") or metadata.get("unit_guid")
            or float(memory.get("still_for") or 0.) < MOUSEOVER_EVENT_STILL_SECONDS
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
