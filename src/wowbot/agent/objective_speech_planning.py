"""Stand and listen while an objective NPC talks its credit out.

Live 2026-10-26 21:52:58-21:53:35 (Best Plans and Intentions 66048): after
the gossip option Archivist Edress spoke four lines (CHAT_MSG_MONSTER_SAY,
the addon's NPC_INSTRUCTION) over ~37 s, walking while she talked; "Archivist
Edress consulted" came only after her last line.  Meanwhile the agent walked
after her, hunted another quest's mob, got stuck and left.  User: "megkell
várni még végigmondja a mondókáját ... csak akkor várjuk meg ha quest credit
jár érte".

The hold starts only when (1) the speaker's name is in an unfinished
objective's text, (2) the agent itself just talked to that NPC (its gossip /
quest window was open with that unit) and (3) the NPC speaks after that talk.
Greetings said while walking up (Kavia, "I heard rumors you were here.")
start nothing.  It ends with the credit, a usable credit object of the quest
(the Scouting Scope after Kavia's last line), a silence of SILENCE_SECONDS,
combat or HOLD_SECONDS.
"""
from __future__ import annotations

import math

from .models import Proposal, number

SILENCE_SECONDS = 20.          # between lines (Edress: up to 13.7 s before the credit)
HOLD_SECONDS = 90.             # since the talk
TALK_GAP_SECONDS = 10.         # windows this close together are one talk
# Edress's first line came with the F7 press, ~0.4 s before her window was
# reported (1 s event-clock resolution); Kavia's greeting 5 s before the talk.
TALK_LEAD_SECONDS = 3.


def _open_objective(state: dict, name: str) -> tuple[str, str] | None:
    """(quest id, objective description) of an unfinished objective naming this NPC."""
    folded = name.casefold()
    for quest in state.get("active_quests") or ():
        if not isinstance(quest, dict) or quest.get("is_complete") is True:
            continue
        for objective in quest.get("objectives") or ():
            if not isinstance(objective, dict) or objective.get("is_complete") is True:
                continue
            text = str(objective.get("description") or "")
            from wowbot.quests.objective_mechanics import text_hint
            if text_hint(text) == "ARRIVE":
                continue  # 'Travel with X' is the next action, not speech credit
            if folded and folded in text.casefold():
                return str(quest.get("quest_id")), text
    return None


TALK_YARDS = 6.

# REV4 P8.4: the server's Conversation object (HighGuid 7) exists exactly while
# a scripted conversation plays; its removal is the end signal.  Per
# conversation entry the agent learns whether the credit came at its end.
CONVERSATION_MAX_SECONDS = 60.      # never awaited longer (first meeting; learned entries skip it)
CREDIT_GRACE_SECONDS = 5.           # credit this soon after the end belongs to it


def active_conversations(state: dict) -> list[dict]:
    """Live server Conversation objects, newest first."""
    rows = [value for value in (state.get("packet_entities") or {}).values()
            if isinstance(value, dict) and value.get("kind") == "CONVERSATION" and not value.get("removed")]
    return sorted(rows, key=lambda v: -(number((v.get("info") or {}).get("sampled_at")) or 0.))


def _progress(state: dict) -> tuple:
    return tuple((str(q.get("quest_id")), str(o.get("description") or ""), o.get("is_complete"))
                 for q in state.get("active_quests") or () if isinstance(q, dict)
                 for o in q.get("objectives") or () if isinstance(o, dict))


def _witness_objectives(state: dict) -> list[tuple[str, str, set[str]]]:
    """(quest id, objective text, speaker names) of unfinished WITNESS objectives.

    REV4 P8.4: "listen to / overhear / witness" credits come at the end of a
    conversation we only watch -- no talk of ours starts it.  The speakers are
    the NPCs the objective names (its text, TDB named/talk creatures)."""
    reference = (state.get("reference_knowledge") or {}).get("quests") or {}
    result = []
    for quest in state.get("active_quests") or ():
        if not isinstance(quest, dict) or quest.get("is_complete") is True:
            continue
        open_rows = [str(o.get("description") or "") for o in quest.get("objectives") or ()
                     if isinstance(o, dict) and o.get("is_complete") is not True]
        for row in (reference.get(str(quest.get("quest_id"))) or {}).get("objectives") or ():
            if not isinstance(row, dict) or row.get("mechanism") != "WITNESS":
                continue
            text = str(row.get("description") or "").strip().casefold()
            live = next((t for t in open_rows if text and text in t.casefold()), None)
            if live is None:
                continue
            names = {str(c["name"]).casefold() for field in ("named_creatures", "talk_creatures",
                                                              "talk_actor_candidates")
                     for c in row.get(field) or () if isinstance(c, dict) and c.get("name")}
            if row.get("credit_name"):
                names.add(str(row["credit_name"]).casefold())
            result.append((str(quest.get("quest_id")), live, names))
    return result


def _adjacent_objective_npcs(state: dict) -> set[str]:
    """Names of unfinished objectives' NPCs the server shows within TALK_YARDS."""
    from .packet_entity_facts import best_position
    reference = (state.get("reference_knowledge") or {}).get("quests") or {}
    named: dict[str, str] = {}
    for quest in state.get("active_quests") or ():
        if not isinstance(quest, dict) or quest.get("is_complete") is True:
            continue
        for row in (reference.get(str(quest.get("quest_id"))) or {}).get("objectives") or ():
            if not isinstance(row, dict):
                continue
            if row.get("credit_object_id") is not None and row.get("credit_name"):
                named.setdefault(str(row["credit_object_id"]), str(row["credit_name"]))
            for creature in row.get("named_creatures") or ():
                if isinstance(creature, dict) and creature.get("entry") is not None and creature.get("name"):
                    named.setdefault(str(creature["entry"]), str(creature["name"]))
    player = state.get("player_world_position") or {}
    px, py = number(player.get("x")), number(player.get("y"))
    if not named or px is None or py is None:
        return set()
    result = set()
    for value in (state.get("packet_entities") or {}).values():
        if not isinstance(value, dict) or value.get("kind") not in {"CREATURE", "UNIT"} or value.get("removed"):
            continue
        name = named.get(str(value.get("entry_id")))
        point = best_position(value) if name else None
        if (point is not None and _open_objective(state, name) is not None
                and math.hypot(point["x"]-px, point["y"]-py) <= TALK_YARDS):
            result.add(name.casefold())
    return result


class ObjectiveSpeechHold:
    def __init__(self) -> None:
        self.talked_at: dict[str, float] = {}       # the talk began (window first open)
        self.open_at: dict[str, float] = {}         # its window last seen open
        self.spoke_at: dict[str, float] = {}
        self.heard: set[tuple] = set()
        self.witness_started: dict[str, float] = {}   # quest -> first line of the watched conversation
        self.conversations: dict[str, dict] = {}      # GUID -> entry, seen, progress at start, ended
        self.conversation_credit: dict[int, str] = {}  # entry -> CREDIT_AT_END / CREDIT_BEFORE_END / NO_CREDIT

    def _observe(self, state: dict, now: float) -> None:
        ui_open = ((state.get("quest_ui") or {}).get("open") is True or state.get("quest_ui_open") is True
                   or (state.get("gossip_ui") or {}).get("open") is True)
        action = str((state.get("quest_ui") or {}).get("action") or state.get("quest_ui_action") or "").upper()
        # An accept/turn-in greeting is not the objective's conversation.
        # It can explicitly tell the player to give a signal via another row.
        conversation_open = ui_open and action not in {"ACCEPT", "COMPLETE", "TURN_IN", "REWARD_SELECT", "GOSSIP_SELECT"}
        if conversation_open:
            names = {str(unit["name"]).casefold() for unit in (state.get("target"), *(state.get("soft_targets") or ()))
                     if isinstance(unit, dict) and unit.get("name")
                     and str(unit.get("guid") or "").startswith("Creature-")}
            # Live 23:06:34: F7 talked to Edress through soft-interact with no
            # target; the window was open 0.6 s and named no unit.  The
            # server's objective NPC standing next to us is the partner.
            names |= _adjacent_objective_npcs(state)
            for name in names:
                if not 0 <= now-self.open_at.get(name, float("-inf")) <= TALK_GAP_SECONDS:
                    self.talked_at[name] = now      # a new talk, not the same window
                self.open_at[name] = now
        for event in state.get("events") or ():
            if not isinstance(event, dict) or event.get("event_type") != "NPC_INSTRUCTION":
                continue
            sender = str((event.get("payload") or {}).get("sender") or "").casefold()
            key = (event.get("sequence"), sender, str((event.get("payload") or {}).get("message") or ""))
            if not sender or key in self.heard:
                continue
            # Received now: the event's own epoch stamp ran ~4 s behind the
            # state clock live (Edress 21:52:58), so it cannot be compared.
            self.heard.add(key)
            self.spoke_at[sender] = now
        if len(self.heard) > 512:
            self.heard = set(list(self.heard)[-256:])
        self._observe_conversations(state, now)

    def _observe_conversations(self, state: dict, now: float) -> None:
        live = {str(v.get("guid")): v for v in active_conversations(state)}
        progress = _progress(state)
        for guid, value in live.items():
            self.conversations.setdefault(guid, {"entry": value.get("entry_id"), "seen": now,
                                                 "progress": progress, "ended": None})
        for guid, row in list(self.conversations.items()):
            entry = row["entry"]
            if row["ended"] is None and guid not in live:
                row["ended"] = now
            if row["progress"] != progress and entry not in self.conversation_credit:
                self.conversation_credit[entry] = ("CREDIT_BEFORE_END" if row["ended"] is None
                                                   else "CREDIT_AT_END")
            if row["ended"] is not None and now-row["ended"] >= CREDIT_GRACE_SECONDS:
                self.conversation_credit.setdefault(entry, "NO_CREDIT")
                del self.conversations[guid]

    def awaited_conversation(self, now: float, since: float | None = None) -> dict | None:
        """A running conversation worth waiting for: not learned to give no
        (or an earlier) credit, younger than CONVERSATION_MAX_SECONDS."""
        for guid, row in sorted(self.conversations.items(), key=lambda item: -item[1]["seen"]):
            if (row["ended"] is None and 0 <= now-row["seen"] <= CONVERSATION_MAX_SECONDS
                    and (since is None or row["seen"] >= since)
                    and self.conversation_credit.get(row["entry"]) not in {"NO_CREDIT", "CREDIT_BEFORE_END"}):
                return {"guid": guid, **row}
        return None

    def silent_conversation(self, since: float) -> bool:
        """The conversation started by this talk is learned to give no credit at its end."""
        return any(row["seen"] >= since and self.conversation_credit.get(row["entry"]) in
                   {"NO_CREDIT", "CREDIT_BEFORE_END"} for row in self.conversations.values())

    def observe(self, state: dict) -> None:
        """Record talks and lines while an open window bypasses propose()."""
        now = number(state.get("monotonic_time"))
        if now is not None:
            self._observe(state, now)

    def propose(self, state: dict) -> list[Proposal]:
        now = number(state.get("monotonic_time"))
        if now is None:
            return []
        self._observe(state, now)
        if (state.get("is_in_combat") or state.get("in_vehicle") or state.get("on_taxi")
                or (state.get("quest_ui") or {}).get("open") is True or state.get("quest_ui_open") is True):
            return []
        from .server_npc_planning import linked_object_entries
        usable = set(linked_object_entries(state).values())
        for name, talked in sorted(self.talked_at.items(), key=lambda row: -row[1]):
            if not 0 <= now-talked <= HOLD_SECONDS:
                continue
            objective = _open_objective(state, name)
            if objective is None or objective[0] in usable:
                continue                       # credited, or the next step is here
            if self.silent_conversation(talked-TALK_LEAD_SECONDS):
                continue                       # learned: this conversation gives no credit at its end
            running = self.awaited_conversation(now, talked-TALK_LEAD_SECONDS)
            if running is not None:
                return [self._conversation_hold(objective[0], objective[1], running, now, name)]
            spoke = self.spoke_at.get(name)
            if spoke is None or spoke < talked-TALK_LEAD_SECONDS:
                # Live 2026-10-27 15:45:07 / 15:52:32: Wrathion said nothing;
                # waiting for a first line held 15 s each time (WAIT_EVENT
                # minimum) and blocked his reopened gossip row for 7 s.
                continue
            remaining = SILENCE_SECONDS-(now-spoke)
            if remaining <= 0:
                continue
            return [Proposal.make(
                "WAIT_EVENT", "Az objektív NPC még beszél (kreditet ad a végén): megvárom, nem megyek el",
                {"quest_ids": [objective[0]], "objective_kind": "NPC_SPEECH", "speaker_name": name,
                 "objective_text": objective[1],
                 "wait_seconds": round(min(remaining, HOLD_SECONDS-(now-talked)), 1)},
                confidence=.85, priority=121, evidence=("objective_npc_speech_after_talk",))]
        return self._witness(state, now)

    def _witness(self, state: dict, now: float) -> list[Proposal]:
        """P8.4 WITNESS: while the named speakers talk, stay; the end signal is
        the credit, SILENCE_SECONDS without a line, or HOLD_SECONDS overall."""
        for quest_id, text, names in _witness_objectives(state):
            running = self.awaited_conversation(now)
            if running is not None:
                return [self._conversation_hold(quest_id, text, running, now)]
            folded = text.casefold()
            spoken = [at for name, at in self.spoke_at.items() if name in names or (name and name in folded)]
            last = max(spoken, default=None)
            if last is None or not 0 <= now-last < SILENCE_SECONDS:
                self.witness_started.pop(quest_id, None)
                continue
            started = self.witness_started.setdefault(quest_id, last)
            if now-started >= HOLD_SECONDS:
                continue
            return [Proposal.make(
                "WAIT_EVENT", "Beszélgetést kell végighallgatnom (WITNESS): maradok, amíg tart",
                {"quest_ids": [quest_id], "objective_kind": "WITNESS_CONVERSATION", "objective_text": text,
                 "wait_seconds": round(min(SILENCE_SECONDS-(now-last), HOLD_SECONDS-(now-started)), 1)},
                confidence=.8, priority=121, evidence=("objective_witness_speech",))]
        return []

    @staticmethod
    def _conversation_hold(quest_id: str, text: str, running: dict, now: float, speaker=None) -> Proposal:
        return Proposal.make(
            "WAIT_EVENT", "Szerveres beszélgetés fut (conversation): a végéig maradok, a kredit a végén jöhet",
            {"quest_ids": [quest_id], "objective_kind": "CONVERSATION", "objective_text": text,
             "conversation_guid": running["guid"], "conversation_entry": running["entry"],
             **({"speaker_name": speaker} if speaker else {}),
             "wait_seconds": round(max(1., min(10., CONVERSATION_MAX_SECONDS-(now-running["seen"]))), 1)},
            confidence=.85, priority=121, evidence=("server_conversation_object",))
