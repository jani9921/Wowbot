"""Read-only, exact quest-item readiness shared by planning and execution.

A selected GUID, a large box or a harmful spell's range cannot authorize F7:
on an attackable unit that same key can start auto-attack instead of item use.
Unknown/publicly unavailable API results stay unknown. No input authority here.
"""
from __future__ import annotations

import math

from .models import number
from wowbot.runtime.skill_identity import check_interaction_recipient
from wowbot.runtime.skill_identity import sample_fresh


class QuestToolResolver:
    MAX_SAMPLE_AGE = .75

    @classmethod
    def self_state(cls, state, item_id, quest_ids, *, now):
        """Usability/cooldown are item facts, including when no unit is selected.

        This deliberately grants no unit range or Interact permission.
        """
        proof = state.get("quest_item_target")
        if not isinstance(proof, dict):
            return None
        sampled, now = number(proof.get("sample_time")), number(now)
        if now is None or sampled is None or not 0 <= now-sampled <= cls.MAX_SAMPLE_AGE:
            return None
        wanted = {str(q) for q in quest_ids or ()}
        return next((row for row in proof.get("items") or () if isinstance(row, dict)
                     and str(row.get("quest_id")) in wanted and row.get("item_id") == item_id), None)

    @staticmethod
    def self_ready(row):
        cooldown = number((row or {}).get("cooldown_remaining"))
        return bool(row and row.get("is_usable") is True and cooldown is not None and 0 <= cooldown <= .1)

    @staticmethod
    def selected_objective(state: dict, objectives, *, now=None):
        """Fresh selected item subject; the existing local skills own it."""
        from .quest_semantics import entity_constraints_allow, subject_matches_name, use_on_subjects
        target = state.get("target") or {}
        now = number(state.get("monotonic_time")) if now is None else number(now)
        if (not target.get("guid") or not target.get("name") or target.get("dead") is True
                or target.get("is_dead") is True or now is None or not sample_fresh(state, "target", now)):
            return None
        for obj in objectives:
            if (getattr(obj, "target_object", None) or {}).get("item_id") is None:
                continue
            subjects = use_on_subjects({**(getattr(obj, "raw", None) or {}),
                                       "description": getattr(obj, "description", "")})
            if (subjects and subject_matches_name(subjects, target["name"])
                    and entity_constraints_allow(target, getattr(obj, "target_entity", None))):
                return obj
        return None

    @classmethod
    def item_state(cls, state: dict, item_id, guid, quest_ids=(), *, now=None) -> dict | None:
        proof = state.get("quest_item_target")
        if not isinstance(proof, dict) or not guid or proof.get("guid") != guid:
            return None
        target = state.get("target") or {}
        if target.get("guid") != guid or target.get("dead") is True or target.get("is_dead") is True:
            return None
        now = number(state.get("monotonic_time")) if now is None else number(now)
        sampled = number(proof.get("sample_time"))
        if (now is None or sampled is None or not math.isfinite(now) or not math.isfinite(sampled)
                or not 0 <= now-sampled <= cls.MAX_SAMPLE_AGE):
            return None
        wanted_quests = {str(value) for value in quest_ids or ()}
        authorized = {str(q.get("quest_id")) for q in state.get("active_quests") or ()
                      if isinstance(q, dict) and q.get("is_complete") is not True
                      and str((q.get("special_item") or {}).get("item_id")) == str(item_id)
                      and (not wanted_quests or str(q.get("quest_id")) in wanted_quests)}
        return next((row for row in proof.get("items") or () if isinstance(row, dict)
                     and str(row.get("quest_id")) in authorized
                     and str(row.get("item_id")) == str(item_id)), None)

    @staticmethod
    def ready(row: dict | None) -> bool:
        cooldown = number((row or {}).get("cooldown_remaining"))
        return bool(row and row.get("in_range") is True and row.get("is_usable") is True
                    and cooldown is not None and math.isfinite(cooldown) and 0 <= cooldown <= .1)

    @classmethod
    def can_interact(cls, state: dict, item_id, guid, quest_ids=(), *, now=None) -> bool:
        now = number(state.get("monotonic_time")) if now is None else number(now)
        return bool(cls.ready(cls.item_state(state, item_id, guid, quest_ids, now=now))
                    and now is not None
                    and check_interaction_recipient({"guid": guid}, state, now))
