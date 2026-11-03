"""Quest-dialog proposal policy; it selects no input and mutates no state."""
from __future__ import annotations

import math
import re

from wowbot.query_ports import TravelCostPort
from .models import Goal, Proposal, number, words
from .quest_offer_selector import QuestOfferSelector
from .quest_reward_selector import QuestRewardSelector
from .quest_accept_flow import QuestAcceptFlow
from .quest_semantics import npc_referenced_by_objective, speak_target_matches
from .quest_ui_evidence import dialog_recipient, quest_option_marked


def _tokens(text: str) -> set[str]:
    """Lower-case words of a text, punctuation dropped."""
    return set(re.findall("[a-z0-9]+", words(text)))


class QuestDialogPlanningPolicy:
    """Translate explicit addon UI facts into generic quest-dialog proposals."""

    # User 2026-10-03: when one NPC offers several quests, take the first,
    # then the second, the third ...  If Retail closes the dialog after an
    # accept, the same NPC is spoken to again while offers remain.
    PENDING_OFFER_SECONDS = 45.
    # How long after a turn-in the same NPC is spoken to again.
    FOLLOW_UP_SECONDS = 20.

    def __init__(self, *, travel_cost: TravelCostPort | None = None) -> None:
        self.travel_cost = travel_cost
        self.offer_selector = QuestOfferSelector()
        self.reward_selector = QuestRewardSelector()
        self.accept_flow = QuestAcceptFlow()
        self.pending_offers: dict | None = None
        self.turned_in_at: dict | None = None
        self.scripted_event: dict | None = None
        from .quest_transition_hold import QuestTransitionHold
        self.transitions = QuestTransitionHold()

    def _remember_offers(self, state: dict, rows: list[dict]) -> None:
        now = number(state.get("monotonic_time"))
        guid = str((state.get("target") or {}).get("guid") or "")
        available = {str(row.get("quest_id")) for row in rows
                     if str(row.get("kind") or "").upper() == "AVAILABLE"
                     and row.get("quest_id") is not None}
        if guid and available and now is not None:
            self.pending_offers = {"guid": guid, "quest_ids": available, "at": now}

    def _pending_offer_interact(self, state: dict) -> Proposal | None:
        memory = getattr(self, "pending_offers", None)
        if not memory:
            return None
        now = number(state.get("monotonic_time"))
        if now is None or not 0 <= now - memory["at"] <= self.PENDING_OFFER_SECONDS:
            self.pending_offers = None
            return None
        taken = {str(quest.get("quest_id")) for quest in state.get("active_quests") or ()
                 if isinstance(quest, dict)}
        remaining = memory["quest_ids"] - taken
        if not remaining:
            self.pending_offers = None
            return None
        target = state.get("target") or {}
        if (str(target.get("guid") or "") != memory["guid"] or state.get("is_in_combat")
                or target.get("attackable", target.get("is_attackable")) is True):
            return None
        from .packet_entity_facts import offers_quest
        if offers_quest(state, memory["guid"], max_age=now - memory["at"]) is False:
            # Live 2026-10-19 14:47:51: after both accepts the server showed
            # Henry Garrick with only an in-progress quest; the re-opened
            # window had nothing to accept and the agent stalled in it.
            self.pending_offers = None
            return None
        return Proposal.make(
            "INTERACT", "Ugyanannál az NPC-nél még felvehető quest maradt: újra megszólítás",
            {"guid": memory["guid"], "pending_quest_ids": sorted(remaining)}, priority=95)

    # User 2026-10-20 (The Rescue of Meredy Huntswell): talking to Meredy
    # starts the rescue; harpies and wolves come into the quest area in
    # waves and Bloodbeak arrives last; its death is the credit.  Between
    # waves the agent walked on to other objectives.  After the scripted
    # option has started a fight, stay there (bounded) until this quest's
    # credit; combat and defence skills own every actual fight.
    EVENT_HOLD_SECONDS = 180.
    EVENT_IDLE_SECONDS = 45.
    EVENT_FIGHT_START_SECONDS = 15.
    EVENT_RADIUS_YARDS = 40.

    def _note_scripted_event(self, state: dict, quest_id, guid) -> None:
        now = number(state.get("monotonic_time"))
        position = state.get("player_world_position") or {}
        if now is None:
            return
        previous = getattr(self, "scripted_event", None) or {}
        if previous.get("quest_id") == str(quest_id) and previous.get("fight_at") is not None:
            return                                   # a running event keeps its start
        self.scripted_event = {"quest_id": str(quest_id), "guid": str(guid or ""), "at": now,
                               "x": number(position.get("x")), "y": number(position.get("y")),
                               "fight_at": None}

    def _scripted_event_hold(self, state: dict, dialog_open: bool) -> Proposal | None:
        event = getattr(self, "scripted_event", None)
        now = number(state.get("monotonic_time"))
        if not event or now is None or dialog_open:
            return None
        quest = next((value for value in state.get("active_quests") or ()
                      if isinstance(value, dict) and str(value.get("quest_id")) == event["quest_id"]
                      and value.get("is_complete") is not True), None)
        if quest is None or not 0 <= now-event["at"] <= self.EVENT_HOLD_SECONDS:
            self.scripted_event = None               # credited, abandoned or too long
            return None
        if state.get("is_in_combat"):
            event["fight_at"] = now                  # combat/defend own the fight
            return None
        if event["fight_at"] is None:
            if now-event["at"] > self.EVENT_FIGHT_START_SECONDS:
                self.scripted_event = None           # the option started nothing
            return None
        if now-event["fight_at"] > self.EVENT_IDLE_SECONDS:
            self.scripted_event = None               # no wave for a long time: event over
            return None
        position = state.get("player_world_position") or {}
        px, py = number(position.get("x")), number(position.get("y"))
        if (None not in (px, py, event["x"], event["y"])
                and ((px-event["x"])**2+(py-event["y"])**2) ** .5 > self.EVENT_RADIUS_YARDS):
            return None
        objective_ids = [str(objective.get("objective_id") or f"{event['quest_id']}:{index}")
                         for index, objective in enumerate(quest.get("objectives") or ())
                         if isinstance(objective, dict) and objective.get("is_complete") is not True]
        return Proposal.make(
            "WAIT_EVENT", "Szkriptelt quest-esemény folyamatban: helyben maradok a következő hullámig",
            {"quest_ids": [event["quest_id"]], "objective_ids": objective_ids,
             "objective_kind": "SCRIPTED_EVENT", "event_npc_guid": event["guid"]},
            confidence=.9, priority=113, evidence=("scripted_gossip_started_fight",))

    def _follow_up_interact(self, state: dict, dialog_open: bool, action: str) -> Proposal | None:
        """Remember a turn-in at an NPC; once the quest has left the log and
        the dialog has closed, talk to the same NPC once more."""
        now = number(state.get("monotonic_time"))
        target = state.get("target") or {}
        guid = str(target.get("guid") or "")
        quest_id = (state.get("quest_ui") or {}).get("quest_id") or state.get("quest_ui_quest_id")
        if dialog_open and action in {"COMPLETE", "TURN_IN", "REWARD_SELECT"} and guid and now is not None:
            self.turned_in_at = {"guid": guid, "quest_id": str(quest_id or ""), "at": now, "left": False}
            return None
        memory = getattr(self, "turned_in_at", None)
        if not memory or now is None:
            return None
        if dialog_open:
            ui = state.get("quest_ui") or {}
            if (memory.get("left") or action == "ACCEPT"
                    or ui.get("entries") or state.get("quest_ui_entries")):
                # Spoken to again, or the NPC offers the next quest by itself.
                self.turned_in_at = None
            return None
        if not 0 <= now - memory["at"] <= self.FOLLOW_UP_SECONDS:
            self.turned_in_at = None
            return None
        open_ids = {str(quest.get("quest_id")) for quest in state.get("active_quests") or ()
                    if isinstance(quest, dict)}
        if memory["quest_id"] and memory["quest_id"] in open_ids:
            return None                           # not turned in (yet)
        memory["left"] = True
        if (guid != memory["guid"] or state.get("is_in_combat")
                or target.get("dead", target.get("is_dead"))
                or target.get("attackable", target.get("is_attackable")) is True):
            return None
        from .packet_entity_facts import offers_quest
        if offers_quest(state, memory["guid"], max_age=now - memory["at"]) is False:
            self.turned_in_at = None   # the server shows no follow-up "!" here
            return None
        return Proposal.make(
            "INTERACT", "Leadás után ugyanannak az NPC-nek újra: követő quest felvétele",
            {"guid": memory["guid"], "after_turn_in_quest_id": memory["quest_id"]}, priority=95)

    _BUY_TEXT = re.compile(r"\b(buy|purchase)\b", re.IGNORECASE)

    def _vendor_gossip(self, state: dict, dialog_open: bool) -> Proposal | None:
        """User 2026-10-21 (Cataloger Jakes): "Buy Archeologist Artifact Notes
        from Cataloger Jakes" -- the shop opens from the gossip row "Can I see
        the Renown items you have for sale?".  Click it when an open objective
        says to buy from the NPC whose window this is."""
        from .quest_objective_planning import vendor_gossip_option
        if not dialog_open or (state.get("vendor_ui") or {}).get("open") is True:
            return None
        target = state.get("target") or {}
        name = str(target.get("name") or "").strip().casefold()
        if (not target.get("guid") or not name or target.get("dead", target.get("is_dead")) is True
                or target.get("attackable", target.get("is_attackable")) is True):
            return None
        quest = next((quest for quest in state.get("active_quests") or ()
                      if isinstance(quest, dict) and quest.get("is_complete") is not True
                      and any(isinstance(objective, dict) and objective.get("is_complete") is not True
                              and self._BUY_TEXT.search(str(objective.get("description") or ""))
                              and name in str(objective.get("description") or "").casefold()
                              for objective in quest.get("objectives") or ())), None)
        option = vendor_gossip_option((state.get("quest_ui") or {}).get("gossip_options"))
        if quest is None or option is None:
            return None
        return Proposal.make(
            "QUEST_DIALOG", "Quest vásárlás: a vendor gossip-sorával megnyitom a boltot",
            {"action": "GOSSIP_VENDOR", "x": option["x"], "y": option["y"],
             "gossip_option_id": option["id"], "gossip_option_name": option["name"],
             "target_guid": target["guid"], "quest_id": quest.get("quest_id")},
            confidence=.85, priority=117)

    _STOP_WORDS = frozenset({"the", "and", "for", "with", "from", "about", "after", "your", "have", "what"})

    @classmethod
    def _talk_gossip(cls, state: dict, dialog_open: bool, attempt_memory=None, *,
                     travel_cost: TravelCostPort | None = None, probe: dict | None = None) -> Proposal | None:
        """Prefer an explicit quest row for an exact, open conversation actor.

        The addon exports the API's colored "(Quest)" prefix. It is stronger
        evidence than lexical overlap with a lore option, and row order is
        irrelevant. Neither the prefix alone nor a preferred quest invents
        the actor/quest relationship; unknown or ambiguous choices stay closed.
        Unmarked legacy conversations retain their objective-text matching.
        """
        if not dialog_open:
            return None
        from wowbot.runtime.entity_identity import check_entity_identity, template_id
        target = dialog_recipient(state)
        if not target.get("guid"):
            return None
        reference = (state.get("reference_knowledge") or {}).get("quests") or {}
        eligible = []
        for quest in state.get("active_quests") or ():
            if (not isinstance(quest, dict) or quest.get("is_complete") is True
                    or template_id(quest.get("quest_id")) is None):
                continue
            open_texts = [str(row.get("description") or "").casefold() for row in quest.get("objectives") or ()
                          if isinstance(row, dict) and row.get("is_complete") is not True]
            for row in (reference.get(str(quest.get("quest_id"))) or {}).get("objectives") or ():
                if (not isinstance(row, dict) or row.get("credit_action") in {"BUY", "RIDE"}
                        or not str(row.get("description") or "").strip()
                        or not any(str(row.get("description") or "").casefold() in text for text in open_texts)):
                    continue
                from .packet_entity_facts import proxy_credit_name
                talkers = list(row.get("talk_creatures") or ()) if row.get("credit_action") == "TALK" else []
                from .conversation_actors import conversation_actors
                talkers.extend(conversation_actors(state, quest["quest_id"], row.get("description"),
                                                   travel_cost=travel_cost))
                if any(talk.get('source') == 'QUEST_GIVER_AT_CURRENT_OBJECTIVE'
                       and check_entity_identity({'npc_id': talk.get('entry')}, target) for talk in talkers):
                    row = {**row, 'contextual_talk': True}
                if (probe and str(probe.get('guid')) == str(target.get('guid'))
                        and str(probe.get('quest_id')) == str(quest.get('quest_id'))):
                    # P8.1: the local NPC an unknown-source objective's probe
                    # talked to at its server POI; only the bounded trial runs.
                    from wowbot.runtime.entity_identity import guid_template
                    entry = (template_id(target.get('npc_id')) or template_id(target.get('entry_id'))
                             or guid_template(str(target['guid'])).get('npc_id'))
                    talkers.append({'entry': entry, 'source': 'OBJECTIVE_TALK_PROBE'})
                    row = {**row, 'contextual_talk': True}
                if not talkers:
                    # Live 2026-10-23 01:10 (A Last Hope, "Meet Sendrax by the
                    # ritual site"): the credit is Sendrax himself (190269), his
                    # window held one row, "I am ready."; only "Talk to" credits
                    # counted, so nothing was chosen.  User: a quest NPC to talk
                    # to with a single row -- choose that row.  The NPC must be
                    # the open objective's own credit or named creature.
                    talkers = [*(row.get("named_creatures") or ()),
                               *([{"entry": row.get("credit_object_id")}]
                                 if row.get("credit_object_id") is not None
                                 and not proxy_credit_name(row.get("credit_name")) else [])]
                    row = {**row, "single_row_only": True}
                if not any(check_entity_identity({"npc_id": talk.get("entry")}, target)
                           for talk in talkers if isinstance(talk, dict) and talk.get("entry") is not None):
                    # A quest can say 'Speak with me' while its objective is
                    # 'Oathstone empowered'. Only a catalogue-resolved speaker
                    # variant of this quest can authorize its live menu.
                    speakers = (reference.get(str(quest['quest_id'])) or {}).get('conversation_speakers') or ()
                    if not any(check_entity_identity({'npc_id': actor.get('entry')}, target)
                               for actor in speakers if isinstance(actor, dict)):
                        continue
                    row = {**row, 'single_row_only': True, 'quest_speaker': True}
                eligible.append((template_id(quest["quest_id"]), row))
        if not eligible:
            return None
        observed = [option for option in (state.get("quest_ui") or {}).get("gossip_options") or ()
                    if isinstance(option, dict)]
        from .gossip_trials import MAX_TRIALS, exploration_option, scope
        related_ids = {qid for qid, _ in eligible}
        tried = (attempt_memory.tried_gossip_options(scope(state, next(iter(related_ids)), target['guid']))
                 if attempt_memory is not None and len(related_ids) == 1 else set())
        if tried:
            remaining = [o for o in observed if str(o.get('id')) not in tried]
            if not remaining or len(tried) >= MAX_TRIALS:
                return Proposal.make('WAIT', 'A beszélgetési sorok próbája nem igazolt questkreditet',
                    {'reason': 'quest_gossip_options_exhausted', 'target_guid': target['guid'],
                     'quest_id': next(iter(related_ids)), 'tried_option_ids': sorted(tried),
                     'waiting_for': ['QUEST_PROGRESS_OR_NEW_GOSSIP_MENU']}, priority=117)
            observed = remaining

        def usable(option):
            x, y = number(option.get("x")), number(option.get("y"))
            return (option.get("available") is not False and template_id(option.get("id")) is not None
                    and str(option.get("name") or "").strip()
                    and x is not None and y is not None and math.isfinite(x) and math.isfinite(y)
                    and 0 < x < 1 and 0 < y < 1)

        marked = [option for option in observed if quest_option_marked(option)]
        if marked:
            # Never hide an unusable/ambiguous quest row by choosing lore.
            if len(marked) != 1 or not usable(marked[0]):
                return None
            option = marked[0]
            raw_quest_id = option.get("quest_id")
            option_quest_id = template_id(raw_quest_id)
            if raw_quest_id not in (None, False, "", "0") and option_quest_id is None:
                return None
            related = {quest_id for quest_id, _ in eligible
                       if option_quest_id is None or quest_id == option_quest_id}
            if len(related) != 1:
                return None
            quest_id = related.pop()
            basis = "UNIQUE_QUEST_MARKED_OPTION"
        else:
            options = [option for option in observed if usable(option)]
            if tried or all(row.get('contextual_talk') for _, row in eligible):
                from .gossip_trials import option_for_quest, paid_chat, safe_chat
                options = [option for option in options if safe_chat(option)
                           and (len(related_ids) != 1 or option_for_quest(option, next(iter(related_ids))))]
                # A paid row waits until every free row was tried (live 26209:
                # the bribe outscored the free question on shared words).
                free = [option for option in options if not paid_chat(option)
                        and str(option.get('id')) not in tried]
                if free:
                    options = free
                if not options:
                    if not tried:
                        return None
                    return Proposal.make('WAIT', 'A kipróbálható beszélgetési sorok elfogytak',
                        {'reason': 'quest_gossip_options_exhausted', 'target_guid': target['guid'],
                         'quest_id': next(iter(related_ids)), 'tried_option_ids': sorted(tried),
                         'waiting_for': ['QUEST_PROGRESS_OR_NEW_GOSSIP_MENU']}, priority=117)
            from .gossip_topics import quest_topic_option, self_introduction_option
            topic = quest_topic_option(eligible, options, reference, target)
            introduction = self_introduction_option(eligible,options,reference,state.get('character_name'))
            if topic is not None:
                quest_id, option = topic
                basis = "QUEST_TOPIC_ROLE_MATCH"
            elif introduction is not None:
                quest_id, option = introduction
                basis = 'QUEST_SELF_INTRODUCTION'
            else:
                matches = {}
                for quest_id, row in eligible:
                    if row.get("single_row_only") and len(options) != 1:
                        continue                   # several rows: the actor alone does not pick one
                    wanted = {word for word in _tokens(str(row.get("description") or ""))
                              if len(word) >= 4 and word not in cls._STOP_WORDS}
                    scored = sorted(((len(wanted & _tokens(str(option["name"]))), option)
                                     for option in options), key=lambda item: -item[0])
                    if (not scored or (len(scored) > 1 and scored[0][0] == scored[1][0])
                            or (scored[0][0] == 0 and len(scored) != 1)
                            or (row.get("conversation_source") and scored[0][0] < 2)):
                        continue
                    score, candidate = scored[0]
                    key = (quest_id, template_id(candidate["id"]))
                    if key not in matches or score > matches[key][0]:
                        matches[key] = (score, candidate)
                highest = max((score for score, _ in matches.values()), default=-1)
                winners = [(key, candidate) for key, (score, candidate) in matches.items() if score == highest]
                if len(winners) == 1:
                    (quest_id, _), option = winners[0]
                    basis = ("SINGLE_ROW_OBJECTIVE_ACTOR" if len(options) == 1 and any(
                        row.get("single_row_only") for related, row in eligible if related == quest_id)
                        else "OBJECTIVE_TEXT_MATCH")
                else:
                    trial = exploration_option(eligible, options, tried) if attempt_memory is not None else None
                    if trial is None:
                        return None
                    quest_id, option = trial
                    basis = 'BOUNDED_QUEST_GOSSIP_TRIAL'
        return Proposal.make(
            "QUEST_DIALOG", "Beszélgetős quest-cél: azonosított NPC questhez kötött gossip-sora",
            {"action": "GOSSIP_OPTION_SELECT", "x": number(option["x"]), "y": number(option["y"]),
             "quest_id": quest_id, "target_guid": target["guid"],
             "gossip_option_id": template_id(option["id"]), "gossip_option_name": str(option["name"]),
             "gossip_transition": "QUEST_PROGRESS", "gossip_selection_basis": basis,
             "gossip_trial": attempt_memory is not None and (bool(tried)
                 or basis in {'BOUNDED_QUEST_GOSSIP_TRIAL', 'QUEST_SELF_INTRODUCTION'}
                 or any(qid == quest_id and (row.get('quest_speaker') or row.get('contextual_talk'))
                        for qid, row in eligible))}, priority=117)

    # Live 2026-10-31 10:31 (26209): "Maybe a couple copper will loosen your
    # tongue..." made the server ask "Are you sure you want to give this hobo
    # money? 2 copper"; the agent could not see the popup (addon 0.9.81 exports
    # it).  A small, known sum asked in an NPC's open gossip window is accepted.
    GOSSIP_CONFIRM_MAX_COPPER = 100

    @classmethod
    def _gossip_confirm(cls, state: dict) -> Proposal | None:
        ui = state.get("quest_ui") or {}
        confirm = ui.get("gossip_confirm")
        if not isinstance(confirm, dict) or confirm.get("open") is not True or confirm.get("enabled") is False:
            return None
        x, y, money = number(confirm.get("x")), number(confirm.get("y")), number(confirm.get("money"))
        target = dialog_recipient(state)
        if (x is None or y is None or not (0 < x < 1 and 0 < y < 1)
                or money is None or not 0 < money <= cls.GOSSIP_CONFIRM_MAX_COPPER
                or not str(target.get("guid") or "").startswith("Creature-")):
            return None
        return Proposal.make(
            "QUEST_DIALOG", f"Gossip-megerősítés: {int(money)} copper elfogadása a quest-beszélgetésben",
            {"action": "GOSSIP_CONFIRM", "x": x, "y": y, "money": int(money), "target_guid": target["guid"]},
            confidence=.9, priority=119)

    def propose(self, state: dict, goal: Goal | None, *, primary_quest_id: str = "",
                quest_model=None, attempt_memory=None, probe: dict | None = None) -> list[Proposal]:
        self.transitions.observe(state)
        result: list[Proposal] = []
        ui = state.get("quest_ui") or {}
        dialog_open = ui.get("open") is True or state.get("quest_ui_open") is True
        action = str(ui.get("action") or state.get("quest_ui_action") or "").upper()
        confirm = self._gossip_confirm(state) if dialog_open else None
        if confirm is not None:
            return [confirm]        # the popup is modal: nothing else in this window acts
        vendor_row = self._vendor_gossip(state, dialog_open)
        if vendor_row is not None:
            result.append(vendor_row)
        talk_row = self._talk_gossip(state, dialog_open, attempt_memory, travel_cost=self.travel_cost,
                                     probe=probe)
        if talk_row is not None:
            result.append(talk_row)
        follow_up = self._follow_up_interact(state, dialog_open, action)
        if follow_up is not None:
            result.append(follow_up)
        hold = self._scripted_event_hold(state, dialog_open)
        if hold is not None:
            result.append(hold)
        completion_mode = str(
            state.get("quest_completion_mode")
            or (state.get("primary_quest") or {}).get("completion_mode") or "UNKNOWN").upper()
        dialog_skill = ("FIELD_TURN_IN"
                        if completion_mode == "FIELD_TURN_IN"
                        and action in {"COMPLETE", "TURN_IN", "REWARD_SELECT"}
                        else "QUEST_DIALOG")
        if dialog_open and action == "GOSSIP_OPTION_SELECT" and talk_row is None:
            option = ui.get("gossip_option") or state.get("quest_ui_gossip_option") or {}
            target = state.get("target") or {}
            target_name = str(target.get("name") or "").strip()
            target_guid = str(target.get("guid") or "")
            option_id = number(option.get("id"))
            x, y = number(option.get("x")), number(option.get("y"))
            explicit_id = ((getattr(goal, "parameters", {}) or {}).get("quest_id")
                           if goal is not None else None)
            ready = quest_model.ready() if quest_model is not None else None
            def objectives_for(quest):
                modeled = (quest_model is not None and any(
                    str(record.quest_id) == str(quest["quest_id"])
                    for record in quest_model.records.values()))
                return ([obj for obj in ready
                         if str(obj.objective_id).split(":", 1)[0] == str(quest["quest_id"])]
                        if modeled else quest.get("objectives") or ())
            # A gossip-to-fight kill credit ("Blacktalon tested" from a
            # Blacktalon Avenger, 66078) is named by its credit, not the text.
            from .packet_entity_facts import sparring_entries
            from .vehicle_abilities import entry_of
            sparring = sparring_entries(state).get(entry_of(target_guid) or "")
            related = [quest for quest in state.get("active_quests") or ()
                       if isinstance(quest, dict) and quest.get("quest_id") is not None
                       and quest.get("is_complete") is not True
                       and (explicit_id is None or str(quest["quest_id"]) == str(explicit_id))
                       and target_name and (any(npc_referenced_by_objective(obj, target)
                                                for obj in objectives_for(quest))
                                            or (sparring is not None
                                                and sparring[0] == str(quest["quest_id"])))]
            if (len(related) == 1 and target_guid and option_id is not None
                    and str(option.get("name") or "").strip()
                    and x is not None and y is not None and 0 < x < 1 and 0 < y < 1
                    and target.get("attackable", target.get("is_attackable")) is not True):
                transition = ("QUEST_PROGRESS" if any(
                    speak_target_matches(obj, target) for obj in objectives_for(related[0]))
                    else "SCRIPTED_COMBAT")
                if transition == "SCRIPTED_COMBAT" and sparring is None:
                    # A sparring partner is one duel, then the next partner
                    # elsewhere; the wave hold would keep us here for 45 s.
                    self._note_scripted_event(state, related[0]["quest_id"], target_guid)
                elif transition == "SCRIPTED_COMBAT" and sparring is not None:
                    self.transitions.arm_duel(state, related[0]["quest_id"], target_guid)
                result.append(Proposal.make(
                    "QUEST_DIALOG", "Aktív quest-cél NPC egyetlen, addon által azonosított beszélgetési opciója",
                    {"action": action, "x": x, "y": y,
                     "quest_id": related[0]["quest_id"], "target_guid": target_guid,
                     "gossip_option_id": int(option_id),
                     "gossip_transition": transition,
                     "gossip_option_name": str(option["name"])}, priority=95))
        if dialog_open and action == "REWARD_SELECT":
            parameters = getattr(goal, "parameters", {}) or {}
            selection = self.reward_selector.select(
                ui.get("reward_choices"),
                choice_index=parameters.get("reward_choice_index"),
                item_id=parameters.get("reward_item_id"),
                # User 2026-10-04: a reward window must not stall questing;
                # an explicit goal policy (or BLOCKED) still wins.
                policy=parameters.get("reward_policy") or "AUTO",
            )
            quest_id = ui.get("quest_id") or state.get("quest_ui_quest_id")
            if selection.choice is not None:
                choice = selection.choice
                result.append(Proposal.make(
                    dialog_skill, "Addon által igazolt, explicit quest-jutalom választása",
                    {"x": choice["x"], "y": choice["y"], "action": "REWARD_SELECT",
                     "quest_id": quest_id, "reward_choice_index": choice["index"],
                     "reward_item_id": choice.get("item_id"),
                     "completion_mode": completion_mode}, priority=94,
                ))
            else:
                result.append(Proposal.make(
                    "WAIT", "Quest-jutalom kiválasztása explicit szabályt vagy ellenőrzött sort igényel",
                    {"reason": selection.reason, "quest_id": quest_id,
                     "reward_choices": ui.get("reward_choices") or []},
                    confidence=1., priority=95,
                ))
        if dialog_open and action == "ACCEPT":
            offer = self.accept_flow.read_offer(state)
            command = (self.accept_flow.accept_command(offer)
                       if offer and self.accept_flow.matches_goal(offer, goal) else None)
            if command is not None:
                result.append(Proposal.make(
                    "QUEST_DIALOG", "Célhoz egyező, addon által igazolt quest ajánlat elfogadása",
                    command, priority=90,
                ))
            elif offer is not None and not self.accept_flow.matches_goal(offer, goal):
                result.append(Proposal.make(
                    "WAIT", "A nyitott quest ajánlat nem egyezik az explicit céllal",
                    {"reason": "quest_offer_goal_mismatch",
                     "offered_quest_id": offer.get("quest_id")},
                    confidence=1., priority=95,
                ))
        if dialog_open and action in {"COMPLETE", "CONTINUE", "TURN_IN"}:
            x = number(ui.get("x")) or number(state.get("quest_ui_x"))
            y = number(ui.get("y")) or number(state.get("quest_ui_y"))
            if x is not None and y is not None and x > 0 and y > 0:
                result.append(Proposal.make(
                    dialog_skill, "A megnyitott quest ablak API által jelzett gombja",
                    {"x": x, "y": y, "action": action,
                     "quest_id": ui.get("quest_id") or state.get("quest_ui_quest_id"),
                     "completion_mode": completion_mode}, priority=90,
                ))
        explicit_quest_id = None
        if goal is not None:
            explicit_quest_id = ((getattr(goal, "parameters", {}) or {}).get("primary_quest_id")
                                 or (getattr(goal, "parameters", {}) or {}).get("quest_id"))
        gossip_rows = []
        observed_gossip_rows = []
        for entry in ui.get("entries", state.get("quest_ui_entries", [])):
            if not isinstance(entry, dict):
                continue
            quest_id = entry.get("quest_id")
            kind = str(entry.get("kind") or "").upper()
            if (entry.get("acceptable", entry.get("is_acceptable"))
                    and quest_id is not None and kind in {"AVAILABLE", "COMPLETE"}):
                observed_gossip_rows.append(entry)
                x, y = number(entry.get("x")), number(entry.get("y"))
                if x is None or y is None or not (0 < x < 1 and 0 < y < 1):
                    continue
                row = {"x": number(entry.get("x")), "y": number(entry.get("y")),
                       "quest_id": quest_id, "gossip_kind": kind}
                if entry.get("title"):
                    row["title"] = str(entry["title"])
                gossip_rows.append(row)
        if dialog_open and observed_gossip_rows:
            self._remember_offers(state, observed_gossip_rows)
        elif not dialog_open:
            pending = self._pending_offer_interact(state)
            if pending is not None:
                result.append(pending)
        if dialog_open and observed_gossip_rows and not gossip_rows:
            # A visible gossip/quest list is a modal UI context.  If the addon
            # can identify the rows but cannot export an exact click point,
            # fail closed in that UI instead of allowing world navigation or
            # visual approach to click through/behind it.
            result.append(Proposal.make(
                "WAIT", "A nyitott questlista soraihoz nincs hiteles kattintási koordináta",
                {"reason": "quest_dialog_rows_unaddressable",
                 "offered_quest_ids": sorted({str(row.get("quest_id"))
                                               for row in observed_gossip_rows})},
                confidence=1., priority=110,
            ))
        objective_context = dict((getattr(goal, "parameters", {}) or {}) if goal is not None else {})
        # Only a quest the user named is a hard filter.  The runtime's current
        # quest is a preference: live 2026-10-02 21:45 the just-turned-in
        # primary quest filtered out both offered quests and the agent waited
        # 38 s in front of an open list.
        if primary_quest_id:
            objective_context.setdefault("active_quest_id", primary_quest_id)
        selection = self.offer_selector.select(
            gossip_rows, str(explicit_quest_id) if explicit_quest_id is not None else None,
            objective=objective_context)
        if selection.requires_explicit_selection:
            result.append(Proposal.make(
                "WAIT", "Több addon által igazolt quest-ajánlat látható; explicit quest_id szükséges",
                {"reason": "quest_offer_selection_required",
                 "offered_quest_ids": list(selection.offered_quest_ids)},
                confidence=1., priority=81,
            ))
        for row in selection.rows:
            result.append(Proposal.make(
                "QUEST_DIALOG", "Addon által igazolt, quest-célhoz kötött gossip sor kiválasztása",
                {**row, "action": "GOSSIP_SELECT"}, priority=80,
            ))
        return result
