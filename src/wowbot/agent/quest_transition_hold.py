"""Bounded, no-input handoffs for a single duel and a delayed follow-up offer."""
from __future__ import annotations

import math

from .models import Proposal, number


def _context(state):
    player = state.get("player_world_position") or {}
    return state.get("session_id"), player.get("instance_id"), state.get("map_id")


def _progress(state, quest_id):
    quest = next((q for q in state.get("active_quests") or ()
                  if str(q.get("quest_id")) == str(quest_id)), None)
    if not quest or quest.get("is_complete") is True:
        return None
    return tuple((o.get("current", o.get("current_count")), o.get("is_complete"))
                 for o in quest.get("objectives") or ())


def _near(state, unit, radius=8.):
    if unit.get("removed"):
        return False
    player = state.get("player_world_position") or {}
    if str(unit.get("map_id")) != str(player.get("instance_id")):
        return False
    distance = number(unit.get("distance"))
    if distance is not None and math.isfinite(distance):
        return 0 <= distance <= radius
    from .packet_entity_facts import best_position
    point = best_position(unit)
    if not point or any(number(row.get(k)) is None for row in (point, player) for k in ("x", "y")):
        return False
    return math.hypot(point["x"]-player["x"], point["y"]-player["y"]) <= radius


class QuestTransitionHold:
    DUEL_START_SECONDS = 15.
    DUEL_MAX_SECONDS = 90.
    OFFER_FIRST_SECONDS = 8.
    OFFER_SILENCE_SECONDS = 20.
    OFFER_MAX_SECONDS = 90.

    def __init__(self):
        self.context = None
        self.duel = None
        self.offer = None
        self.seen = set()

    def _scope(self, state):
        scope = _context(state)
        if scope != self.context:
            self.context, self.duel, self.offer, self.seen = scope, None, None, set()

    def arm_duel(self, state, quest_id, guid):
        self._scope(state)
        now = number(state.get("monotonic_time"))
        if now is None or not math.isfinite(now):
            return
        if self.duel and self.duel["guid"] == guid:
            return  # proposal retries must not extend the transition deadline
        self.duel = {"quest_id": str(quest_id), "guid": str(guid), "at": now,
                     "progress": _progress(state, quest_id), "fight_at": None}

    def _dialog_ender(self, state, quest_id):
        from .quest_ui_evidence import dialog_recipient
        selected = dialog_recipient(state)
        if selected.get("guid"):
            return selected["guid"], selected.get("npc_id"), {str(selected.get("name") or "").casefold()}-{""}
        # Server-mode reward windows can have neither target nor NPC GUID.
        # Require the unique nearby, live server reward-ready entity, scoped
        # to the TDB ender role when reference roles are available.
        ref = ((state.get("reference_knowledge") or {}).get("quests") or {}).get(str(quest_id)) or {}
        enders = {str(r.get("npc_id")) for r in ref.get("quest_roles") or () if r.get("role") == "QUEST_ENDER"}
        choices = [u for u in (state.get("packet_entities") or {}).values()
                   if u.get("guid") and _near(state, u)
                   and (u.get("quest_giver") or {}).get("reward_ready") is True
                   and (number((u.get("quest_giver") or {}).get("age")) or 0.) <= 2.]
        if len(choices) > 1 and enders:
            choices = [u for u in choices if str(u.get("entry_id")) in enders]
        if len(choices) != 1:
            return None
        unit = choices[0]
        names = {str(unit.get("name") or "").casefold()}-{""}
        for event in state.get("events") or ():
            body = event.get("payload") or {}
            if event.get("event_type") == "TARGET_CHANGED" and body.get("guid") == unit["guid"] and body.get("name"):
                names.add(str(body["name"]).casefold())
        return unit["guid"], unit.get("entry_id"), names

    def observe(self, state):
        self._scope(state)
        now = number(state.get("monotonic_time"))
        if now is None or not math.isfinite(now):
            return
        ui = state.get("quest_ui") or {}
        opened = ui.get("open") is True or state.get("quest_ui_open") is True
        action = str(ui.get("action") or state.get("quest_ui_action") or "").upper()
        quest_id = ui.get("quest_id") or state.get("quest_ui_quest_id")
        created = False
        if (self.offer and self.offer["turned_at"] is not None and opened
                and action == "ACCEPT" and str(quest_id) != self.offer["quest_id"]):
            self.offer = None
        if opened and quest_id and action in {"COMPLETE", "TURN_IN", "REWARD_SELECT"}:
            identity = self._dialog_ender(state, quest_id)
            if identity and (not self.offer or self.offer["quest_id"] != str(quest_id)):
                guid, entry, names = identity
                self.offer = {"quest_id": str(quest_id), "guid": guid, "entry": entry, "names": names,
                              "at": now, "turned_at": None, "spoke_at": None}
                created = True
        if self.duel and state.get("is_in_combat") is True:
            self.duel["fight_at"] = now
        for event in state.get("events") or ():
            key = event.get("sequence"), event.get("event_type")
            if key in self.seen:
                continue
            self.seen.add(key)
            if not self.offer:
                continue
            body = event.get("payload") or {}
            if (event.get("event_type") == "TARGET_CHANGED" and body.get("guid") == self.offer["guid"]
                    and body.get("name")):
                # The full target snapshot can be cleared before the same
                # event page arrives. Its exact GUID still names our ender.
                self.offer["names"].add(str(body["name"]).casefold())
            elif event.get("event_type") == "QUEST_TURNED_IN" and str(body.get("quest_id")) == self.offer["quest_id"]:
                self.offer["turned_at"] = self.offer["turned_at"] or now
            elif event.get("event_type") == "NPC_INSTRUCTION" and not created:
                if (body.get("guid") == self.offer["guid"]
                        or str(body.get("sender") or "").casefold() in self.offer["names"]):
                    self.offer["spoke_at"] = now
        if len(self.seen) > 1024:
            # Keep replayed ring events seen; do not manufacture a new line.
            self.seen = {(e.get("sequence"), e.get("event_type")) for e in state.get("events") or ()}
        if self.offer and self.offer["turned_at"] is None and not opened:
            active = {str(q.get("quest_id")) for q in state.get("active_quests") or ()}
            if self.offer["quest_id"] not in active and now-self.offer["at"] <= 30.:
                self.offer["turned_at"] = now

    def propose(self, state):
        self.observe(state)
        now = number(state.get("monotonic_time"))
        if now is None or not math.isfinite(now) or state.get("is_dead") or state.get("is_ghost"):
            return None
        duel = self.duel
        if duel:
            limit = self.DUEL_MAX_SECONDS if duel["fight_at"] is not None else self.DUEL_START_SECONDS
            if (_progress(state, duel["quest_id"]) != duel["progress"] or duel["progress"] is None
                    or not 0 <= now-duel["at"] < limit):
                self.duel = None
            elif state.get("is_in_combat") is not True:
                return Proposal.make("WAIT", "A megszólított párbajpartner átváltására / creditjére várok",
                    {"purpose": "SPARRING_TRANSITION", "quest_ids": [duel["quest_id"]],
                     "event_npc_guid": duel["guid"], "wait_seconds": min(1., limit-(now-duel["at"]))},
                    priority=122, evidence=("quest_sparring_gossip",))
        offer = self.offer
        if not offer or offer["turned_at"] is None or state.get("is_in_combat") is True:
            return None
        if state.get("quest_ui_open") or (state.get("quest_ui") or {}).get("open"):
            return None
        if (not 0 <= now-offer["turned_at"] < self.OFFER_MAX_SECONDS
                or any(_near(state, u) and str(u.get("entry_id")) == str(offer["entry"])
                       and (u.get("quest_giver") or {}).get("quest_available") is True
                       and (number((u.get("quest_giver") or {}).get("age")) or 0.) <= 2.
                       for u in (state.get("packet_entities") or {}).values())):
            self.offer = None
            return None
        last = offer["spoke_at"]
        deadline = ((last+self.OFFER_SILENCE_SECONDS) if last is not None and last >= offer["turned_at"]-3.
                    else offer["turned_at"]+self.OFFER_FIRST_SECONDS)
        if now >= deadline:
            self.offer = None
            return None
        return Proposal.make("WAIT", "Leadás utáni NPC-beszéd / követő quest megjelenésére várok",
            {"purpose": "POST_TURNIN_TRANSITION", "after_turn_in_quest_id": offer["quest_id"],
             "event_npc_guid": offer["guid"], "npc_id": offer["entry"], "wait_seconds": min(1., deadline-now)},
            priority=122, evidence=("confirmed_local_quest_turnin",))
