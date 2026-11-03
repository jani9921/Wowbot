"""Server-side entity facts (Ymir packets) as planner evidence, read-only.

The server's per-player QuestGiverStatus for a unit GUID is the strongest
quest-marker evidence the agent has: the addon API exposes none
(no-quest-giver-unit-api), and vision cannot tell a grey "?" from a yellow
one or see a "!" behind another NPC.  Live 2026-10-19 14:47:51 the server
reported Henry Garrick with only an in-progress quest left, and the agent
re-opened his window from a remembered offer list and stalled there.

These helpers only read ``state["packet_entities"]`` (WorldPacketReducer).
With Ymir off every call returns None / empty and callers keep their
previous evidence chain unchanged.
"""
from __future__ import annotations

import math
import re

from .models import number
from wowbot.entity_spatial import entity, best_position, travel_position




def quest_marker(state: dict, guid, *, max_age: float | None = None) -> dict | None:
    """The server's latest quest marker for this unit, or None when unknown.

    ``max_age`` keeps only a status sampled after an event that is this many
    seconds old; ages are clock-domain free (packet and addon clocks differ).
    """
    value = entity(state, guid)
    marker = value.get("quest_giver") if value else None
    if not isinstance(marker, dict):
        return None
    age = number(marker.get("age"))
    if age is None or max_age is not None and age > max(0., max_age):
        return None
    return marker


def offers_quest(state: dict, guid, *, max_age: float | None = None) -> bool | None:
    marker = quest_marker(state, guid, max_age=max_age)
    return None if marker is None else bool(marker.get("quest_available"))






def interaction_position(state: dict, guid, *, allow_dead: bool = False) -> dict | None:
    """An existing same-instance server actor's position, never an F7 permit.

    Static create positions remain valid until removed; a new observation
    age alone does not make them disappear. Recipient identity and sample
    freshness are separately checked before the interaction command.
    """
    value = entity(state, guid)
    if (value is None or str(value.get("guid")) != str(guid)
            or value.get("kind") not in {"CREATURE", "VEHICLE", "GAMEOBJECT"}
            or not allow_dead and (value.get("dead", value.get("is_dead")) is True
                or value.get("kind") != "GAMEOBJECT" and _unit_flags(value) & UNIT_LOOTABLE)):
        return None
    point = best_position(value)
    player = state.get("player_world_position") or {}
    if (point is None or point.get("instance_id") is None or player.get("instance_id") is None
            or str(point["instance_id"]) != str(player["instance_id"])
            or not all(number(point.get(axis)) is not None and math.isfinite(number(point[axis]))
                       for axis in ("x", "y", "z"))):
        return None
    return point


# GameObject dynamic flag "Activate" (TrinityCore GO_DYNFLAG_LO_ACTIVATE).
# Live 2026-10-19: Harpy Totems were 0x8200 while quest 55881 was not taken
# (14:42) and 0xc204 while it was active (15:22); 0x4 is the per-player
# "usable for you" bit.
GO_ACTIVATE = 0x4
# GO_DYNFLAG_LO_NO_INTERACT.  Live 2026-10-26 (66048): the Scouting Scope was
# 0x8080 until Talonstalker Kavia's gossip and 0x8000 right after it
# (21:54:17); the user: the object becomes active only after the talk.
GO_NO_INTERACT = 0x80
CREDIT_OBJECT_BASIS = "OBJECTIVE_CREDIT_SPELL"
# These types do not normally consume Interact: generic, trap, spell focus.
# Activate also marks quest scenery (live 66056: generic 383636 and usable
# spellcaster 377013 both named objective 423854). It is not a type override.
PASSIVE_GO_TYPES = frozenset({5, 6, 8})


def game_object_use_candidate(state: dict, value: dict) -> bool:
    """A use-capable server type, or the client's exact fresh F7 recipient.

    Unknown/new types remain eligible; never substitute a TDB entry for the
    current server entry. A positive client recipient can confirm even an
    unusual scripted type, but a shared name/objective/Activate bit cannot.
    """
    if value.get("kind") != "GAMEOBJECT" or value.get("removed"):
        return False
    if (value.get("info") or {}).get("go_type") not in PASSIVE_GO_TYPES:
        return True
    from wowbot.runtime.skill_identity import check_interaction_recipient
    now = number(state.get("monotonic_time"))
    guid = value.get("guid")
    return now is not None and bool(guid) and any(
        isinstance(row, dict) and str(row.get("source_unit") or "").casefold() == "softinteract"
        and str(row.get("guid") or "") == str(guid)
        and check_interaction_recipient({"guid": guid}, state, now)
        for row in state.get("soft_targets") or ())


def go_flags_usable(flags) -> bool:
    """Activate set and NO_INTERACT clear.  Live 2026-10-26 22:46:42: after
    re-accepting 66048 the battle plans went 0xc204 -> 0xc284 (Activate kept,
    NO_INTERACT added) until Fao's gossip; F7 on them failed OUT_OF_RANGE."""
    return type(flags) is int and bool(flags & GO_ACTIVATE) and not flags & GO_NO_INTERACT


def credit_object_entries(state: dict) -> dict[str, str]:
    """{object entry: quest id} of server game objects whose use spell gives
    an unfinished objective's kill credit (TDB/DB2 ``credit_objects``) and
    which the server no longer marks NO_INTERACT."""
    reference = (state.get("reference_knowledge") or {}).get("quests") or {}
    wanted: dict[str, str] = {}
    for quest in state.get("active_quests") or ():
        if not isinstance(quest, dict) or quest.get("is_complete") is True or quest.get("quest_id") is None:
            continue
        qid = str(quest["quest_id"])
        open_text = [str(row.get("description") or "").casefold() for row in quest.get("objectives") or ()
                     if isinstance(row, dict) and row.get("is_complete") is not True]
        for row in (reference.get(qid) or {}).get("objectives") or ():
            description = str((row or {}).get("description") or "").strip().casefold() if isinstance(row, dict) else ""
            if not description or not any(description in text for text in open_text):
                continue  # finished or unnamed objectives ground no use
            for item in [*(row.get("credit_objects") or ()), *(row.get("interaction_objects") or ())]:
                if isinstance(item, dict) and item.get("object_id") is not None:
                    wanted.setdefault(str(item["object_id"]), qid)
    result: dict[str, str] = {}
    if not wanted:
        return result
    for value in (state.get("packet_entities") or {}).values():
        if not isinstance(value, dict) or value.get("kind") != "GAMEOBJECT" or value.get("removed"):
            continue
        quest_id = wanted.get(str(value.get("entry_id")))
        flags = (value.get("dynamic_flags") or {}).get("value")
        if (quest_id and type(flags) is int and not flags & GO_NO_INTERACT
                and game_object_use_candidate(state, value)):
            result[str(value.get("entry_id"))] = quest_id
    return result


def hidden_object_sources(state: dict, quest_id, *, described: bool = False) -> list[tuple[str, str]]:
    """(objective id, game-object entry) of a quest's hidden item rows looted
    from objects.

    Live 2026-10-23 00:21 (Library of Alexstrasza 66000): the only live
    objective was "0/4 Books saved" (a [DNT] kill credit); the TDB's
    description-less item rows come from book chests 376941-376946, and the
    server named each chest's objective (StateWorldEffectsQuestObjectiveID
    427692 ...) with our Activate flag set.  The agent waited 122 yd away.

    ``described`` also returns item rows with a text that only objects yield
    (no creature drops it).  Live 2026-10-25 10:38:19-10:39:06 (Cooking Meat,
    "Cook the meat on the campfire", item 174074 from Campfire 339769): the
    server named the campfire's objective 394179 and set our Activate flag
    the moment the fifth Raw Meat was looted; the agent waited beside it.
    """
    reference = ((state.get("reference_knowledge") or {}).get("quests") or {}).get(str(quest_id)) or {}
    # A blank reference description does not make a visible, already credited
    # item objective hidden work. Live 2026-10-29: completed River Reeds were
    # repeatedly located on behalf of the pending feathers/heart objectives.
    # Truly hidden item rows (e.g. Books saved's chests) stay available.
    from .quest_reference_matching import reference_objectives
    finished = set()
    for quest in state.get('active_quests') or ():
        if not isinstance(quest, dict) or str(quest.get('quest_id')) != str(quest_id):
            continue
        for index, objective in enumerate(quest.get('objectives') or ()):
            if (not isinstance(objective, dict)
                    or (str(objective.get('type') or '').upper() != 'COLLECT'
                        and str(objective.get('raw_type') or '').lower() != 'item')):
                continue
            current, required = number(objective.get('current')), number(objective.get('required'))
            if (objective.get('is_complete') is True
                    or (current is not None and required is not None and 0 < required <= current)):
                finished.update(str(row.get('objective_id')) for row in reference_objectives(
                    quest_id, objective.get('objective_id') or f'{quest_id}:{index}',
                    objective.get('description'), reference.get('objectives')))
    result = []
    for row in reference.get("objectives") or ():
        if (not isinstance(row, dict) or str(row.get("credit_kind") or "").upper() != "ITEM"
                or row.get("objective_id") is None or str(row['objective_id']) in finished):
            continue
        sources = [source for source in row.get("item_sources") or () if isinstance(source, dict)
                   and source.get("relation") == "QUEST_ITEM_ASSOCIATION" and source.get("entry") is not None]
        if str(row.get("description") or "").strip() and (
                not described or any(source.get("kind") != "GAMEOBJECT" for source in sources)):
            continue
        result.extend((str(row["objective_id"]), str(source["entry"]))
                      for source in sources if source.get("kind") == "GAMEOBJECT")
    return result


def objective_objects(state: dict, quest_id) -> list[dict]:
    """Game objects the server shows for this quest's GAMEOBJECT objectives.

    A unit belongs to the quest when its create block names one of the
    quest's objective ids (StateWorldEffectsQuestObjectiveID) or its entry is
    an objective's credit object.  ``usable`` is the server's own per-player
    Activate flag.  Empty when Ymir is off or no such object is in range.
    """
    entities = state.get("packet_entities")
    reference = ((state.get("reference_knowledge") or {}).get("quests") or {}).get(str(quest_id)) or {}
    objective_ids, entries = set(), set()
    # Live 2026-10-26 21:35 (Best Plans and Intentions 66048): the battle
    # plans table names "Fao the Relentless consulted" (427169), a creature-
    # credit objective, in its create block; the agent re-talked to Fao in a
    # loop instead of using it.  The server's own link to any objective of
    # the quest counts (its Activate flag says whether we need it now).
    linked_ids = {str(objective.get("objective_id")) for objective in reference.get("objectives") or ()
                  if isinstance(objective, dict) and objective.get("objective_id") is not None}
    for objective in reference.get("objectives") or ():
        if not isinstance(objective, dict):
            continue
        template = objective.get("object_template") or {}
        entry = objective.get("credit_object_id") or template.get("object_id")
        if objective.get("credit_kind") == "GAMEOBJECT" or template:
            objective_ids.add(str(objective.get("objective_id")))
            if entry is not None:
                entries.add(str(entry))
    for objective_id, entry in hidden_object_sources(state, quest_id, described=True):
        objective_ids.add(objective_id)
        entries.add(entry)
    objective_ids |= linked_ids
    if not isinstance(entities, dict) or not (objective_ids or entries):
        return []
    result = []
    for value in entities.values():
        if not isinstance(value, dict) or value.get("kind") != "GAMEOBJECT" or value.get("removed"):
            continue
        info = value.get("info") or {}
        linked = str(info.get("quest_objective_id")) in objective_ids
        if not linked and str(value.get("entry_id")) not in entries:
            continue
        point = best_position(value)
        flags = (value.get("dynamic_flags") or {}).get("value")
        if point is None:
            continue
        result.append({**point, "guid": value["guid"], "entry_id": value.get("entry_id"),
                       "objective_id": info.get("quest_objective_id"),
                       "usable": go_flags_usable(flags) and game_object_use_candidate(state, value)})
    return result


def game_objects_near(state: dict, x: float, y: float, radius: float) -> list[dict]:
    """Every live game object the server reported within ``radius`` (2D)."""
    entities = state.get("packet_entities")
    result = []
    for value in (entities.values() if isinstance(entities, dict) else ()):
        if not isinstance(value, dict) or value.get("kind") != "GAMEOBJECT" or value.get("removed"):
            continue
        point = best_position(value)
        if point is not None and math.hypot(point["x"]-x, point["y"]-y) <= radius:
            result.append({**point, "guid": value["guid"]})
    return result


def quest_givers(state: dict, *, available: bool = True, reward: bool = False,
                 radius: float | None = None) -> list[tuple[float, dict, dict]]:
    """(distance, entity, WORLD_YARDS point) of units the server marks, nearest first."""
    entities = state.get("packet_entities")
    player = state.get("player_world_position") or {}
    px, py = number(player.get("x")), number(player.get("y"))
    if not isinstance(entities, dict) or px is None or py is None:
        return []
    result = []
    for value in entities.values():
        marker = value.get("quest_giver") if isinstance(value, dict) else None
        if not isinstance(marker, dict) or value.get("removed") or value.get("kind") == "GAMEOBJECT":
            continue
        if not ((available and marker.get("quest_available")) or (reward and marker.get("reward_ready"))):
            continue
        point = best_position(value)
        if point is None or str(point["instance_id"]) != str(player.get("instance_id")):
            continue
        distance = math.hypot(point["x"]-px, point["y"]-py)
        if radius is None or distance <= radius:
            result.append((distance, value, point))
    result.sort(key=lambda row: row[0])
    return result


# Live 2026-10-20 12:57-12:59 (Explorers in Peril, Waking Shores): "Professor
# Cogcatcher rescued" was normalized to KILL; he sat 0.76 yd inside a
# "Protodragon Rib Cage" (GOOBER 379137, lock 2741) the agent hovered but never
# used.  Dynamic flags 0x8000 without Activate: a chair (type 7) shows the same,
# so Activate marks a quest highlight, not usability.  Door, button, chest and
# goober are what the Interact key opens.
INTERACTIVE_GO_TYPES = frozenset({0, 1, 3, 10})
RESCUE_OBJECT_YARDS = 2.5
RESCUE_BASIS = "RESCUE_ADJACENT_OBJECT"
_RESCUE_TEXT = re.compile(r"\b(rescued?|freed?|released?|saved?|liberated?)\b", re.IGNORECASE)
# Live 2026-10-23 01:18-01:19 (A Last Hope, "Pick up the Infused Dragon Egg"):
# the TDB names the egg creature 190090 (credit "Kill Credit: Pick Up Egg
# [DNT]"); it was hunted with Tab (not attackable) while the client's own
# soft-interact recipient was that egg 1.5 yd away.  The user picked it up.
_PICKUP_TEXT = re.compile(
    r"^\s*(?:pick\s+up|pick|collect|gather|grab|take|carry|loot|use|click|open|activate|touch|"
    r"investigate|inspect|examine|retrieve|fetch|place|light|ring|pull|push|read|mount|board)\b",
    re.IGNORECASE)


# Live 2026-10-23 (Skyriding 68795): "Speak to Lord Andestrasz about
# Skyriding" listed his creature entries as kill targets.  A conversation is
# never a kill objective.
_CONVERSATION_TEXT = re.compile(
    r"^\s*(?:speak|talk|ask|meet|report|greet|tell|listen|consult|visit|chat)\b", re.IGNORECASE)


def conversation_objective(row: dict) -> bool:
    return isinstance(row, dict) and bool(_CONVERSATION_TEXT.search(str(row.get("description") or "")))


def pickup_objective(row: dict) -> bool:
    """A creature-credit row whose text says to handle the unit, not kill it."""
    return (isinstance(row, dict) and str(row.get("credit_kind") or "").upper() != "ITEM"
            and bool(_PICKUP_TEXT.search(str(row.get("description") or ""))))


def rescue_credit_entry(row: dict) -> str | None:
    """A concrete creature-credit identity, never a technical credit proxy."""
    name = str(row.get("credit_name") or "").strip()
    entry = number(row.get("credit_object_id"))
    if (str(row.get("credit_kind") or "").upper() in {"CREATURE", "CREATURE_CREDIT"}
            and name and not proxy_credit_name(name) and entry is not None
            and math.isfinite(entry) and entry > 0 and entry.is_integer()):
        return str(int(entry))
    return None


def rescue_actor_entries(row: dict) -> set[str]:
    entries = {str(named["entry"]) for key in ("named_creatures", "credit_creatures")
               for named in row.get(key) or ()
               if isinstance(named, dict) and named.get("entry") is not None}
    credit = rescue_credit_entry(row)
    if credit is not None:
        entries.add(credit)
    return entries


def rescue_objects(state: dict, quest_id=None) -> list[dict]:
    """Interactive game objects holding an NPC that an open objective says to
    rescue/free: the server creature of the objective's named entry, and a
    door/button/chest/goober within ``RESCUE_OBJECT_YARDS`` of it."""
    entities = state.get("packet_entities")
    reference = (state.get("reference_knowledge") or {}).get("quests") or {}
    if not isinstance(entities, dict):
        return []
    values = [value for value in entities.values() if isinstance(value, dict) and not value.get("removed")]
    result = []
    for quest in state.get("active_quests") or ():
        if (not isinstance(quest, dict) or quest.get("is_complete") is True
                or quest_id is not None and str(quest.get("quest_id")) != str(quest_id)):
            continue
        qid = str(quest.get("quest_id"))
        live = [(index, objective) for index, objective in enumerate(quest.get("objectives") or ())
                if isinstance(objective, dict) and objective.get("is_complete") is not True]
        for row in (reference.get(qid) or {}).get("objectives") or ():
            text = str((row or {}).get("description") or "") if isinstance(row, dict) else ""
            if not text or not _RESCUE_TEXT.search(text):
                continue
            match = next(((index, objective) for index, objective in live
                          if text.casefold() in str(objective.get("description") or "").casefold()), None)
            if match is None:
                continue                       # credited, or not this quest's live objective
            index, objective = match
            entries = rescue_actor_entries(row)
            for npc in values:
                if npc.get("kind") not in {"CREATURE", "VEHICLE"} or str(npc.get("entry_id")) not in entries:
                    continue
                held = best_position(npc)
                if held is None:
                    continue
                for value in values:
                    if (value.get("kind") != "GAMEOBJECT"
                            or (value.get("info") or {}).get("go_type") not in INTERACTIVE_GO_TYPES):
                        continue
                    point = best_position(value)
                    if (point is None or math.dist((point["x"], point["y"], point["z"]),
                                                   (held["x"], held["y"], held["z"])) > RESCUE_OBJECT_YARDS):
                        continue
                    result.append({**point, "guid": value["guid"], "entry_id": value.get("entry_id"),
                                   "quest_id": qid,
                                   "objective_id": str(objective.get("objective_id") or f"{qid}:{index}"),
                                   "rescue_npc_guid": npc["guid"], "usable": True})
    return result


def server_object_interactable(state: dict, guid, basis=None) -> bool:
    """The server shows this game object as one the Interact key can use:
    its per-player Activate flag, an objective's credit-spell object no
    longer NO_INTERACT, or -- for a rescue -- an interactive type still
    holding a live rescue NPC."""
    value = entity(state, guid)
    if value is None or not game_object_use_candidate(state, value):
        return False
    flags = (value.get("dynamic_flags") or {}).get("value")
    if go_flags_usable(flags):
        return True
    if basis == CREDIT_OBJECT_BASIS:
        return str(value.get("entry_id")) in credit_object_entries(state)
    return basis == RESCUE_BASIS and any(item["guid"] == value["guid"] for item in rescue_objects(state))


# Kill objectives by server position (user 2026-10-20: "the server sends the
# nearby quest mobs too").  Live 09:04-09:13 (Meredy): every Harpy Ambusher,
# Snatcher, Hunting Worg and Bloodbeak came with exact x,y,z and splines while
# the agent still searched for them on screen.  A killed Harpy Snatcher's unit
# dynamic flags went 0 -> 0x4 (lootable) at 09:08:06 and back to 0 after the
# loot; two worg corpses carried 0x4 from the start.
UNIT_LOOTABLE = 0x4
# An invisible credit proxy ("Kill Credit: Rescue Cogcatcher [DNT]") is no mob.
_PROXY_CREDIT = re.compile(r"\[DNT\]|\bkill credit\b|\bcredit\b|\bbunny\b|\btrigger\b", re.IGNORECASE)


def proxy_credit_name(name) -> bool:
    """A technical credit name is not the identity of a visible actor."""
    return bool(_PROXY_CREDIT.search(str(name or "")))


TAB_SERVER_GUID = "TAB_SERVER_GUID"
TAB_TARGET_YARDS = 20.
TAB_FACING_RADIANS = .35
TAB_CONE_RADIANS = .7
TAB_FLOOR_YARDS = 5.


def _unit_flags(value: dict) -> int:
    flags = (value.get("dynamic_flags") or {}).get("value")
    return flags if type(flags) is int else 0


# UnitData flags (TrinityCore UnitFlags) from the server's unit fields
# (2026-10-27): no player may attack these.
UNIT_NON_ATTACKABLE = 0x2
UNIT_IMMUNE_TO_PC = 0x100
UNIT_NOT_SELECTABLE = 0x2000000


def unit_facts(value: dict) -> dict:
    return (value.get("unit") or {}) if isinstance(value, dict) else {}


def unit_dead(value: dict) -> bool:
    return unit_facts(value).get("health") == 0


UNIT_FLAG2_FEIGN_DEATH = 0x1


def server_feign_death(state: dict, guid) -> bool:
    """The server shows this unit alive (health > 0) but feigning death.

    Live 2026-11-03 08:15 (26257 "It's Alive!"): the inert Overloaded Harvest
    Golem (health 4378/4378, unit_flags2 0x801) read "dead" in the client
    target frame; every item path refused a dead target and the agent stood
    next to it.  Such a unit is a live item subject, not a corpse."""
    value = (state.get("packet_entities") or {}).get(str(guid or "")) if guid else None
    unit = unit_facts(value) if isinstance(value, dict) and not value.get("removed") else {}
    flags, health = unit.get("unit_flags2"), unit.get("health")
    return (type(flags) is int and bool(flags & UNIT_FLAG2_FEIGN_DEATH)
            and type(health) in {int, float} and health > 0)


def unit_unattackable(value: dict) -> bool:
    flags = unit_facts(value).get("unit_flags")
    return type(flags) is int and bool(flags & (UNIT_NON_ATTACKABLE | UNIT_IMMUNE_TO_PC | UNIT_NOT_SELECTABLE))


def attackers(state: dict) -> list[tuple[float, dict]]:
    """Live creatures the server shows targeting us, nearest first (3D with
    our server height).  Live 2026-10-27 16:39:39: the in-combat Tab pin was
    the nearest unit of any kind; Tab took a Boltthrower on another level
    and DEFEND failed OUT_OF_RANGE three times."""
    position = state.get("player_world_position") or {}
    px, py = number(position.get("x")), number(position.get("y"))
    pz = number(position.get("z")) if position.get("z_observed") is True else None
    if px is None or py is None:
        return []
    result = []
    for value in (state.get("packet_entities") or {}).values():
        if (not isinstance(value, dict) or value.get("kind") not in {"CREATURE", "VEHICLE"}
                or value.get("removed") or unit_facts(value).get("targets_me") is not True
                or unit_dead(value) or unit_unattackable(value)):
            continue
        point = best_position(value)
        if point is None or str(point.get("instance_id")) != str(position.get("instance_id")):
            continue
        flat = math.hypot(point["x"]-px, point["y"]-py)
        dz = abs(point["z"]-pz) if pz is not None and point.get("z") is not None else 0.
        result.append((math.hypot(flat, dz), value))
    return sorted(result, key=lambda row: row[0])


def _service_npc(value: dict) -> bool:
    from .server_npc_planning import TALKABLE_NPC_FLAGS
    flags = (value.get("info") or {}).get("npc_flags")
    return type(flags) is int and bool(flags & TALKABLE_NPC_FLAGS)


QUEST_OBJECTIVE_PROGRESS_BAR = 15


def _progress_bar_objective(rows: list[dict], live: list) -> tuple | None:
    """The open live progress bar that a quest's hidden kill rows fill.

    Live 2026-10-22 23:50-23:52 (Fighting Fire with... Water 66998): the only
    live objective was "Erupting Cavern contained (24%)"; the TDB holds that
    bar (type 15) plus description-less creature credits (Erupting Droplet,
    Lasher, Magma).  Every droplet killed in self-defence added 4%, yet none
    was hunted: the hidden rows matched no KILL objective, so the agent waited.
    """
    for row in rows:
        if number(row.get("raw_type")) != QUEST_OBJECTIVE_PROGRESS_BAR:
            continue
        text = str(row.get("description") or "").casefold()
        if not text:
            continue
        for index, objective in live:
            if (str(objective.get("raw_type") or "").lower() == "progressbar"
                    and text in str(objective.get("description") or "").casefold()):
                return index, objective
    return None


NPC_SPELLCLICK = 0x01000000


def collect_creature_sources(state: dict) -> dict[str, list[dict]]:
    """Exact open item-objective -> creature sources, not a kill instruction."""
    from .quest_reference_matching import reference_objectives, objective_text_key
    from wowbot.runtime.entity_identity import template_id
    references = (state.get('reference_knowledge') or {}).get('quests') or {}
    result: dict[str, list[dict]] = {}
    for quest in state.get('active_quests') or ():
        if (not isinstance(quest, dict) or quest.get('is_complete') is True
                or quest.get('is_accepted') is False):
            continue
        qid = str(quest.get('quest_id'))
        items = [(index, objective) for index, objective in enumerate(quest.get('objectives') or ())
                 if isinstance(objective, dict) and (
                     str(objective.get('type') or '').upper() == 'COLLECT'
                     or str(objective.get('raw_type') or '').lower() == 'item')]
        refs = [row for row in (references.get(qid) or {}).get('objectives') or () if isinstance(row, dict)]
        item_rows = [row for row in refs if str(row.get('credit_kind') or '').upper() == 'ITEM']
        # A partial catalog cannot assign its blank row to the first of
        # several visible item counters. Keep completed counters in this
        # alignment too: completing one does not give its source to another.
        orders = [str(row.get('order')) for row in item_rows]
        allow_ordinal = len(orders) == len(items) and set(orders) == {str(index) for index, _ in items}
        for index, objective in items:
            if objective.get('is_complete') is True:
                continue
            current, required = number(objective.get('current')), number(objective.get('required'))
            if current is not None and required is not None and 0 < required <= current:
                continue
            oid = str(objective.get('objective_id') or f'{qid}:{index}')
            rows = reference_objectives(qid, oid, objective.get('description'), refs,
                                        allow_ordinal=allow_ordinal)
            if (not rows and len(items) == len(item_rows) == 1 and oid == f'{qid}:{index}'
                    and not objective_text_key(item_rows[0].get('description'))
                    and not any(str(row.get('objective_id')) == oid for row in refs)):
                # The only visible item and the only blank item row are
                # unambiguous even when the catalog omits its order field.
                rows = item_rows
            if len(rows) != 1 or str(rows[0].get('credit_kind') or '').upper() != 'ITEM':
                continue
            row = rows[0]
            if row.get('credit_action') in {'BUY', 'TALK', 'RIDE', 'SPELLCLICK'}:
                continue  # explicit mechanics keep their existing non-hunt policy
            item_id = template_id(row.get('credit_object_id'))
            if item_id is None:
                continue
            for source in row.get('item_sources') or ():
                if (not isinstance(source, dict) or source.get('kind') != 'CREATURE'
                        or source.get('relation') != 'QUEST_ITEM_ASSOCIATION'):
                    continue
                inherited_item = (source.get('item_id') is None and len(items) == len(item_rows) == 1)
                if template_id(source.get('item_id')) != item_id and not inherited_item:
                    continue
                entry = template_id(source.get('entry'))
                if entry is None:
                    continue
                binding = {'quest_id': qid, 'objective_id': oid, 'item_id': item_id,
                           'reference_objective_id': row.get('objective_id')}
                if inherited_item:
                    # Older reference rows name the item only at the parent.
                    # Preserve that unique hunt hint without upgrading it to
                    # an exact per-source item relation for an interaction.
                    binding['item_id_explicit'] = False
                if binding not in result.setdefault(str(entry), []):
                    result[str(entry)].append(binding)
    return result


def collect_spellclick_units(state: dict) -> dict[str, dict]:
    """Live SPELLCLICK GUIDs linked unambiguously to an unfinished item row."""
    sources = collect_creature_sources(state)
    instance_id = (state.get('player_world_position') or {}).get('instance_id')
    if instance_id is None:
        return {}
    instance = str(instance_id)
    result = {}
    for value in (state.get('packet_entities') or {}).values():
        if (not isinstance(value, dict) or not value.get('guid')
                or value.get('kind') not in {'CREATURE', 'VEHICLE'}
                or value.get('removed') or value.get('dead') is True or value.get('is_dead') is True
                or (value.get('unit') or {}).get('health') == 0
                or str(value.get('map_id')) != instance):
            continue
        bindings = [source for source in sources.get(str(value.get('entry_id')), [])
                    if source.get('item_id_explicit') is not False]
        flags = (value.get('info') or {}).get('npc_flags')
        if len(bindings) == 1 and type(flags) is int and flags & NPC_SPELLCLICK:
            result[str(value['guid'])] = {**bindings[0], 'npc_id': value['entry_id']}
    return result


def kill_objective_relations(state: dict) -> dict[str, tuple[tuple[str, str], ...]]:
    """All open objective relations used by source discovery and combat.

    Several quests can need drops from the same creature. Keep each relation
    so the combat policy can honor the primary objective after selection,
    rather than rediscovering the creature's role from its displayed name.
    These are reference relations, not proof of a live, attackable recipient.
    """
    reference = (state.get("reference_knowledge") or {}).get("quests") or {}
    wanted: dict[str, list[tuple[str, str]]] = {}
    for quest in state.get("active_quests") or ():
        if not isinstance(quest, dict) or quest.get("is_complete") is True:
            continue
        qid = str(quest.get("quest_id"))
        live = [(index, objective) for index, objective in enumerate(quest.get("objectives") or ())
                if isinstance(objective, dict) and objective.get("is_complete") is not True]
        rows = [row for row in (reference.get(qid) or {}).get("objectives") or () if isinstance(row, dict)]
        for row in rows:
            text = str(row.get("description") or "")
            from .quest_semantics import healing_subject
            if (_RESCUE_TEXT.search(text) or healing_subject(row) or pickup_objective(row)
                    or conversation_objective(row)
                    or row.get("item_uses")
                    or row.get("credit_action") in {"TALK", "RIDE", "BUY", "SPELLCLICK"}):
                continue                       # talked to / ridden / clicked / picked up, never killed
            if str(row.get("credit_kind") or "").upper() == "ITEM":
                continue  # all item/source matching uses collect_creature_sources below

            def same_kind(objective):
                return (str(objective.get("type") or "").upper() == "KILL"
                        or str(objective.get("raw_type") or "").lower() == "monster")
            if text:
                match = next(((index, objective) for index, objective in live
                              if text.casefold() in str(objective.get("description") or "").casefold()
                              and same_kind(objective)), None)
            else:
                # A blank creature row can match the only unfinished kill
                # objective when it is the only row of that kind. Item rows
                # use the separate complete-list/identity checks below.
                kind_rows = [other for other in rows
                             if str(other.get("credit_kind") or "").upper() != "ITEM"]
                candidates = [(index, objective) for index, objective in live if same_kind(objective)]
                match = candidates[0] if len(candidates) == 1 and len(kind_rows) == 1 else None
                # Live 2026-10-23 (Training Wings 70061): three description-less
                # rows credit "Agitated Weedling", "Intrusive Pupstinger" and
                # "Relentless Gust"; the live objectives read "0/12 Agitated
                # Weedling slain" ...  The credit's own name binds the row.
                name = str(row.get("credit_name") or "").strip().casefold()
                if match is None and name and not proxy_credit_name(name):
                    named = [(index, objective) for index, objective in candidates
                             if name in str(objective.get("description") or "").casefold()]
                    match = named[0] if len(named) == 1 else None
                if match is None:
                    match = _progress_bar_objective(rows, live)
            if match is None:
                continue
            index, objective = match
            objective_id = str(objective.get("objective_id") or f"{qid}:{index}")
            entries = {str(named.get("entry")) for key in ("named_creatures", "credit_creatures")
                       for named in row.get(key) or ()
                       if isinstance(named, dict) and named.get("entry") is not None}
            if (str(row.get("credit_kind") or "").upper() in {"CREATURE", "CREATURE_CREDIT"}
                    and row.get("credit_object_id") is not None
                    and not proxy_credit_name(row.get("credit_name"))):
                entries.add(str(row["credit_object_id"]))
            for entry in entries:
                relations = wanted.setdefault(entry, [])
                if (qid, objective_id) not in relations:
                    relations.append((qid, objective_id))
    # One item/source resolver serves discovery, interaction and combat.
    # A creature_questitem association alone does not require a kill:
    # a live SPELLCLICK source supplies its item through Interact instead.
    clicked_entries = {str(value.get('entry_id'))
        for value in (state.get('packet_entities') or {}).values()
        if isinstance(value, dict) and not value.get('removed')
        and str(value.get('map_id')) == str((state.get('player_world_position') or {}).get('instance_id'))
        and type((value.get('info') or {}).get('npc_flags')) is int
        and value['info']['npc_flags'] & NPC_SPELLCLICK}
    for entry, sources in collect_creature_sources(state).items():
        relations = wanted.setdefault(entry, [])
        for source in sources:
            relation = (source['quest_id'], source['objective_id'])
            if entry in clicked_entries:
                if relation in relations:
                    relations.remove(relation)
            elif relation not in relations:
                relations.append(relation)
    return {entry: tuple(relations) for entry, relations in wanted.items() if relations}


def kill_objective_entries(state: dict) -> dict[str, tuple[str, str]]:
    """Stable first objective per entry for the existing discovery policies."""
    return {entry: relations[0] for entry, relations in kill_objective_relations(state).items()}


GOSSIP_NPC_FLAG = 0x1


def _attackable_target(state: dict, guid) -> bool:
    """The client's selected unit is this one and is attackable now (the
    sparring partner after its gossip option; user: "gossip opció
    választása, majd támadás")."""
    target = state.get("target") or {}
    return (str(target.get("guid") or "") == str(guid)
            and target.get("attackable", target.get("is_attackable")) is True
            and target.get("dead", target.get("is_dead")) is not True)


def sparring_entries(state: dict) -> dict[str, tuple[str, str]]:
    """{creature entry: (quest id, objective id)} of kill-credit creatures the
    server shows as friendly gossip NPCs: talk first, they fight after it.

    Live 2026-10-26 23:09-23:11 (Sharp Practice 66078, "0/8 Blacktalon
    tested"): the Blacktalon Avengers/Assassins (187187/187189, KillCredit
    187158) stood around with npc_flags 1 ("I'm here to test your combat
    skills.").  The kill hunt skips service NPCs and the talk policy skips
    kill credits, so the agent waited 1.5 yd from one."""
    wanted = kill_objective_entries(state)
    result: dict[str, tuple[str, str]] = {}
    for value in (state.get("packet_entities") or {}).values():
        if (not isinstance(value, dict) or value.get("kind") != "CREATURE" or value.get("removed")
                or str(value.get("entry_id")) not in wanted or _unit_flags(value) & UNIT_LOOTABLE):
            continue
        flags = (value.get("info") or {}).get("npc_flags")
        if type(flags) is int and flags & GOSSIP_NPC_FLAG and not _attackable_target(state, value.get("guid")):
            result[str(value.get("entry_id"))] = wanted[str(value.get("entry_id"))]
    return result


def kill_objective_units(state: dict) -> list[dict]:
    """Live server units to kill for an open objective: the credit entry or
    TDB named creatures of a KILL objective, or the creatures that drop a
    COLLECT objective's quest item -- never a lootable corpse, a service NPC
    or a unit an objective says to rescue.

    Live 2026-10-20 16:46-16:48 (Murloc Mania, "First Aid Kits recovered
    from defeated Murlocs"): the kits drop from murlocs 150228/150229
    (TDB creature_questitem); the KILL-only rule left the agent on hover
    search while the server showed every murloc.
    """
    entities = state.get("packet_entities")
    if not isinstance(entities, dict):
        return []
    wanted = kill_objective_entries(state)
    result = []
    for value in entities.values():
        if (not isinstance(value, dict) or value.get("kind") not in {"CREATURE", "VEHICLE"}
                or value.get("removed") or str(value.get("entry_id")) not in wanted
                or _unit_flags(value) & UNIT_LOOTABLE or unit_dead(value) or unit_unattackable(value)
                or (_service_npc(value) and not _attackable_target(state, value.get("guid")))):
            continue
        point = best_position(value)
        if point is None:
            continue
        qid, objective_id = wanted[str(value.get("entry_id"))]
        result.append({**point, "guid": value["guid"], "entry_id": value.get("entry_id"),
                       "quest_id": qid, "objective_id": objective_id,
                       "targets_me": unit_facts(value).get("targets_me") is True})
    return result


def tab_target_check(state: dict, guid, player_z: float | None = None, *,
                     airborne: bool = False, max_yards: float = TAB_TARGET_YARDS) -> tuple[bool, str]:
    """Would the Tab key (TARGETNEARESTENEMY) select exactly this server unit?

    It must be alive (not a lootable corpse), within Tab range on our level,
    straight ahead, and no other live non-service unit may be as near in the
    frontal cone.  Selection is still verified by its GUID afterwards.
    ``airborne`` (a flying vehicle, 2026-10-26): distances are 3D from the
    known height and no floor rule applies -- the targets lie below.
    """
    value = entity(state, guid)
    if value is None or value.get("kind") not in {"CREATURE", "VEHICLE"}:
        return False, "SERVER_UNIT_GONE"
    if _unit_flags(value) & UNIT_LOOTABLE:
        return False, "SERVER_UNIT_DEAD"
    point = best_position(value)
    position = state.get("player_world_position") or {}
    px, py = number(position.get("x")), number(position.get("y"))
    facing = number(state.get("orientation"))
    if point is None or None in (px, py, facing):
        return False, "NO_POSE"
    if player_z is None and position.get("z_observed") is True:
        player_z = number(position.get("z"))
    def reach(near):
        horizontal = math.hypot(near["x"]-px, near["y"]-py)
        if airborne and player_z is not None and number(near.get("z")) is not None:
            return math.hypot(horizontal, near["z"]-player_z)
        return horizontal
    flat = reach(point)
    if flat > max_yards:
        return False, "OUT_OF_TAB_RANGE"
    if not airborne and player_z is not None and abs(point["z"]-player_z) > TAB_FLOOR_YARDS:
        return False, "OTHER_FLOOR"

    def off_axis(x, y):
        return abs((math.atan2(y-py, x-px)-facing+math.pi) % math.tau - math.pi)

    if math.hypot(point["x"]-px, point["y"]-py) >= 1. and off_axis(point["x"], point["y"]) > TAB_FACING_RADIANS:
        return False, "NOT_FACING"
    for other in (state.get("packet_entities") or {}).values():
        if (not isinstance(other, dict) or other.get("guid") == value["guid"] or other.get("removed")
                or other.get("kind") not in {"CREATURE", "VEHICLE"}
                or _unit_flags(other) & UNIT_LOOTABLE or _service_npc(other)):
            continue
        near = best_position(other)
        if near is None:
            continue
        distance = reach(near)
        if distance <= flat+1. and (distance < 1. or off_axis(near["x"], near["y"]) <= TAB_CONE_RADIANS):
            return False, "OTHER_UNIT_NEARER"
    return True, "SERVER_TAB_NEAREST"


def use_on_target_opener(state: dict, guid) -> bool:
    """The selected unit is opened with Interact (F7) before the fight.

    Live 2026-10-26 (Proto-Fight 66122, "Use the Ruby Harpoon on a
    proto-dragon", the Ruby Spear in the quest log): F7 on a proto-dragon
    fires the harpoon and brings it down; a Charge first said "No path
    available" at the drake in the air.  User: "odamegy, tab, F7, utána
    megtámadja és megöli".  Generic: the unit is a credit creature of a
    quest that carries a quest-log item and a "Use ..." objective."""
    parts = str(guid or "").split("-")
    entry = parts[5] if len(parts) > 6 else ""
    wanted = kill_objective_entries(state).get(entry)
    if not wanted:
        return False
    quest_id = str(wanted[0])
    quest = next((q for q in state.get("active_quests") or ()
                  if isinstance(q, dict) and str(q.get("quest_id")) == quest_id), None)
    if not quest or not (quest.get("special_item") or {}).get("item_id"):
        return False
    rows = (((state.get("reference_knowledge") or {}).get("quests") or {}).get(quest_id) or {}).get("objectives") or ()
    texts = [str(row.get("description") or "") for row in rows if isinstance(row, dict)]
    texts += [str(o.get("description") or "") for o in quest.get("objectives") or () if isinstance(o, dict)]
    return any(text.lstrip("0123456789/ ").lower().startswith("use ") for text in texts)
