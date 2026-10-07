"""Combat, target-reacquisition and loot proposal policy.

The policy is deliberately input-free.  It does not select the winning
proposal, dispatch commands, mutate the WorldModel, or own combat/target
lifecycle.  The single high-level Planner composes its proposals with the
other domains and remains the only selection authority.
"""
from __future__ import annotations

import math

from dataclasses import dataclass
from typing import Any

from .models import Goal, Proposal, number, words
from .visual_approach import VisualApproachController
from .quest_semantics import (combat_subjects, target_matches_objective,
                              target_matches_structured_entity)


def _model(world):
    """The WorldModel behind a planner WorldSnapshot (or the model itself)."""
    return getattr(world, "_model", None) or world


@dataclass(frozen=True, slots=True)
class CombatPlanningResult:
    proposals: tuple[Proposal, ...]
    target: dict
    matching_objectives: tuple[Any, ...]
    matching_quest_ids: tuple[Any, ...]
    matching_objective_ids: tuple[str, ...]


# The quest model normalizes USE_ITEM to USE_OBJECT.
ITEM_USE_OBJECTIVES = frozenset({"USE_ITEM", "USE_ITEM_ON_TARGET", "USE_OBJECT"})


VEHICLE_ATTACK_READY_HEIGHT = .085   # bbox height fraction: close enough for a CLOSE ability
VEHICLE_REFLEX_HEIGHT = .10          # a box this tall on the centre line is about to be hit


def vehicle_attack_action(state: dict, learned: dict | None = None,
                          advice: dict | None = None, preferred=()) -> dict | None:
    """The ridden vehicle's ability to use on an objective unit (generic)."""
    from .vehicle_abilities import choose_attack_action
    return choose_attack_action(state, learned, advice, preferred)


class CombatPlanningPolicy:
    """Project target/combat evidence into proposals without side effects."""

    def __init__(self, registry):
        self.registry = registry

    REVEAL_WINDOW_SECONDS = 10.

    def _soft_interact_loot(self, world, state: dict, now: float) -> Proposal | None:
        """Own kill named by the client's soft-interact unit (no box needed)."""
        from wowbot.skills.loot import soft_interact_corpse
        # Ownership/loot times are runtime-clock times (as ``now``), not the
        # addon's GetTime() in state["monotonic_time"].
        state_now = now
        for row in state.get("soft_targets") or ():
            guid = str((row or {}).get("guid") or "") if isinstance(row, dict) else ""
            if (not guid or state_now is None or not soft_interact_corpse(state, guid)
                    or not _model(world).corpse_is_owned(guid, state_now)
                    or world.corpse_was_recently_looted(guid, state_now)
                    or self._reported_empty(state, guid)):
                continue
            objectives = self._active_incomplete_objectives(world)
            return Proposal.make(
                "LOOT", "Saját ölés holtteste a kliens soft-interact egysége: interact billentyű",
                {"guid": guid, "soft_interact": True,
                 "quest_ids": list(dict.fromkeys(qid for qid, _ in objectives)),
                 "objective_ids": [oid for _, oid in objectives]},
                confidence=1., priority=108)
        return None

    def _hidden_corpse_reveal(self, world, state: dict, now: float) -> Proposal | None:
        owned = getattr(_model(world), "owned_corpse_guids", None) or {}
        anchored = {str(item.get("guid")) for item in state.get("confirmed_corpse_anchors") or ()
                    if isinstance(item, dict)}
        done = _model(world).__dict__.setdefault("corpse_reveal_done", {})
        state_now = now
        if (state.get("target") or {}).get("guid"):
            return None
        for guid, killed_at in sorted(owned.items(), key=lambda item: -float(item[1] or 0)):
            killed = number(killed_at)
            if (killed is None or not 0. <= state_now-killed <= self.REVEAL_WINDOW_SECONDS
                    or guid in anchored or guid in done
                    or world.corpse_was_recently_looted(guid, state_now)
                    or self._reported_empty(state, guid)):
                continue
            done[guid] = state_now
            return Proposal.make(
                "RECOVER", "Megölt, de nem látható (karakter alatti) holttest felfedése rövid hátralépéssel",
                {"recovery_step": "BACKWARD_REVEAL", "corpse_guid": guid},
                confidence=.8, priority=95)
        return None

    @staticmethod
    def _vehicle_aims(state: dict, target: dict, ready_objectives, matching_objectives) -> list[dict]:
        """Objective units on screen a ridden vehicle can attack, nearest first.

        User 2026-10-04: "a farther one is selected, the nearer one is in
        front and knocks the boar back".  Besides the selected target, every
        unit an addon hover named (confirmed mouseover anchor bound to a live,
        non-self World3D track) that matches an open objective is an aim; the
        tallest box (nearest) wins.
        """
        from .self_avatar import is_self_avatar_box
        live = {str(item.get("track_id")): item for item in state.get("visual_candidates") or ()
                if isinstance(item, dict) and item.get("source") == "WORLD3D"
                and item.get("track_id") is not None and not is_self_avatar_box(item)
                and str(item.get("lifecycle") or "ACTIVE").upper()
                not in {"TERMINATED", "LOST", "LOST_TEMPORARY"}
                and number(item.get("x")) is not None and number(item.get("y")) is not None}
        aims = []
        target_guid = str((target or {}).get("guid") or "")
        if target_guid and matching_objectives and not target.get("dead", target.get("is_dead")):
            anchor = target.get("screen_position") or {}
            track = live.get(str(anchor.get("track_id") or target.get("visual_track_id") or ""))
            aims.append({"guid": target_guid, "selected": True, "track": track, "anchor": anchor,
                         "objectives": list(matching_objectives)})
        semantics = state.get("confirmed_entity_semantics") or {}
        for guid, anchor in (state.get("confirmed_mouseover_anchors") or {}).items():
            if str(guid) == target_guid or not isinstance(anchor, dict) or anchor.get("dead") is True:
                continue
            track = live.get(str(anchor.get("track_id") or ""))
            if track is None:
                continue
            unit = {"guid": guid, "name": anchor.get("name") or (semantics.get(guid) or {}).get("name")}
            objectives = [obj for obj in ready_objectives
                          if target_matches_objective(unit, {**obj.raw, "description": obj.description})]
            if objectives:
                aims.append({"guid": str(guid), "selected": False, "track": track, "anchor": anchor,
                             "objectives": objectives})

        # Look-alikes of this quest's hover-confirmed targets (visual
        # prototypes) are aims too, without a hover first.
        kill_objectives = [obj for obj in ready_objectives
                           if str(getattr(obj, "type", "")).upper() == "KILL"]
        known_tracks = {str((aim["track"] or {}).get("track_id")) for aim in aims}
        if kill_objectives:
            for track_id, item in live.items():
                appearance = item.get("appearance") if isinstance(item.get("appearance"), dict) else {}
                if (track_id not in known_tracks
                        and (number(appearance.get("prototype_lift")) or 0.) >= .6):
                    aims.append({"guid": None, "selected": False, "track": item, "anchor": {},
                                 "objectives": kill_objectives, "prototype_only": True})

        def height(aim):
            source = aim["track"] or aim["anchor"] or {}
            return number(source.get("bbox_height_fraction")) or 0.
        return sorted(aims, key=lambda aim: (-height(aim), not aim["selected"]))

    def _vehicle_attack(self, world, state: dict, target: dict, ready_objectives,
                        matching_objectives, quest_ids, objective_ids) -> list[Proposal]:
        """Use a ridden vehicle's ability on an objective unit -- any vehicle.

        Live 2026-10-04 (Giant Boar): Monstrous Cadavers are ClientActor
        objects (not attackable); Trample lunges the boar ~30 yd along its
        facing and tramples what is in the way, while walking into a cadaver
        without it knocks the boar back.  User: every quest vehicle differs,
        so the use mode comes from ``vehicle_abilities`` (learned effect >
        tooltip > range), never from a spell id.
        """
        from .vehicle_abilities import (FORWARD_DASH, TARGETED, ability_mode,
                                        aim_tolerance)
        learned = _model(world).__dict__.setdefault("vehicle_ability_effects", {})
        advice = _model(world).__dict__.get("vehicle_ability_advice") or {}
        spoken = [hint.get("ability") for hint in _model(world).__dict__.get("npc_instruction_hints") or ()
                  if isinstance(hint, dict)]
        action = vehicle_attack_action(state, learned, advice, spoken)
        if action is None:
            return []
        mode = ability_mode(action, learned, advice)
        # Live 17:58: a second press 0.5 s after the first hit "Spell is not
        # ready yet".  Wait out the cooldown plus the lunge in flight.
        pressed_at = (_model(world).__dict__.get("vehicle_ability_pressed_at") or {}).get(
            str(action.get("id")))
        clock = number(getattr(_model(world), "last_received", None))
        refractory = max(1.4, (number(action.get("cooldown_duration")) or 0.)+.4)
        cooling = (pressed_at is not None and clock is not None and 0 <= clock-pressed_at < refractory)
        aims = self._vehicle_aims(state, target, ready_objectives, matching_objectives)
        kill_open = any(str(getattr(obj, "type", "")).upper() == "KILL" for obj in ready_objectives)

        def ability(reason: str, aim: dict | None, priority: int) -> Proposal | None:
            if cooling:
                # Lunge in flight / cooldown: hold still for it rather than
                # starting a seconds-long mouseover probe.
                return Proposal.make("WAIT", "Jármű-képesség: roham folyamatban / újratöltés",
                                     {"waiting_for": ["VEHICLE_ABILITY_READY"]}, priority=priority)
            objectives = (aim or {}).get("objectives") or matching_objectives
            return Proposal.make("VEHICLE_ABILITY", reason, {
                "guid": aim["guid"] if aim and aim["selected"] else None,
                "aim_guid": (aim or {}).get("guid"),
                "binding": action["action"], "spell_id": action.get("id"),
                "ability_name": action.get("name"), "use_mode": mode,
                "quest_ids": quest_ids or list(dict.fromkeys(
                    record.quest_id for record in world.quest_model.records.values()
                    if any(obj in record.objectives for obj in objectives))),
                "objective_ids": objective_ids or [obj.objective_id for obj in objectives]},
                priority=priority)

        if mode == FORWARD_DASH and (aims or kill_open):
            # Reflex: a unit right on the centre line is about to be hit --
            # lunge through it instead of bumping into it.
            from .self_avatar import is_self_avatar_box
            for item in state.get("visual_candidates") or ():
                if (isinstance(item, dict) and item.get("source") == "WORLD3D"
                        and "subject" in str(item.get("detector_kind") or item.get("kind") or "")
                        and not is_self_avatar_box(item)
                        and str(item.get("lifecycle") or "ACTIVE").upper() in {"ACTIVE", "STABLE", "TENTATIVE"}
                        and (number(item.get("bbox_height_fraction")) or 0.) >= VEHICLE_REFLEX_HEIGHT
                        and abs((number(item.get("x")) or 0.)-.5) <= aim_tolerance(
                            number(item.get("bbox_width_fraction")))):
                    reflex = ability("Járművel: egység közvetlenül előttünk -- a jármű előre-támadása",
                                     aims[0] if aims else None, 105)
                    return [reflex] if reflex else []
        if mode != FORWARD_DASH:
            aims = [aim for aim in aims if not aim.get("prototype_only")]
        if not aims:
            return []
        aim = aims[0]
        if mode == TARGETED and not aim["selected"]:
            aim = next((item for item in aims if item["selected"]), None)
            if aim is None:
                return []          # target planning selects a unit first
        screen = aim["track"] or aim["anchor"] or {}
        x, height = number(screen.get("x")), number(screen.get("bbox_height_fraction"))
        width = number(screen.get("bbox_width_fraction"))
        position = state.get("player_world_position") or {}
        where = (target.get("world_position") or {}) if aim["selected"] else {}
        distance = None
        if None not in (number(position.get("x")), number(position.get("y")),
                        number(where.get("x")), number(where.get("y"))):
            distance = math.hypot(float(where["x"])-float(position["x"]),
                                  float(where["y"])-float(position["y"]))
        params = {"guid": aim["guid"] if aim["selected"] else None, "aim_guid": aim["guid"],
                  "quest_ids": quest_ids, "objective_ids": objective_ids, "use_mode": mode}
        if mode == FORWARD_DASH:
            # Fire at 1.5x the aim tolerance: VEHICLE_AIM stops turning at 1x,
            # so a box that drifted a little on the next frame is still hit
            # (live 17:40: the aim alternated left/right instead of lunging).
            if x is not None and abs(x-.5) <= 1.5*aim_tolerance(width):
                lunge = ability("Járművel a quest-célpontra fordulva: előre-támadás", aim, 104)
                return [lunge] if lunge else []
            purpose, ready_height = "VEHICLE_AIM", None
        elif mode == TARGETED:
            if action.get("in_range") is True:
                cast = ability("Járművel: a célzott képesség hatótávon belül", aim, 104)
                return [cast] if cast else []
            purpose, ready_height = "VEHICLE_ATTACK", None
        else:
            close = ((height is not None and height >= VEHICLE_ATTACK_READY_HEIGHT)
                     or (height is None and distance is not None and distance <= 10.))
            if close and (x is None or abs(x-.5) <= .10):
                use = ability("Járművel a quest-célpont mellett: a jármű képessége", aim, 104)
                return [use] if use else []
            purpose, ready_height = "VEHICLE_ATTACK", VEHICLE_ATTACK_READY_HEIGHT
        if x is not None and number(screen.get("y")) is not None and screen.get("track_id") is not None:
            return [Proposal.make(
                "VISUAL_APPROACH", "Járművel a quest-célpont felé (képernyőn követve)",
                {**params, "purpose": purpose, "track_id": screen.get("track_id"),
                 "visual_signature": screen.get("visual_signature"),
                 "screen_position": aim["anchor"] if aim["selected"] else None,
                 "ready_bbox_height": ready_height}, confidence=.85, priority=103)]
        if distance is not None:
            return [Proposal.make(
                "MOVE", "Járművel a quest-célpont becsült helyére",
                {**params, "x": where["x"], "y": where["y"], "coordinate_space": "WORLD_YARDS",
                 "instance_id": where.get("instance_id"), "map_id": state.get("map_id"),
                 "purpose": "VEHICLE_ATTACK_APPROACH",
                 "stop_distance": 25.0 if mode == FORWARD_DASH else 10.0}, priority=102)]
        return []

    def propose(self, world, goal: Goal, now: float, quest_domain) -> CombatPlanningResult:
        state = world.state
        proposals: list[Proposal] = []
        target = world.query.target()
        commitment = world.runtime_context.get("commitment") or {}

        if (commitment.get("kind") == "TARGET" and commitment.get("target_guid")
                and not state.get("is_in_combat") and not state.get("world_map_open")
                and target.get("guid") != commitment.get("target_guid")
                and (state.get("mouseover") or {}).get("guid") != commitment.get("target_guid")):
            # A short-lived, confirmed screen anchor can reacquire the exact
            # committed identity.  It cannot create a new semantic identity.
            guid = commitment["target_guid"]
            anchor = ((target.get("screen_position") if target.get("guid") == guid else None)
                      or (state.get("confirmed_mouseover_anchors") or {}).get(guid))
            anchor_time = number((anchor or {}).get("sample_time"))
            state_time = number(state.get("monotonic_time"))
            anchor_fresh = (isinstance(anchor, dict) and anchor_time is not None
                            and state_time is not None and 0 <= state_time-anchor_time < 30.
                            and number(anchor.get("x")) is not None
                            and number(anchor.get("y")) is not None)
            if anchor_fresh:
                proposals.append(Proposal.make(
                    "REACQUIRE_TARGET",
                    "Elvesztett vizuális nyomkövetés visszaszerzése: kamera az utolsó ismert pozíció felé",
                    {"guid": guid, "target_x": anchor["x"], "target_y": anchor["y"]},
                    confidence=.75, priority=92))

        primary_context = world.runtime_context.get("primary_quest") or {}
        primary_quest_id = str(primary_context.get("quest_id") or "")
        primary_objective_id = str(primary_context.get("objective_id") or "")
        ready_objectives = [
            obj for obj in world.quest_model.ready()
            if (not primary_quest_id or obj.objective_id.split(":", 1)[0] == primary_quest_id)
            and (not primary_objective_id or obj.objective_id == primary_objective_id)
        ]
        matching_objectives = [
            obj for obj in ready_objectives
            if target_matches_structured_entity(target, obj.target_entity)
            or target_matches_objective(target, {**obj.raw, "description": obj.description})
        ]
        matching_quest_ids = list(dict.fromkeys(
            record.quest_id for record in world.quest_model.records.values()
            if any(obj in record.objectives for obj in matching_objectives)))
        matching_objective_ids = [obj.objective_id for obj in matching_objectives]
        vehicle_attack = self._vehicle_attack(world, state, target, ready_objectives,
                                              matching_objectives, matching_quest_ids,
                                              matching_objective_ids)
        if vehicle_attack:
            return CombatPlanningResult(
                tuple(vehicle_attack), target, tuple(matching_objectives),
                tuple(matching_quest_ids), tuple(matching_objective_ids))

        training_objectives = [
            obj for obj in ready_objectives
            if any(token in words(obj.description)
                   for token in ("spar", "abilities proven", "combat tactics"))
        ]
        instructions = [event for event in state.get("events", [])
                        if event.get("event_type") == "NPC_INSTRUCTION"]
        if (training_objectives and instructions
                and target.get("attackable", target.get("is_attackable")) is True):
            instruction = str((instructions[-1].get("payload") or {}).get("message") or "")
            action = self.registry.instructed_action(state, instruction)
            if action:
                proposals.append(Proposal.make(
                    "FOLLOW_INSTRUCTION",
                    "NPC instrukciója explicit módon megnevezett egy használható képességet",
                    {"guid": target.get("guid"), "instruction": instruction,
                     "binding": action.get("action"),
                     "spell_id": action.get("id", action.get("spell_id")),
                     "objective_id": training_objectives[0].objective_id,
                     "quest_ids": matching_quest_ids}, priority=110))

        target_anchor = (state.get("confirmed_mouseover_anchors") or {}).get(
            str(target.get("guid") or ""), {})
        # Live 2026-10-03 13:12: the porcupine was targeted because its
        # tooltip named "Raw Meat"; the target frame carries no quest flag
        # and a "wildlife" objective names no creature, so a MOVE (44) won
        # for 18 s.  The mouseover judgement made before TARGET counts.
        judged_at = number((getattr(_model(world), "quest_relevant_units", None) or {}).get(
            str(target.get("guid") or "")))
        state_now = number(state.get("monotonic_time"))
        judged_relevant = (judged_at is not None and state_now is not None
                           and 0. <= state_now-judged_at <= 600.
                           and bool(ready_objectives))
        relevant = (target.get("quest_relevant") is True
                    or target_anchor.get("quest_related") is True
                    or judged_relevant
                    or target.get("npc_id") in goal.parameters.get("target_npc_ids", []))
        if target.get("quest_relevant") is True and target.get("quest_id") is not None:
            matching_quest_ids = list(dict.fromkeys([*matching_quest_ids, target["quest_id"]]))
        if target_anchor.get("quest_related") is True and target_anchor.get("quest_id") is not None:
            matching_quest_ids = list(dict.fromkeys([*matching_quest_ids, target_anchor["quest_id"]]))
        name = words(str(target.get("name") or ""))
        if name:
            relevant = relevant or bool(matching_objectives)
        relevant = relevant or bool(matching_objectives)
        if not relevant and not name:
            # A nameless tab-target can still be relevant when ACQUIRE_TARGET
            # was only possible because a kill objective is ready. Identified
            # mouseover targets retain the strict semantic matching path.
            relevant = any(
                obj.type == "KILL"
                or combat_subjects({**obj.raw, "description": obj.description})
                for obj in ready_objectives)

        item_use_only = bool(
            (matching_objectives or ready_objectives)
            and all(str(getattr(obj, "type", "") or "").upper() in ITEM_USE_OBJECTIVES
                    for obj in (matching_objectives or ready_objectives)))
        if relevant and item_use_only and not state.get("is_in_combat"):
            # Live 2026-10-04 10:44: "Re-Sizer v9.0.1 tested on Wandering
            # Boars" (USE_ITEM) made the boar combat-relevant and COMBAT (91)
            # charged it before the quest item was used (user: "should not
            # have").  The named unit is for the item; an attacker still
            # triggers DEFEND/COMBAT through the in-combat branch below.
            relevant = False
        credit_gate = quest_domain.credit_gate(
            target.get("guid"), matching_quest_ids, matching_objective_ids, state, now)
        actionbar_reader = getattr(self.registry, "combat_actionbar", None)
        combat_actions = (actionbar_reader(state) if callable(actionbar_reader)
                          else state.get("actionbar", []))
        harmful = [a for a in combat_actions if a.get("is_harmful") is True]
        target_locatable = bool(
            target.get("screen_position") or target_anchor or
            any(action.get("in_range") is True for action in harmful))
        if (relevant and credit_gate is None
                and target.get("attackable", target.get("is_attackable")) is True
                and not target.get("dead", target.get("is_dead"))
                and (state.get("is_in_combat") or target_locatable)):
            proposals.append(Proposal.make(
                "COMBAT", "A quest szövegével/API-val vagy felhasználói céllal egyező target",
                {"guid": target.get("guid"), "quest_ids": matching_quest_ids,
                 "objective_ids": matching_objective_ids}, priority=90))

        ui_error = str(state.get("ui_error") or "").casefold()
        combat_path_blocked = any(token in ui_error for token in (
            "no path", "path not available", "can't reach", "cannot reach"))
        if ((relevant or state.get("is_in_combat"))
                and target.get("attackable") is True and not target.get("dead")):
            if harmful and (all(a.get("in_range") is False for a in harmful)
                            or combat_path_blocked):
                # Issue #95: only GUID-bound evidence (the projected
                # BOUND_WORLD3D_TRACK / nameplate screen_position, or a
                # confirmed mouseover anchor).  The former unbound "best box"
                # fallback could be another mob and the skill gate always
                # rejected it.
                anchor = (target.get("screen_position") or
                          (state.get("confirmed_mouseover_anchors") or {}).get(
                              str(target.get("guid") or "")))
                if anchor:
                    proposals.append(Proposal.make(
                        "VISUAL_APPROACH",
                        "Quest-releváns távoli target folyamatos megközelítése megerősített 3D anchor alapján",
                        {"guid": target.get("guid"), "purpose": "COMBAT",
                         "track_id": anchor.get("track_id"),
                         "visual_signature": anchor.get("visual_signature"),
                         "screen_position": anchor, "quest_ids": matching_quest_ids,
                         "rejected_binding": ((world.runtime_context.get("last_result") or {}).get("last_binding")
                                              if combat_path_blocked else None),
                         "objective_ids": matching_objective_ids},
                        confidence=.9, priority=105))

        if (state.get("is_in_combat")
                and target.get("attackable", target.get("is_attackable")) is True
                and not target.get("dead", target.get("is_dead"))):
            health, maximum = number(state.get("health")), number(state.get("max_health"))
            escape_binding = goal.parameters.get("escape_binding")
            if health is not None and maximum and health/maximum <= .2 and escape_binding:
                proposals.append(Proposal.make(
                    "ESCAPE",
                    "Kritikus életerő; csak a felhasználó által kijelölt menekülési binding használható",
                    {"binding": escape_binding, "duration": .2}, priority=125))
            skill = "COMBAT" if relevant else "DEFEND"
            proposals.append(Proposal.make(
                skill, "Quest-cél elleni harc" if relevant else "Aktív támadó elleni önvédelem",
                {"guid": target.get("guid"), "quest_ids": matching_quest_ids,
                 "objective_ids": matching_objective_ids}, priority=100))
        elif state.get("is_in_combat") and not target:
            proposals.append(Proposal.make(
                "ACQUIRE_TARGET", "Védekezéshez ellenfél kijelölése", priority=100))

        if not state.get("is_in_combat"):
            live = near = None
            corpse = next((item for item in reversed(state.get("confirmed_corpse_anchors", []))
                           if item.get("guid") and number(item.get("x")) is not None
                           and number(item.get("y")) is not None
                           and item.get("ownership_confirmed") is True
                           and not self._reported_empty(state, item.get("guid"))), None)
            if corpse and (not target or target.get("guid") == corpse.get("guid")):
                objectives = self._active_incomplete_objectives(world)
                live, point, near = self._corpse_view(state, corpse)
                corpse = {**corpse, "x": point[0], "y": point[1]}
            if (corpse and (not target or target.get("guid") == corpse.get("guid"))
                    and live is not None and near is False):
                # User 2026-10-01: walk over to the corpse first (same
                # continuous servo, face it), then click its current box.
                proposals.append(Proposal.make(
                    "VISUAL_APPROACH", "Holttest folyamatos megközelítése lootoláshoz",
                    {"purpose": "LOOT", "track_id": live.get("track_id"),
                     "corpse_guid": corpse["guid"], "x": corpse["x"], "y": corpse["y"],
                     "ready_bbox_height": .6, "corpse_anchor": True},
                    confidence=1., priority=108,
                    evidence=tuple(filter(None, (corpse.get("observation_id"),)))))
            elif corpse and (not target or target.get("guid") == corpse.get("guid")):
                proposals.append(Proposal.make(
                    "LOOT", "Addon-tooltip által megerősített holttest lootolása új target keresése előtt",
                    {"guid": corpse["guid"], "x": corpse["x"], "y": corpse["y"],
                     "track_id": (live or {}).get("track_id") or corpse.get("track_id"),
                     "source": corpse.get("source"), "corpse_anchor": True,
                     "quest_ids": list(dict.fromkeys(qid for qid, _ in objectives)),
                     "objective_ids": [oid for _, oid in objectives]},
                    confidence=1., priority=108,
                    evidence=tuple(filter(None, (corpse.get("observation_id"),)))))
            # Live 2026-10-03 13:36: a porcupine killed in melee lay under the
            # character model -- no box, no corpse anchor, no LOOT.  One short
            # step back per corpse reveals it to the hover search.
            soft = self._soft_interact_loot(world, state, now)
            if soft is not None and not any(p.skill in {"LOOT", "VISUAL_APPROACH"}
                                            for p in proposals):
                proposals.append(soft)
            reveal = (None if soft is not None
                      else self._hidden_corpse_reveal(world, state, now))
            if reveal is not None and not any(p.skill in {"LOOT", "VISUAL_APPROACH"}
                                              for p in proposals):
                proposals.append(reveal)
        target_guid = str(target.get("guid") or "")
        active_skill = world.runtime_context.get("active_skill") or {}
        active_combat_target = (
            str(active_skill.get("skill") or "").upper() in {"COMBAT", "DEFEND"}
            and str(active_skill.get("target_guid") or "") == target_guid)
        committed_combat_target = (
            commitment.get("kind") == "TARGET"
            and str(commitment.get("target_guid") or "") == target_guid
            and str(commitment.get("initial_skill") or "").upper()
                in {"COMBAT", "DEFEND"})
        target_owned = (target_guid in set(state.get("owned_corpse_guids") or ())
                        or active_combat_target
                        or committed_combat_target
                        or target.get("lootable") is True
                        or state.get("loot_pending") is True)
        if (target.get("dead", target.get("is_dead")) and target_owned
                and not self._reported_empty(state, target_guid)
                and not world.corpse_was_recently_looted(str(target.get("guid") or ""), now)
                and (state.get("loot_pending") or world.quest_model.ready())):
            objectives = self._active_incomplete_objectives(world)
            # Live 2026-10-07 12:06: at 85 the dead target's LOOT lost to the
            # quest-dot / zone MOVEs (84-92); once walked away the corpse had
            # no position (only the selected target has one) and LOOT failed.
            # Out of combat it is looted first; in combat defence stays first.
            proposals.append(Proposal.make(
                "LOOT", "Halott target lootjának ellenőrzése a quest folytatása előtt",
                {"guid": target.get("guid"),
                 "quest_ids": list(dict.fromkeys(qid for qid, _ in objectives)),
                 "objective_ids": [oid for _, oid in objectives]},
                priority=85 if state.get("is_in_combat") else 107))

        respawn = self._respawn_wait(world, state, target)
        if respawn is not None:
            proposals.append(respawn)
        return CombatPlanningResult(
            tuple(proposals), target, tuple(matching_objectives),
            tuple(matching_quest_ids), tuple(matching_objective_ids))

    RESPAWN_WAIT_SECONDS = 180.

    def _respawn_wait(self, world, state: dict, target: dict) -> Proposal | None:
        """Stay at a killed unique objective unit's spot until it respawns.

        User 2026-10-04: "0/1 Torgok slain" -- if it is not there but its
        corpse is, someone killed it; wait a while for the respawn instead
        of wandering off.  The WAIT outranks area search / travel but not
        INSPECT/TARGET/COMBAT, so the respawned unit is still noticed.
        """
        watch = _model(world).__dict__.get("respawn_watch") or {}
        clock = number(getattr(_model(world), "last_received", None))
        if not watch or clock is None:
            return None
        open_ids = {obj.objective_id for obj in world.quest_model.ready()}
        live_target = (target or {}).get("guid") and not target.get("dead", target.get("is_dead"))
        for objective_id, entry in list(watch.items()):
            if objective_id not in open_ids:
                watch.pop(objective_id, None)
                continue
            waited = clock-(number(entry.get("seen_dead_at")) or clock)
            if waited > self.RESPAWN_WAIT_SECONDS:
                continue
            if live_target and str(target.get("name") or "") == entry.get("name"):
                continue                       # it is back and selected: fight
            return Proposal.make(
                "WAIT", f"{entry.get('name')} halott (valaki megölte): várakozás a respawnra "
                        f"({waited:.0f}/{self.RESPAWN_WAIT_SECONDS:.0f} s)",
                {"waiting_for": ["UNIQUE_TARGET_RESPAWN"], "objective_id": objective_id,
                 "name": entry.get("name")}, priority=82)
        return None

    @staticmethod
    def _reported_empty(state: dict, guid) -> bool:
        """The addon (CanLootUnit) says this corpse has nothing left for us.

        Live 2026-10-03 (Cooking Meat): a Coastal Goat was auto-looted, its
        corpse turned ``lootable=false`` and LOOT was still tried twice more.
        """
        guid = str(guid or "")
        return bool(guid) and any(
            isinstance(unit, dict) and str(unit.get("guid") or "") == guid
            and unit.get("lootable") is False
            for unit in (state.get("mouseover"), state.get("target")))

    @staticmethod
    def _corpse_view(state: dict, corpse: dict):
        """(live box, click point, beside the avatar?) for a confirmed corpse.

        The click point is the lower part of the box (a killed unit lies where
        its feet were), in the anchors' CLIENT_BOTTOM_LEFT convention.  ``near``
        is None when the avatar box is unknown.
        """
        from .self_avatar import is_self_avatar_box
        track_id = corpse.get("track_id")
        live = next((item for item in state.get("visual_candidates") or ()
                     if track_id and item.get("track_id") == track_id
                     and item.get("source") == "WORLD3D"), None)
        if is_self_avatar_box(live):
            # Live 2026-10-02: the corpse lay at the character's feet and its
            # hover point had been bound to the player's own box; clicking
            # that box's lower part right-clicked the player.  Use the exact
            # dead-mouseover point instead.
            return None, (float(corpse["x"]), float(corpse["y"])), None
        box = live or corpse
        edges = VisualApproachController._edges(box)
        if edges is None:
            return live, (float(corpse["x"]), float(corpse["y"])), None
        left, top, right, bottom = edges
        point = ((left+right)/2, 1.-(bottom-.15*(bottom-top)))
        own = VisualApproachController._self_edges(state)
        near = (None if own is None
                else VisualApproachController._beside_self(edges, own, lying=True))
        return live, point, near

    @staticmethod
    def _active_incomplete_objectives(world) -> list[tuple[Any, str]]:
        return [(record.quest_id, obj.objective_id)
                for record in world.quest_model.records.values() for obj in record.objectives
                if record.current_state == "ACTIVE" and obj.completion_state != "COMPLETE"]
