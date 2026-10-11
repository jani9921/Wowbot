"""Evidence-gated orchestration for quest world-object interaction.

This policy owns no input and invents no object semantics.  It connects the
existing location, bounded visual-search and ``OBJECT_USE`` stages by carrying
the objective's explicit identity through active perception.  Addon mouseover
is the confirmation boundary; raw CV candidates remain UNKNOWN.
"""
from __future__ import annotations

from .models import Proposal, number, words
from .quest_semantics import world_object_subjects


def _stems(text: str) -> list[str]:
    """Words without a plural ending: "cocoons" and "Thick Cocoon" meet."""
    stems = []
    for word in words(str(text or "")).split():
        stems.append(word[:-2] if word.endswith("es") and len(word) > 4 else
                     word[:-1] if word.endswith("s") and len(word) > 3 else word)
    return stems


def name_matches(subjects, name) -> bool:
    name_stems = set(_stems(name))
    return bool(name_stems) and any(
        subject_stems and set(subject_stems) <= name_stems
        for subject_stems in (_stems(subject) for subject in subjects or ()))


# User 2026-10-06: the cocoon's quest_object_like track was ACTIVE at .25,
# but the former .55 gate discarded it.  This lower gate is ONLY for that
# learned object class; overhead/quest symbols retain their own thresholds.
# The box only authorizes approach/hover, never use without addon identity.
QUEST_OBJECT_MIN_CONFIDENCE = .20
QUEST_OBJECT_MIN_STABLE = 3


def quest_object_candidates(state: dict) -> list[dict]:
    """World3D boxes of the learned ``quest_object_outline_like`` class (user-
    labelled cocoons etc.), stable enough to walk to, largest first."""
    found = []
    for item in state.get("visual_candidates") or ():
        if not isinstance(item, dict) or item.get("source") != "WORLD3D":
            continue
        labels = {str(value).lower() for value in item.get("candidate_labels") or ()}
        appearance = item.get("appearance") if isinstance(item.get("appearance"), dict) else {}
        labels.update(str(value).lower() for value in appearance.get("anchor_candidate_labels") or ())
        lifecycle = str(item.get("lifecycle") or item.get("track_state") or "ACTIVE").upper()
        if ("quest_object_like" not in labels or lifecycle in {"LOST", "REJECTED", "TERMINATED"}
                or (number(item.get("confidence")) or 0.) < QUEST_OBJECT_MIN_CONFIDENCE
                or (number(item.get("stable_frames")) or 0.) < QUEST_OBJECT_MIN_STABLE):
            continue
        found.append(item)
    return sorted(found, key=lambda item: -(number(item.get("bbox_height_fraction")) or 0.))


def only_object_objectives_open(state: dict) -> bool:
    """Every open objective of every unfinished quest is a game object.

    Live 2026-10-06 (Hrun's pit): the cocoon sweep stopped to hover another
    player's hunter pet, torches and spiders.  While only objects are
    wanted, a unit body without a quest symbol answers nothing; a finished
    quest (turn-in NPC) or any other objective type keeps units relevant.
    """
    found = False
    for quest in state.get("active_quests") or ():
        if not isinstance(quest, dict):
            continue
        if quest.get("is_complete") is True:
            return False
        for objective in quest.get("objectives") or ():
            if not isinstance(objective, dict) or objective.get("is_complete"):
                continue
            if str(objective.get("raw_type") or "").lower() != "object":
                return False
            found = True
    return found


def open_object_objective(state: dict, quest_id=None) -> bool:
    """An unfinished game-object objective (raw type ``object``) is open."""
    for quest in state.get("active_quests") or ():
        if not isinstance(quest, dict) or quest.get("is_complete") is True:
            continue
        if quest_id is not None and str(quest.get("quest_id")) != str(quest_id):
            continue
        if any(isinstance(objective, dict) and not objective.get("is_complete")
               and str(objective.get("raw_type") or "").lower() == "object"
               for objective in quest.get("objectives") or ()):
            return True
    return False


class ObjectInteractionFlow:
    """Compose locate -> local search -> validate -> use -> credit verify."""

    # Visual scale is diagnostic only for a hovered quest object: live 18:28
    # showed a .10-height cocoon that was usable.  Client range feedback,
    # followed by bounded forward pulses, owns the retry decision.
    OBJECT_READY_HEIGHT = .16

    @staticmethod
    def _hover_identity(state: dict) -> tuple[str, str] | None:
        from .tooltip_quest import effective_mouseover
        mouse = effective_mouseover(state)
        key = (str(mouse.get("quest_id") or ""),
               str(mouse.get("object_id") or mouse.get("name")
                   or mouse.get("unit_name") or "").casefold())
        return key if any(key) else None

    @staticmethod
    def _confirmed_hover_box(identity: dict, quest_id, state: dict,
                             boxes: list[dict]) -> dict | None:
        """Bind a current addon-confirmed object hover to one live visual box.

        A learned outline alone is never authority to walk toward scenery.
        The pointer, mouseover and box must agree in this same fresh view.
        """
        from .tooltip_quest import effective_mouseover
        now = number(state.get("monotonic_time"))
        mouse_at = number(state.get("mouseover_sample_time"))
        cursor_at = number(state.get("cursor_sample_time"))
        cursor = state.get("cursor_position") or {}
        cx, cy = number(cursor.get("nx")), number(cursor.get("ny"))
        mouse = effective_mouseover(state)
        if (None in (now, mouse_at, cursor_at, cx, cy)
                or not 0 <= now-mouse_at <= .75
                or not 0 <= now-cursor_at <= .75
                or abs(mouse_at-cursor_at) > .1
                or mouse.get("quest_related") is not True
                or str(mouse.get("quest_id")) != str(quest_id)
                or not ObjectInteractionFlow.mouseover_matches(identity, mouse)):
            return None
        for box in boxes:
            bx, by = number(box.get("x")), number(box.get("y"))
            observed = number(box.get("observed_at", box.get("last_seen")))
            if (None in (bx, by, observed)
                    or not 0 <= now-observed <= .8
                    or str(box.get("lifecycle") or box.get("track_state") or "ACTIVE").upper()
                    not in {"ACTIVE", "STABLE"}):
                continue
            width = number(box.get("bbox_width_fraction")) or 0.
            height = number(box.get("bbox_height_fraction")) or 0.
            if (abs(cx-bx) <= max(.025, width*.75)
                    and abs(cy-by) <= max(.025, height*.6)):
                return box
        return None

    def object_ready_height(self) -> float:
        return float(self.__dict__.get("_ready_height") or self.OBJECT_READY_HEIGHT)

    def note_result(self, last_result: dict | None, state: dict) -> None:
        """Learn once per finished action from an object use's range error."""
        last = last_result if isinstance(last_result, dict) else {}
        action = last.get("action_id")
        if not action or action == self.__dict__.get("_noted_action"):
            return
        self._noted_action = action
        if (last.get("skill") == "OBJECT_USE"
                and "range" in str(last.get("reason") or "").lower()):
            identity = self._hover_identity(state)
            if identity is not None and identity != self.__dict__.get("_range_failure_identity"):
                self._range_failure_count = 0
                self._range_failure_identity = identity
            self._range_failure_count = min(3, int(self.__dict__.get("_range_failure_count") or 0)+1)
            height = max((number(box.get("bbox_height_fraction")) or 0.
                          for box in quest_object_candidates(state)), default=0.)
            self._ready_height = min(.6, max(self.object_ready_height()*1.25, height*1.3))
            self._range_blocked_at = number(state.get("monotonic_time"))
            cursor = state.get("cursor_position") or {}
            position = state.get("player_world_position") or {}
            self._range_blocked_cursor = (number(cursor.get("nx")), number(cursor.get("ny")))
            self._range_blocked_position = (position.get("instance_id"),
                                            number(position.get("x")), number(position.get("y")))
        elif (last.get("skill") == "OBJECT_USE"
              and "line_of_sight" in str(last.get("reason") or "").lower()):
            cursor = state.get("cursor_position") or {}
            position = state.get("player_world_position") or {}
            self._los_blocked_cursor = (number(cursor.get("nx")), number(cursor.get("ny")))
            self._los_blocked_position = (position.get("instance_id"),
                                          number(position.get("x")), number(position.get("y")))
        elif (last.get("skill") in {"VISUAL_APPROACH", "MOVE"}
              and last.get("outcome") == "SUCCESS"):
            self._range_blocked_at = None          # movement, not hover, permits retry
        if last.get("skill") == "OBJECT_USE" and last.get("outcome") == "SUCCESS":
            self._los_blocked_cursor = None
            self._range_blocked_at = None
            self._range_failure_count = 0
            self._range_failure_identity = None
            cursor = state.get("cursor_position") or {}
            self._credited = (number(state.get("monotonic_time")),
                              number(cursor.get("nx")), number(cursor.get("ny")))

    CREDITED_HOLD_SECONDS = 3.
    CREDITED_CURSOR_RADIUS = .04

    def just_credited(self, state: dict) -> bool:
        """The object under the unmoved cursor was just credited.

        Live 2026-10-07 12:06: the FAST quest digest verified the 5th cocoon;
        the paged snapshot still showed 4/5 and the tooltip still named the
        cocoon, so a second OBJECT_USE right-clicked the freed prisoner
        ("Invalid target")."""
        credited = self.__dict__.get("_credited")
        now = number(state.get("monotonic_time"))
        cursor = state.get("cursor_position") or {}
        cx, cy = number(cursor.get("nx")), number(cursor.get("ny"))
        if not credited or None in (credited[0], now, cx, cy):
            return False
        at, x, y = credited
        near = x is None or y is None or abs(cx-x) + abs(cy-y) <= self.CREDITED_CURSOR_RADIUS
        return 0 <= now-at <= self.CREDITED_HOLD_SECONDS and near

    def range_blocked(self, state: dict) -> bool:
        """A range error remains until movement or a different object cue."""
        blocked = number(self.__dict__.get("_range_blocked_at"))
        if blocked is None:
            return False
        original_cursor = self.__dict__.get("_range_blocked_cursor") or (None, None)
        cursor = state.get("cursor_position") or {}
        cx, cy = number(cursor.get("nx")), number(cursor.get("ny"))
        if (None not in (*original_cursor, cx, cy)
                and abs(cx-original_cursor[0])+abs(cy-original_cursor[1]) > .06):
            # Camera movement slides the same cocoon under a new cursor
            # coordinate.  A new coordinate alone is not evidence that the
            # client's range error no longer applies to this object.
            current_identity = self._hover_identity(state)
            failed_identity = self.__dict__.get("_range_failure_identity")
            if (current_identity is not None and failed_identity is not None
                    and current_identity != failed_identity):
                self._range_blocked_at = None
                return False
        previous = self.__dict__.get("_range_blocked_position") or (None, None, None)
        position = state.get("player_world_position") or {}
        px, py = number(position.get("x")), number(position.get("y"))
        if (previous[0] is not None and position.get("instance_id") is not None
                and position.get("instance_id") != previous[0]):
            self._range_blocked_at = None
            return False
        if (None not in (previous[1], previous[2], px, py)
                and (px-previous[1])**2+(py-previous[2])**2 >= 4.):
            self._range_blocked_at = None
            return False
        return True

    def line_of_sight_blocked(self, state: dict) -> bool:
        """Do not retry the same obstructed click without a changed position/cue.

        Moving to a different object (cursor) or walking at least two yards
        permits a fresh attempt; repeated hover at the same wall does not.
        """
        original = self.__dict__.get("_los_blocked_cursor")
        if original is None:
            return False
        cursor = state.get("cursor_position") or {}
        cx, cy = number(cursor.get("nx")), number(cursor.get("ny"))
        if None not in (*original, cx, cy) and abs(cx-original[0])+abs(cy-original[1]) > .06:
            self._los_blocked_cursor = None
            return False
        previous = self.__dict__.get("_los_blocked_position") or (None, None, None)
        position = state.get("player_world_position") or {}
        px, py = number(position.get("x")), number(position.get("y"))
        if (previous[0] is not None and position.get("instance_id") is not None
                and position.get("instance_id") != previous[0]):
            self._los_blocked_cursor = None
            return False
        if (None not in (previous[1], previous[2], px, py)
                and position.get("instance_id") == previous[0]
                and (px-previous[1])**2+(py-previous[2])**2 >= 4.):
            self._los_blocked_cursor = None
            return False
        return True

    @staticmethod
    def expected_identity(objective) -> dict:
        target = dict(getattr(objective, "target_object", {}) or {})
        raw = getattr(objective, "raw", {}) or {}
        subjects = world_object_subjects({**raw, "description": getattr(objective, "description", "")})
        if raw.get('tdb_object_name'):
            subjects = list(dict.fromkeys([raw['tdb_object_name'], *subjects]))
        return {
            "object_id": target.get("object_id") or raw.get('tdb_object_id'),
            "item_id": target.get("item_id"),
            "expected_tooltips": subjects,
            "tdb_object_name": raw.get('tdb_object_name'),
        }

    @staticmethod
    def mouseover_matches(identity: dict, mouseover: dict) -> bool:
        """Accept explicit IDs first; textual identity only when no ID exists."""
        if identity.get("object_id") is not None:
            observed_id = mouseover.get('object_id')
            if observed_id not in (None, '', 0, '0'):
                return str(observed_id) == str(identity['object_id'])
            # Retail's object tooltip/FAST mouseover can lack an object ID.
            # Only the exact TDB GO template name may confirm that case;
            # generic objective words such as "cocoon" are insufficient.
            expected = words(str(identity.get('tdb_object_name') or '')).strip()
            hovered = (mouseover.get('unit_name') or mouseover.get('name')
                       or str(mouseover.get('tooltip') or '').split('~', 1)[0])
            return bool(expected and words(str(hovered)).strip() == expected)
        if identity.get("item_id") is not None:
            return str(mouseover.get("item_id")) == str(identity["item_id"])
        tooltip = f" {words(str(mouseover.get('tooltip') or '')).strip()} "
        subjects = [words(str(value)).strip() for value in identity.get("expected_tooltips") or ()]
        name = mouseover.get("unit_name") or mouseover.get("name")
        if tooltip.strip():
            return bool(any(value and f" {value} " in tooltip for value in subjects)
                        or name_matches(subjects, name))
        # The FAST lane carries the current structured game-object name even
        # when the long tooltip is dropped to fit one pixel-grid packet.
        return mouseover.get("quest_related") is True and name_matches(subjects, name)

    @staticmethod
    def quest_mouseover_matches(identity: dict, mouseover: dict,
                                state: dict, quest_id) -> bool:
        """Identity plus a live link to this open quest, not name alone."""
        if quest_id is None or not ObjectInteractionFlow.mouseover_matches(identity, mouseover):
            return False
        # An explicit current object ID is stronger than a quest-title
        # tooltip, which the addon may omit on its narrow FAST packet.
        if (identity.get('object_id') is not None
                and mouseover.get('object_id') not in (None, '', 0, '0')):
            return True
        if not identity.get('tdb_object_name'):
            # A tool object (the campfire of "Cook the meat", credit = an
            # item) never carries a quest line; only an object that is itself
            # the TDB GAMEOBJECT credit loses it once used for this character.
            return bool(mouseover.get("tooltip")
                        or str(mouseover.get("quest_id")) == str(quest_id))
        if (mouseover.get('quest_related') is True
                and str(mouseover.get('quest_id')) == str(quest_id)):
            return True
        from .tooltip_quest import tooltip_quest_id
        inferred = tooltip_quest_id(mouseover, state)
        return inferred is not None and str(inferred) == str(quest_id)

    @staticmethod
    def soft_target(identity: dict, state: dict) -> dict | None:
        """The soft-interact game object (addon 0.9.57) when it is the objective's."""
        for target in state.get("soft_targets") or ():
            if not isinstance(target, dict) or target.get("unit_type") != "GAMEOBJECT":
                continue
            if identity.get("object_id") is not None:
                if str(target.get("object_id")) == str(identity["object_id"]):
                    return target
                continue
            if name_matches(identity.get("expected_tooltips"), target.get("name")):
                return target
        return None

    def propose_object_steps(self, objective, record, state: dict) -> list[Proposal]:
        """User 2026-10-06 (cocoons): the learned quest-object box is seen,
        the soft-interact target or the hovered tooltip is the object: walk
        to it, hover it, use it -- above the zone sweep and the dot walk."""
        identity = self.expected_identity(objective)
        quest_ids = [getattr(record, "quest_id", None) or objective.objective_id.split(":", 1)[0]]
        steps = []
        boxes = quest_object_candidates(state)
        if self.line_of_sight_blocked(state):
            return []
        confirmed = self._confirmed_hover_box(identity, quest_ids[0], state, boxes)
        # Live 2026-10-07 12:58: the right-click returned "You are too far
        # away"; SEEK then hovered the same .10-height cocoon repeatedly
        # without moving.  A *client* range error requires an approach.
        # Box height alone is not a range test: the 18:28 live run had a
        # correctly named, hovered small box that the user could use.
        # Let the normal fresh-hover OBJECT_USE try once before any range
        # error; its verified failure can then bind this approach to a box.
        if confirmed is not None and self.range_blocked(state):
            return [Proposal.make(
                "VISUAL_APPROACH", "Megerősített quest-objektumhoz közelebb lépek használat előtt",
                {"purpose": "INTERACT", "object_use_approach": True,
                 "track_id": confirmed.get("track_id"),
                 "visual_signature": confirmed.get("visual_signature"),
                 "expected_tooltips": identity.get("expected_tooltips"),
                 "object_id": identity.get("object_id"),
                 "item_id": identity.get("item_id"),
                 "quest_ids": quest_ids, "objective_id": objective.objective_id,
                 "ready_bbox_height": self.object_ready_height(),
                 "range_failures": max(1, int(self.__dict__.get("_range_failure_count") or 0)),
                 "max_seconds": 8.},
                confidence=.85, priority=96,
                evidence=("fresh_quest_object_mouseover", "live_visual_box"))]
        if boxes:
            box = boxes[0]
            steps.append(Proposal.make(
                "SEEK_VISUAL_CUE", "Látott quest-objektum (gubó): odamegyek és rámutatok",
                {"purpose": "SEARCH_LOCAL_OBJECT", "search_capability": "SEARCH_LOCAL_OBJECT",
                 "track_id": box.get("track_id"), "visual_signature": box.get("visual_signature"),
                 "query": next(iter(identity.get("expected_tooltips") or ()), "quest object"),
                 "search_area": {"track_id": box.get("track_id")},
                 "quest_id": quest_ids[0], "objective_id": objective.objective_id,
                 "objective_type": getattr(objective, "type", None),
                 **identity, "scan_budget": 2, "time_budget": 15.,
                 "ready_bbox_height": self.object_ready_height()},
                confidence=.8, priority=93 if self.range_blocked(state) else 90,
                evidence=("learned_quest_object_box",)))
        soft = self.soft_target(identity, state)
        if soft is not None and not self.range_blocked(state):
            steps.append(Proposal.make(
                "OBJECT_USE", "Quest-objektum soft-interact célpontban: ellenőrzött F7 tartalék",
                {"activation_source": "INTERACT_KEY", "binding": "INTERACTTARGET",
                 "object_guid": soft.get("guid"), "object_id": soft.get("object_id"),
                 "object_name": soft.get("name"), "objective_id": objective.objective_id,
                 "quest_ids": quest_ids},
                # Issue #99: an identity-matched soft-interact object is in
                # range now; the visible-box SEEK (90/93) used to starve this
                # verified use.  Quest credit is still verified by the skill.
                confidence=.85, priority=95, evidence=("soft_interact_object",)))
        return steps

    def propose_local_search(self, objective, record, search_area: dict) -> list[Proposal]:
        identity = self.expected_identity(objective)
        query = next(iter(identity.get("expected_tooltips") or ()), None)
        query = str(query or identity.get("object_id") or identity.get("item_id")
                    or getattr(objective, "description", "") or "quest world object")
        return [Proposal.make(
            "SEEK_VISUAL_CUE",
            "Quest-object terület elérve: UNKNOWN cue megközelítése és addon-mouseover azonosítás",
            {"purpose": "SEARCH_LOCAL_OBJECT", "search_capability": "SEARCH_LOCAL_OBJECT",
             "query": query, "search_area": dict(search_area),
             "quest_id": getattr(record, "quest_id", None),
             "objective_id": getattr(objective, "objective_id", None),
             "objective_type": getattr(objective, "type", None),
             **identity, "scan_budget": 4, "time_budget": 22.,
             "ready_bbox_height": .09},
            confidence=max(.6, float(getattr(objective, "confidence", 0.) or 0.)),
            priority=66,
            evidence=("objective_search_area_reached", "object_identity_not_yet_confirmed"))]

