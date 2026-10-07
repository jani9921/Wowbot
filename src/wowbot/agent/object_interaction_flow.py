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

    # Approach until the quest-object box is this tall before using it.  The
    # client's "You are too far away." raises it (live 2026-10-06 21:16: a
    # cocoon hovered from a ledge above; the credited one was ~.19-.24 tall).
    OBJECT_READY_HEIGHT = .12
    OBJECT_RANGE_BLOCK_SECONDS = 6.

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
            height = max((number(box.get("bbox_height_fraction")) or 0.
                          for box in quest_object_candidates(state)), default=0.)
            self._ready_height = min(.6, max(self.object_ready_height()*1.25, height*1.3))
            self._range_blocked_at = number(state.get("monotonic_time"))
        elif (last.get("skill") in {"SEEK_VISUAL_CUE", "VISUAL_APPROACH", "MOVE"}
              and last.get("outcome") == "SUCCESS"):
            self._range_blocked_at = None          # walked closer: try the use again

    def range_blocked(self, state: dict) -> bool:
        """A use just failed "too far": approach first, do not click again."""
        blocked, now = number(self.__dict__.get("_range_blocked_at")), number(state.get("monotonic_time"))
        return (blocked is not None and now is not None
                and 0 <= now-blocked <= self.OBJECT_RANGE_BLOCK_SECONDS)

    @staticmethod
    def expected_identity(objective) -> dict:
        target = dict(getattr(objective, "target_object", {}) or {})
        raw = getattr(objective, "raw", {}) or {}
        subjects = world_object_subjects({**raw, "description": getattr(objective, "description", "")})
        return {
            "object_id": target.get("object_id"),
            "item_id": target.get("item_id"),
            "expected_tooltips": subjects,
        }

    @staticmethod
    def mouseover_matches(identity: dict, mouseover: dict) -> bool:
        """Accept explicit IDs first; textual identity only when no ID exists."""
        if identity.get("object_id") is not None:
            return str(mouseover.get("object_id")) == str(identity["object_id"])
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
        if soft is not None:
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

