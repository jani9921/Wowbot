"""Walk to an objective NPC at its server position, face it, press Interact.

User 2026-10-20: "the server gives NPC x,y,z -- use it to go right up to the
NPC, then right-click or F7".  Live 08:47-08:49 the cursor rested on Meredy
Huntswell (The Rescue of Meredy Huntswell, a KILL objective started by
talking to her) and the agent never approached or spoke to her.

An NPC qualifies when a TDB objective of an open, unfinished quest names its
creature entry and its create block says it can be talked to (Gossip or
QuestGiver NPC flag).  The approach is an ordinary navmesh MOVE to its exact
server point with face_on_arrival; the press is the existing SOFT_INTERACT
INTERACT, so the client's soft-interact unit must be exactly that GUID.  It
only reads ``state["packet_entities"]``; with Ymir off it proposes nothing.
"""
from __future__ import annotations

import math
import re

from wowbot.query_ports import TravelCostPort
from .models import Proposal, number
from .packet_entity_facts import (CREDIT_OBJECT_BASIS, best_position, credit_object_entries, go_flags_usable,
                                  game_object_use_candidate,
                                  proxy_credit_name, sparring_entries, collect_spellclick_units)

# Units Interact opens a window on: Gossip, QuestGiver, Trainer, Vendor (and
# its food/ammo/poison/reagent kinds), Repair, Flight master, Innkeeper,
# Banker, Stable master.  Live 2026-10-20 10:09-10:11 (Repair Yourself, "Speak
# With Quartermaster Richter"): the server flags of Richter were 0x1280
# (vendor + food vendor + repair, no gossip), so he was never walked up to.
TALKABLE_NPC_FLAGS = (0x1 | 0x2 | 0x10 | 0x80 | 0x100 | 0x200 | 0x400 | 0x800 | 0x1000
                      | 0x2000 | 0x10000 | 0x20000 | 0x400000)
SEARCH_YARDS = 80.
GIVER_YARDS = 30.              # server "!"/"?" units not named by an objective
INTERACT_YARDS = 4.
# Live 2026-10-25 10:47:02-10:47:32 (Scout-o-Matic 5000): the hovering
# vehicle was the client's soft-interact unit 2.2 yd away but 4.8 yd above
# (5.3 yd), so the 4 yd gate never pressed F7 and the agent re-walked to its
# spot six times.  The client's own F7 recipient being exactly this unit is
# the proof of reach; the bound only rejects a far/stale server point.
SOFT_RECIPIENT_YARDS = 6.5
FACING_RADIANS = .45
RETRY_SECONDS = 45.            # after its window actually opened
PRESS_SECONDS = 4.             # one press per attempt


def server_npc_distance(state: dict, point: dict) -> float | None:
    player = state.get("player_world_position") or {}
    px, py = number(player.get("x")), number(player.get("y"))
    x, y = number(point.get("x")), number(point.get("y"))
    if (None in (px, py, x, y)
            or str(player.get("instance_id")) != str(point.get("instance_id"))):
        return None
    distance = math.hypot(x-px, y-py)
    if player.get("z_observed") is True or player.get("z_known") is True:
        pz, z = number(player.get("z")), number(point.get("z"))
        if pz is not None and z is not None:
            distance = math.hypot(distance, z-pz)
    return distance


def server_npc_interaction_ready(state: dict, guid: str, point: dict) -> bool:
    """Exact server position plus the fresh public recipient of the F7 key."""
    from wowbot.runtime.skill_identity import check_interaction_recipient
    player = state.get("player_world_position") or {}
    px, py = number(player.get("x")), number(player.get("y"))
    x, y = number(point.get("x")), number(point.get("y"))
    now, facing = number(state.get("monotonic_time")), number(state.get("orientation"))
    if (None in (px, py, x, y, now)
            or str(player.get("instance_id")) != str(point.get("instance_id"))):
        return False
    distance = server_npc_distance(state, point)
    if distance is None or distance > INTERACT_YARDS:
        return False
    if distance >= 1. and (facing is None or abs(
            (math.atan2(y-py, x-px)-facing+math.pi) % math.tau - math.pi) > FACING_RADIANS):
        return False
    # Require an explicit soft recipient here: this route intentionally does
    # not hard-target/hover a visual box before interacting with the ender.
    soft = next((row for row in state.get("soft_targets") or ()
                 if isinstance(row, dict) and str(row.get("source_unit") or "").casefold() == "softinteract"), None)
    return bool(soft is not None
                and soft.get("is_attackable", soft.get("attackable")) is not True
                and soft.get("is_dead", soft.get("dead")) is not True
                and check_interaction_recipient({"guid": guid}, state, now))


def objective_npc_entries(state: dict, *,
                          travel_cost: TravelCostPort | None = None) -> dict[str, str]:
    """{creature entry: quest id} named by unfinished objectives of open quests."""
    reference = (state.get("reference_knowledge") or {}).get("quests") or {}
    result: dict[str, str] = {}
    for quest in state.get("active_quests") or ():
        if not isinstance(quest, dict) or quest.get("is_complete") is True:
            continue
        open_objectives = [objective for objective in quest.get("objectives") or ()
                           if isinstance(objective, dict) and objective.get("is_complete") is not True]
        if not open_objectives:
            continue
        quest_id = str(quest.get("quest_id"))
        from .conversation_actors import conversation_actors
        for actor in conversation_actors(state, quest_id, travel_cost=travel_cost):
            result.setdefault(str(actor["entry"]), quest_id)
        for row in (reference.get(quest_id) or {}).get("objectives") or ():
            if not isinstance(row, dict):
                continue
            description = str(row.get("description") or "").strip().casefold()
            if description and not any(description in str(
                    objective.get("description") or "").casefold() for objective in open_objectives):
                continue  # future/completed objective actors are not current work
            if row.get("credit_action") in {"BUY", "TALK"} and not description:
                continue  # no open objective can ground this purchase/conversation

            def nominate(entry):
                # A name-derived TDB relation cannot repair a contradictory
                # numeric/GUID binding of the current objective.
                from wowbot.runtime.entity_identity import check_entity_identity, identity_fields
                related = [o for o in open_objectives if not description or description in str(
                           o.get("description") or "").casefold()]
                bindings = [identity_fields(o.get("target_entity") or {}) for o in related]
                if any(not binding for binding in bindings):
                    result.setdefault(str(entry), quest_id)
                    return
                observed = [{"npc_id": entry}, *({"npc_id": entry, "guid": value.get("guid")}
                            for value in (state.get("packet_entities") or {}).values()
                            if str(value.get("entry_id")) == str(entry) and not value.get("removed"))]
                if any(check_entity_identity(binding, unit) for binding in bindings for unit in observed):
                    result.setdefault(str(entry), quest_id)

            # "Kill Credit: Talk to Sendrax [DNT]" (live 2026-10-21 16:13).
            if str(row.get('credit_kind') or '').upper() == 'TALK_CREDIT':
                # Type 3 directly names the unit to talk to, even without a
                # creature name/list (live 72429: Agari Dotur and the vendor).
                from .quest_reference_matching import reference_objectives
                from wowbot.runtime.entity_identity import template_id
                matched = any(row in reference_objectives(
                    quest_id, objective.get('objective_id') or f'{quest_id}:{index}',
                    objective.get('description'), (reference.get(quest_id) or {}).get('objectives'))
                    for index, objective in enumerate(quest.get('objectives') or ())
                    if isinstance(objective, dict) and objective.get('is_complete') is not True)
                entry = template_id(row.get('credit_object_id'))
                if matched and entry is not None and quest.get('is_accepted') is not False:
                    nominate(entry)
                continue
            for named in row.get("talk_creatures") or ():
                if isinstance(named, dict) and named.get("entry") is not None:
                    nominate(named["entry"])
            for named in row.get("named_creatures") or ():
                if isinstance(named, dict) and named.get("entry") is not None:
                    nominate(named["entry"])
            if (row.get("credit_action") not in {"BUY", "TALK", "RIDE"}
                    and not proxy_credit_name(row.get("credit_name"))
                    and str(row.get("credit_kind") or "").upper() in {"CREATURE", "CREATURE_CREDIT", "TALK"}):
                if row.get("credit_object_id") is not None:
                    nominate(row["credit_object_id"])
    return result


def objective_npc_available(state: dict, quest_id, *, since: float | None = None,
                            travel_cost: TravelCostPort | None = None) -> str | None:
    """GUID of a server-known, talkable objective NPC of this quest in reach,
    created after ``since`` (an NPC known at planning time had its chance:
    a talked-to one must not cancel every later search walk).

    Live 2026-10-28 10:53:42-10:54:53 (Claimant to the Throne 66780, "Speak
    with Left and Right"): the only plan was a TDB-POI walk, chosen 1.7 s
    before the server sent Left and Right 12 yd away; the walk was never
    replanned and spun 70 s on a waypoint of a lower floor."""
    entries = {entry for entry, quest in objective_npc_entries(
        state, travel_cost=travel_cost).items() if quest == str(quest_id)}
    item_clicks = {guid: binding for guid, binding in collect_spellclick_units(state).items()
                   if binding['quest_id'] == str(quest_id)}
    entries.update(str(binding['npc_id']) for binding in item_clicks.values())
    if not entries:
        return None
    instance = str((state.get("player_world_position") or {}).get("instance_id"))
    for value in (state.get("packet_entities") or {}).values():
        if (not isinstance(value, dict) or value.get("kind") not in {"CREATURE", "VEHICLE"}
                or value.get("removed") or str(value.get("entry_id")) not in entries):
            continue
        info = value.get("info") or {}
        flags, created = info.get("npc_flags"), number(info.get("sampled_at"))
        point = best_position(value)
        if (type(flags) is not int
                or not (flags & TALKABLE_NPC_FLAGS or str(value.get('guid')) in item_clicks) or point is None
                or (since is not None and (created is None or created < since))):
            continue
        distance = server_npc_distance(state, point) if str(point.get("instance_id")) == instance else None
        if distance is not None and distance <= SEARCH_YARDS:
            return str(value["guid"])
    return None


def ride_entries(state: dict) -> dict[str, str]:
    """{creature entry: quest id} of vehicles an open objective says to ride.

    Live 2026-10-21 16:14 ("Hop on the Surveyor's Disc", credit "Ride
    Vehicle"): the disc came with no NPC flags; it was hunted as a kill and
    Tab never selected it.  Interact (its spellclick) seats the player.
    """
    reference = (state.get("reference_knowledge") or {}).get("quests") or {}
    from .objective_transport import transport_entries
    result: dict[str, str] = transport_entries(state)
    for quest in state.get("active_quests") or ():
        if not isinstance(quest, dict) or quest.get("is_complete") is True:
            continue
        if not any(isinstance(objective, dict) and objective.get("is_complete") is not True
                   for objective in quest.get("objectives") or ()):
            continue
        quest_id = str(quest.get("quest_id"))
        for row in (reference.get(quest_id) or {}).get("objectives") or ():
            if isinstance(row, dict) and row.get("credit_action") == "RIDE":
                for named in row.get("named_creatures") or ():
                    if isinstance(named, dict) and named.get("entry") is not None:
                        result.setdefault(str(named["entry"]), quest_id)
    return result


def spellclick_entries(state: dict) -> dict[str, str]:
    """{creature entry: quest id} of units an open objective credits through
    Interact on the unit itself (TDB npc_spellclick_spells, ``SPELLCLICK``).

    Live 2026-10-25 (Exile's Reach): "First Aid Kit used on Kee-La" (and on
    Bjorn and Austin), "Use Scout-o-Matic 5000" and "Ride the Giant Boar"
    were hunted with Tab, which never selects a friendly unit; the user had
    to target them.  Standing at the unit and pressing F7 does it."""
    reference = (state.get("reference_knowledge") or {}).get("quests") or {}
    result: dict[str, str] = {}
    for quest in state.get("active_quests") or ():
        if not isinstance(quest, dict) or quest.get("is_complete") is True:
            continue
        open_texts = [str(objective.get("description") or "").casefold()
                      for objective in quest.get("objectives") or ()
                      if isinstance(objective, dict) and objective.get("is_complete") is not True]
        if not open_texts:
            continue
        quest_id = str(quest.get("quest_id"))
        for row in (reference.get(quest_id) or {}).get("objectives") or ():
            if not isinstance(row, dict) or row.get("credit_action") != "SPELLCLICK":
                continue
            text = str(row.get("description") or "").strip().casefold()
            if text and not any(text in item for item in open_texts):
                continue                       # this one is done: Kee-La is healed
            for named in row.get("spellclick_creatures") or ():
                if isinstance(named, dict) and named.get("entry") is not None:
                    result.setdefault(str(named["entry"]), quest_id)
    for binding in collect_spellclick_units(state).values():
        result.setdefault(str(binding['npc_id']), binding['quest_id'])
    return result


_CARRY_TEXT = re.compile(r"^\s*(?:carry|bring|return|deliver|escort|take|transport|haul)\b", re.IGNORECASE)
REPICKUP_YARDS = 10.


def pickup_entries(state: dict, *, dropped: bool = False) -> dict[str, str]:
    """{creature entry: quest id} of units an open objective says to pick
    up/use/open (``pickup_objective``); Interact on the soft-interact unit.

    ``dropped``: user 2026-10-23 (A Last Hope): "in combat the egg is always
    put down so you can fight; then it must be picked up again and carried
    on".  The quest log kept "1/1 Pick up" (live 01:19:50 / 01:20:20 a new
    egg 4.6 / 2.8 yd away) while "Carry the egg to safety" was open.  Such
    a finished pickup row counts again while a carry objective is open --
    for a unit right beside the player only (``REPICKUP_YARDS``)."""
    from .packet_entity_facts import pickup_objective
    reference = (state.get("reference_knowledge") or {}).get("quests") or {}
    result: dict[str, str] = {}
    for quest in state.get("active_quests") or ():
        if not isinstance(quest, dict) or quest.get("is_complete") is True:
            continue
        open_texts = [str(objective.get("description") or "").casefold()
                      for objective in quest.get("objectives") or ()
                      if isinstance(objective, dict) and objective.get("is_complete") is not True]
        all_texts = [str(objective.get("description") or "").casefold()
                     for objective in quest.get("objectives") or () if isinstance(objective, dict)]
        carrying = any(_CARRY_TEXT.search(re.sub(r"^\s*\d+/\d+\s*", "", text)) for text in open_texts)
        quest_id = str(quest.get("quest_id"))
        for row in (reference.get(quest_id) or {}).get("objectives") or ():
            text = str((row or {}).get("description") or "").strip().casefold() if isinstance(row, dict) else ""
            if not text or not pickup_objective(row):
                continue
            if dropped:
                if not carrying or not any(text in item for item in all_texts):
                    continue
            elif not any(text in item for item in open_texts):
                continue
            entries = [named.get("entry") for named in row.get("named_creatures") or () if isinstance(named, dict)]
            if row.get("credit_object_id") is not None and not proxy_credit_name(row.get("credit_name")):
                entries.append(row["credit_object_id"])
            for entry in entries:
                if entry is not None:
                    result.setdefault(str(entry), quest_id)
    return result


def turn_in_entries(state: dict) -> dict[str, str]:
    """{creature entry: quest id} of the enders of finished quests."""
    from .turnin_resolver import known_ender_entries
    result: dict[str, str] = {}
    for quest in state.get("active_quests") or ():
        if isinstance(quest, dict) and quest.get("is_complete") is True:
            for entry in known_ender_entries(state, quest.get("quest_id")):
                result.setdefault(entry, str(quest.get("quest_id")))
    return result


LINKED_OBJECT_USE_YARDS = 2.
LINKED_OBJECT_STOP_YARDS = 1.2


def linked_object_entries(state: dict) -> dict[str, str]:
    """{object entry: quest id} of game objects the server links to an open
    quest's objective and marks usable (Activate).

    Live 2026-10-26 21:35 (Best Plans and Intentions 66048): after the gossip
    Fao said to review the table; the battle plans (377106/377111, GOOBER)
    named "Fao the Relentless consulted" (427169) and were usable 3.7 yd
    away.  The agent re-talked to Fao in a loop.  User: "be kéne menjen a
    sátorba, és megnézze az asztalt ... F7-el"."""
    reference = (state.get("reference_knowledge") or {}).get("quests") or {}
    objectives: dict[str, str] = {}
    for quest in state.get("active_quests") or ():
        if not isinstance(quest, dict) or quest.get("is_complete") is True or quest.get("quest_id") is None:
            continue
        qid = str(quest["quest_id"])
        for row in (reference.get(qid) or {}).get("objectives") or ():
            if isinstance(row, dict) and row.get("objective_id") is not None:
                objectives[str(row["objective_id"])] = qid
    result: dict[str, str] = {}
    for value in (state.get("packet_entities") or {}).values():
        if not isinstance(value, dict) or value.get("kind") != "GAMEOBJECT" or value.get("removed"):
            continue
        linked = objectives.get(str((value.get("info") or {}).get("quest_objective_id")))
        flags = (value.get("dynamic_flags") or {}).get("value")
        if linked and go_flags_usable(flags) and game_object_use_candidate(state, value):
            result[str(value.get("entry_id"))] = linked
    # The Scouting Scope (66048) carries no objective id; its spell's DB2
    # kill credit links it, and it opens after Kavia's gossip.
    for entry, quest_id in credit_object_entries(state).items():
        result.setdefault(entry, quest_id)
    return result


class ServerNpcInteractionPolicy:
    """Proposes MOVE then SOFT_INTERACT for server-located objective NPCs."""

    def __init__(self, object_flow=None, *, travel_cost: TravelCostPort | None = None) -> None:
        self.travel_cost = travel_cost
        self.interacted_at: dict[str, float] = {}
        self.pressed_at: dict[str, float] = {}
        self.collected_sources: dict[tuple, float] = {}
        from .object_interaction_flow import ObjectInteractionFlow
        self.object_flow = object_flow if object_flow is not None else ObjectInteractionFlow()

    def candidates(self, state: dict, *, vehicle_requirement: dict | None = None) -> list[tuple[float, dict, dict, str]]:
        entities = state.get("packet_entities")
        player = state.get("player_world_position") or {}
        px, py = number(player.get("x")), number(player.get("y"))
        if not isinstance(entities, dict) or px is None or py is None:
            return []
        # User 2026-10-20: the turn-in NPC's own position is known as soon
        # as the server has sent it -- walk up to it the same way.
        wanted = {**objective_npc_entries(state, travel_cost=self.travel_cost), **turn_in_entries(state)}
        ridden = ride_entries(state)
        wanted.update(ridden)
        picked = pickup_entries(state)
        dropped = {entry: quest for entry, quest in pickup_entries(state, dropped=True).items()
                   if entry not in picked}
        clicked = {**spellclick_entries(state), **linked_object_entries(state)}
        item_clicks = collect_spellclick_units(state)
        item_click_entries = {str(binding['npc_id']) for binding in item_clicks.values()}
        # Gossip-to-fight kill credits (the Blacktalons, 66078): talk first.
        wanted.update({entry: quest_id for entry, (quest_id, _) in sparring_entries(state).items()})
        wanted.update(picked)
        wanted.update(dropped)
        wanted.update(clicked)
        # no NPC flags needed: Interact itself acts
        ridden = {**ridden, **picked, **dropped, **clicked}
        if vehicle_requirement is not None:
            # Completed boarding credit remains an execution prerequisite.
            # Scope this pass to exact boarding entries, never another giver
            # or a different creature with the same display name.
            wanted = {entry: vehicle_requirement["quest_id"] for entry in vehicle_requirement["npc_ids"]}
            ridden, dropped = wanted, {}
        result = []
        soft_guid = next((str(row.get("guid") or "") for row in state.get("soft_targets") or ()
                          if isinstance(row, dict)
                          and str(row.get("source_unit") or "").casefold() == "softinteract"), "")
        for value in entities.values():
            if (not isinstance(value, dict) or value.get("kind") not in {"CREATURE", "VEHICLE", "GAMEOBJECT"}
                    or value.get("removed")):
                continue
            entry = str(value.get("entry_id"))
            binding = item_clicks.get(str(value.get('guid')))
            if entry in item_click_entries and binding is None:
                continue  # another GUID's click flag does not authorize this one
            if binding is not None and self._collected_key(state, binding, value.get('guid')) in self.collected_sources:
                continue
            if vehicle_requirement is not None and (
                    entry not in wanted or value.get("kind") not in {"CREATURE", "VEHICLE"}
                    or value.get("dead") is True or value.get("is_dead") is True
                    or (value.get("info") or {}).get("health") == 0):
                continue
            # User 2026-10-20: quest pickup too.  A unit the server shows with
            # a "!" (or a yellow "?") close by is walked up to the same way;
            # far side givers stay with the campaign-first map-POI policy.
            marker = value.get("quest_giver") or {}
            giver = marker.get("quest_available") is True or marker.get("reward_ready") is True
            # Live 2026-10-23 00:11 (Library of Alexstrasza 66000): the giver
            # was a book on the ground, GameObject 377499 with a server "!",
            # 4 yd away and the client's soft-interact recipient; only
            # creatures were considered, so the agent waited until the user
            # pressed F7.  An object qualifies by its server quest marker only.
            if value.get("kind") == "GAMEOBJECT" and not giver and entry not in clicked:
                continue
            if entry not in wanted and not giver:
                continue
            flags = (value.get("info") or {}).get("npc_flags")
            # Live 2026-10-22 23:11-23:13: the follower Ruby Egg Guardian showed
            # a yellow "?" 3 yd away but was known from monster moves only (no
            # create block, no NPC flags).  A server quest marker is itself
            # proof that the unit can be talked to.
            if (entry not in ridden and not giver
                    and (type(flags) is not int or not flags & TALKABLE_NPC_FLAGS)):
                continue
            point = best_position(value)
            distance = (server_npc_distance(state, point)
                        if point is not None and str(point["instance_id"]) == str(player.get("instance_id"))
                        else None)
            if (str(value.get("guid")) == soft_guid and (entry in wanted or giver)
                    and (distance is None or distance > SEARCH_YARDS)):
                # Live 2026-10-23 01:22:55-01:24:13 (Ruby Lifeshrine): a quest
                # NPC was the client's soft-interact unit while its server point
                # jumped 1500 yd off (platform-relative).  The client cannot
                # soft-target a unit that far: the point is wrong, the unit is here.
                here = {**(point or {}), "x": px, "y": py,
                        "z": player.get("z"), "instance_id": player.get("instance_id")}
                result.append((0., value, here, wanted.get(entry, "")))
                continue
            if distance is None:
                continue
            if entry in dropped and distance > REPICKUP_YARDS:
                continue                       # only the carried thing put down beside us
            if distance <= (SEARCH_YARDS if entry in wanted else GIVER_YARDS):
                result.append((distance, value, point, wanted.get(entry, "")))
        result.sort(key=lambda row: row[0])
        return result

    def note_interaction(self, guid: str, now: float) -> None:
        self.interacted_at[str(guid)] = now

    def note_dispatched(self, guid: str, now: float) -> None:
        self.pressed_at[str(guid)] = now

    @staticmethod
    def _collected_key(state, binding, guid):
        return (state.get('session_id'), str(binding.get('quest_id')),
                str(binding.get('objective_id')), str(guid))

    def note_item_collected(self, state: dict, parameters: dict, now: float) -> None:
        self.collected_sources[self._collected_key(state, parameters, parameters.get('soft_guid'))] = now
        while len(self.collected_sources) > 256:
            self.collected_sources.pop(next(iter(self.collected_sources)))

    def propose(self, state: dict, *, vehicle_requirement: dict | None = None) -> list[Proposal]:
        from wowbot.runtime.skill_identity import check_interaction_recipient
        now = number(state.get("monotonic_time"))
        # Accepting or crediting one conversation can leave another pending
        # at the same NPC. A new quest state may reopen that work immediately;
        # the independent short press throttle still prevents F7 spam.
        from .world import WorldModel
        quests = sorted((q for q in state.get("active_quests") or () if isinstance(q, dict)),
                        key=lambda q: str(q.get("quest_id")))
        context = (state.get("session_id"), WorldModel.quest_signature({"active_quests": quests}))
        previous = self.__dict__.get("_quest_context")
        if previous is not None and previous != context:
            self.interacted_at.clear()
            if previous[0] != context[0]:
                self.pressed_at.clear()
                self.collected_sources.clear()
        self._quest_context = context
        ui_open = ((state.get("quest_ui") or {}).get("open") is True or state.get("quest_ui_open") is True
                   or (state.get("gossip_ui") or {}).get("open") is True
                   or (state.get("vendor_ui") or {}).get("open") is True)   # repair/buy there
        if now is not None and ui_open:
            target = str((state.get("target") or {}).get("guid") or "")
            soft = next((str(row.get("guid")) for row in state.get("soft_targets") or ()
                         if isinstance(row, dict) and row.get("guid")), "")
            for guid in {target, soft} & set(self.pressed_at):
                self.note_interaction(guid, now)          # its window opened: talked to
        if now is None or ui_open or state.get("is_in_combat") or state.get("in_vehicle") is True:
            return []
        player = state.get("player_world_position") or {}
        px, py = number(player.get("x")), number(player.get("y"))
        facing = number(state.get("orientation"))
        linked = linked_object_entries(state) if vehicle_requirement is None else {}
        candidates = self.candidates(state, vehicle_requirement=vehicle_requirement)
        # Live 2026-10-26 21:46: Fao stood 1.9 yd away, the usable battle
        # plans 8.2 yd; nearest-first re-talked to Fao every ~10 s.  The
        # server-linked usable object of an open objective goes first.
        candidates.sort(key=lambda row: (not (row[1].get("kind") == "GAMEOBJECT"
                                               and str(row[1].get("entry_id")) in linked), row[0]))
        for distance, value, point, quest_id in candidates:
            guid = str(value["guid"])
            last, pressed = self.interacted_at.get(guid), self.pressed_at.get(guid)
            if ((last is not None and 0 <= now-last < RETRY_SECONDS)
                    or (pressed is not None and 0 <= now-pressed < PRESS_SECONDS)):
                continue
            bearing = math.atan2(point["y"]-py, point["x"]-px)
            facing_error = (abs((bearing-facing+math.pi) % math.tau - math.pi)
                            if facing is not None else math.inf)
            if value.get("kind") == "GAMEOBJECT" and str(value.get("entry_id")) in linked:
                # An objective's usable object (the battle plans table): F7
                # takes it only when it is right in front and nearer than any
                # unit (GameObject soft-interact is not exported), so step up
                # to it facing it -- never fall through to the next NPC.
                flat = math.hypot(point["x"]-px, point["y"]-py)
                spot = {**point, "guid": guid, "object_id": value.get("entry_id"), "distance": flat}
                layer_z = number(player.get("z")) if player.get("z_known") is not False else None
                ready = self.object_flow.packet_interact_ready(state, spot, layer_z)
                flags = (value.get("dynamic_flags") or {}).get("value")
                activated = go_flags_usable(flags)
                soft_unit = next((str(row.get("guid") or "") for row in state.get("soft_targets") or ()
                                  if isinstance(row, dict)
                                  and str(row.get("source_unit") or "").casefold() == "softinteract"), "")
                # The use skill refuses F7 while another unit is the client's
                # interact recipient (it would talk to Fao): step closer first.
                if ready == "READY" and soft_unit in {"", guid}:
                    return [Proposal.make(
                        "OBJECT_USE", "Objektívához kötött, használható quest-tárgy előttem: F7",
                        {"activation_source": "INTERACT_KEY_PACKET", "binding": "INTERACTTARGET",
                         "object_guid": guid, "object_id": value.get("entry_id"), "quest_ids": [quest_id],
                         "server_interaction_range": self.object_flow.packet_use_range(spot),
                         **({} if activated else {"server_use_basis": CREDIT_OBJECT_BASIS})},
                        confidence=.9, priority=104,
                        evidence=("server_game_object_identity",
                                  "server_activate_flag" if activated else "objective_credit_spell",
                                  "objective_link"))]
                if ready not in {"OUT_OF_RANGE", "NOT_FACING", "OTHER_FLOOR", "REPOSITION"}:
                    # A different recipient/nearer object is not fixed by
                    # pushing into this object's collision model again.
                    return []
                stop = (LINKED_OBJECT_STOP_YARDS if self.object_flow.packet_use_range(spot)
                        <= self.object_flow.PACKET_USE_RANGE_YARDS else self.object_flow.packet_stop_distance(spot))
                if ready == "NOT_FACING":
                    stop = max(stop, flat+.05)  # face in place at the reached edge
                approach = ({} if ready == "OTHER_FLOOR" else
                            self.object_flow.packet_approach_search().goal(state, spot))
                if approach is None:
                    continue  # bounded probes exhausted; let another objective proceed
                return [Proposal.make(
                    "MOVE", "Objektívához kötött quest-tárgy: odalépek és felé fordulok",
                    {"x": point["x"], "y": point["y"], "z": point["z"], "z_known": True,
                     "z_source": "PACKET_GAMEOBJECT", "coordinate_space": "WORLD_YARDS",
                     "instance_id": point["instance_id"], "map_id": state.get("map_id"),
                     "purpose": "APPROACH_QUEST_OBJECT_SPAWN", "require_navmesh": True,
                     "stop_distance": stop, "face_on_arrival": True,
                     "server_entity_guid": guid, "object_id": value.get("entry_id"), "quest_id": quest_id,
                     **approach},
                    confidence=.85, priority=103,
                    evidence=("server_game_object_identity", "objective_link"))]
            soft = next((row for row in state.get("soft_targets") or ()
                         if isinstance(row, dict)
                         and str(row.get("source_unit") or "").casefold() == "softinteract"), None)
            marker = value.get("quest_giver") or {}
            pickup = (str(value.get("entry_id")) in pickup_entries(state)
                      or str(value.get("entry_id")) in pickup_entries(state, dropped=True))
            clicked = str(value.get("entry_id")) in spellclick_entries(state)
            pose = value.get("position") or {}
            stale_moving_origin = (str(pose.get("source") or "").startswith("PACKET_MONSTER_MOVE")
                                   and not pose.get("estimate")
                                   and (number(pose.get("age")) is None or number(pose["age"]) > 2.))
            # A follower moves with the player: its last server point is
            # seconds old.  The client's own F7 recipient being exactly this
            # quest-marked unit is the proof of reach.  An objective's unit to
            # pick up is reached the same way (the egg, 1.5 yd away).
            recipient_ready = (
                (marker.get("reward_ready") is True or marker.get("quest_available") is True
                 # an objective's unit (the egg) right here: Interact reaches it
                 or ((pickup or clicked or bool(quest_id)) and distance <= SOFT_RECIPIENT_YARDS))
                and soft is not None and str(soft.get("guid") or "") == guid
                and soft.get("is_attackable", soft.get("attackable")) is not True
                and soft.get("is_dead", soft.get("dead")) is not True
                and check_interaction_recipient({"guid": guid}, state, now))
            # Do not turn a following ender toward its old spline origin.
            # In that case only the fresh exact client recipient locates it.
            follower_ready = recipient_ready and (
                stale_moving_origin or math.hypot(point["x"]-px, point["y"]-py) < 1.
                or facing_error <= FACING_RADIANS)
            game_object = value.get("kind") == "GAMEOBJECT"
            if ((follower_ready or server_npc_interaction_ready(state, guid, point))
                    and (state.get("movement") or {}).get("moving") is not True):
                item_binding = collect_spellclick_units(state).get(guid)
                return [Proposal.make(
                    "INTERACT", ("Szerver által ismert quest-tárgy előttem (soft-interact egyezik): F7"
                                 if game_object else
                                 "Szerver által ismert quest-NPC előttem (soft-interact egyezik): F7"),
                    {"activation_source": "SOFT_INTERACT", "soft_guid": guid,
                     ("object_id" if game_object else "npc_id"): value.get("entry_id"),
                     "purpose": ("SERVER_OBJECTIVE_NPC" if vehicle_requirement is not None
                                 else "OBJECTIVE_PICKUP" if pickup
                                 else "OBJECTIVE_SPELLCLICK" if clicked else "SERVER_OBJECTIVE_NPC"),
                     "interaction_kind": ("RIDE" if vehicle_requirement is not None
                                          else "QUEST_OBJECT" if game_object
                                          else "PICKUP" if pickup
                                          else "RIDE" if str(value.get("entry_id")) in ride_entries(state)
                                          else "SPELLCLICK" if clicked
                                          else "TALK"),
                     "quest_id": quest_id,
                     **({key: item_binding[key] for key in
                         ('objective_id', 'item_id', 'reference_objective_id')} if item_binding else {}),
                     **({"expected_result": "VEHICLE_ENTERED"}
                        if vehicle_requirement is not None or str(value.get("entry_id")) in ride_entries(state) else {})},
                    confidence=.9, priority=104,
                    evidence=("server_npc_position", "soft_interact_guid_match"))]
            flat = math.hypot(point["x"]-px, point["y"]-py)
            if min(distance, flat) <= INTERACT_YARDS and facing_error <= FACING_RADIANS:
                # In front of it (a hovering vehicle is above us) but another
                # unit is the F7 recipient: walking to the same spot again
                # changes nothing.
                continue
            return [Proposal.make(
                "MOVE", "Szerver: quest-NPC pontos helye: odamegyek és felé fordulok",
                {"x": point["x"], "y": point["y"], "z": point["z"], "z_known": True,
                 "z_source": "PACKET_ENTITY", "coordinate_space": "WORLD_YARDS",
                 "instance_id": point["instance_id"], "map_id": state.get("map_id"),
                 "purpose": "APPROACH_SERVER_NPC", "require_navmesh": True,
                 "stop_distance": max(3., flat+.05) if recipient_ready or min(distance, flat) <= INTERACT_YARDS else 3.,
                 "face_on_arrival": True,
                 "server_entity_guid": guid, ("object_id" if game_object else "npc_id"): value.get("entry_id"),
                 "quest_id": quest_id},
                confidence=.85, priority=102,
                evidence=("server_npc_position", "objective_names_npc"))]
        return []
