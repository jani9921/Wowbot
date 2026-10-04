"""Canonical bounded M0 loot FSM."""
from __future__ import annotations

from enum import StrEnum

from wowbot.agent.models import Command, number
from .hover_confirm import CORPSE_SEARCH_OFFSETS, hover_confirm_step
from wowbot.runtime import ActiveSkillState, FailureReason, SkillResult, SkillStatus, world_entity_id
from wowbot.verification.loot import LootVerifier


class LootPhase(StrEnum):
    CONFIRM_HOVER = "CONFIRM_HOVER"
    LOCATE_CORPSE = "LOCATE_CORPSE"
    APPROACH = "APPROACH"
    INTERACT = "INTERACT"
    WAIT_LOOT_STATE = "WAIT_LOOT_STATE"
    VERIFY = "VERIFY"


def soft_interact_corpse(world_state: dict, corpse_guid) -> bool:
    """The client's soft-interact unit is exactly this dead corpse.

    Live 2026-10-03 13:46:09: right after the kill the addon reported
    ``softinteract`` = the dead Coastal Goat (exact GUID) while the corpse
    hover search missed it.  The interact key then acts on that unit with no
    screen position; LootVerifier still has to see the loot.  Used only with
    no other unit selected (a hard target would take the key).
    """
    if not corpse_guid:
        return False
    target_guid = str((world_state.get("target") or {}).get("guid") or "")
    if target_guid and target_guid != str(corpse_guid):
        return False
    return any(isinstance(row, dict) and str(row.get("source_unit") or "").casefold() == "softinteract"
               and str(row.get("guid") or "") == str(corpse_guid)
               and row.get("is_dead", row.get("dead")) is True
               for row in world_state.get("soft_targets") or ())


class LootSkill:
    def __init__(self, verifier: LootVerifier | None = None):
        self.verifier = verifier or LootVerifier()

    def begin(self, state: ActiveSkillState, world_state: dict) -> SkillResult:
        params, target = state.intent.parameters, world_state.get("target") or {}
        corpse_guid = world_entity_id(state.intent.target_ref or params.get("guid"))
        raw_expected = params.get("expected_item_ids", params.get("expected_item_id"))
        if raw_expected is None:
            expected_item_ids = ()
        elif isinstance(raw_expected, (list, tuple, set)):
            expected_item_ids = tuple(int(item_id) for item_id in raw_expected)
        else:
            expected_item_ids = (int(raw_expected),)
        state.skill_context["loot"] = {"corpse_guid": corpse_guid,
                                        "expected_item_ids": expected_item_ids}
        state.phase = LootPhase.LOCATE_CORPSE.value
        if soft_interact_corpse(world_state, corpse_guid):
            state.skill_context["loot"]["via"] = "SOFT_INTERACT"
            state.phase = LootPhase.INTERACT.value
            return SkillResult(SkillStatus.RUNNING, commands=(Command("BIND", "INTERACTTARGET"),),
                               metadata={"loot_via": "SOFT_INTERACT"})
        if params.get("corpse_anchor"):
            x, y = number(params.get("x")), number(params.get("y"))
            if x is None or y is None or not (0 < x < 1 and 0 < y < 1):
                return SkillResult(SkillStatus.FAILURE, FailureReason.CORPSE_NOT_FOUND,
                                   replan_required=True)
            mouse = world_state.get("mouseover") or {}
            if (corpse_guid and str(mouse.get("guid") or "") == str(corpse_guid)
                    and mouse.get("lootable") is not False):
                # Live 13:46:08: the cursor already rested on the corpse
                # ("Coastal Goat Corpse") and LOOT moved it away to hover the
                # remembered point.  Click where it is.
                state.skill_context["loot"].update(hover_point=(x, y), hovers=1)
                state.phase = LootPhase.INTERACT.value
                return SkillResult(SkillStatus.RUNNING,
                                   commands=(Command("CLICK_CURRENT_CURSOR", button="RIGHT"),))
            if corpse_guid:
                # Hover the corpse first; right-click only once the addon
                # names it (and does not report it empty).
                state.skill_context["loot"].update(
                    hover_point=(x, y), track_id=params.get("track_id"),
                    hovers=1, hovered_at=state.started_at, hover_pending=True)
                state.phase = LootPhase.CONFIRM_HOVER.value
                return SkillResult(SkillStatus.RUNNING,
                                   commands=(Command("HOVER", x=x, y=y, duration=.05),))
            commands = (Command("CLICK", x=x, y=y, button="RIGHT"),)
        else:
            if corpse_guid and target.get("guid") != corpse_guid:
                return SkillResult(SkillStatus.FAILURE, FailureReason.TARGET_LOST,
                                   retryable=True, replan_required=True)
            if target.get("dead", target.get("is_dead")) is not True:
                return SkillResult(SkillStatus.FAILURE, FailureReason.NOT_LOOTABLE,
                                   replan_required=True)
            commands = (Command("BIND", "INTERACTTARGET"),)
        state.phase = LootPhase.INTERACT.value
        return SkillResult(SkillStatus.RUNNING, commands=commands)

    @staticmethod
    def _world_approach_request(world_state: dict, corpse_guid: str | None) -> dict | None:
        target = world_state.get("target") or {}
        player, position = world_state.get("player_world_position") or {}, target.get("world_position") or {}
        if (not corpse_guid or str(target.get("guid") or "") != str(corpse_guid)
                or target.get("dead", target.get("is_dead")) is not True):
            return None
        if None in {number(player.get("x")), number(player.get("y")),
                    number(position.get("x")), number(position.get("y"))}:
            return None
        player_instance, corpse_instance = player.get("instance_id"), position.get("instance_id")
        if (player_instance is not None and corpse_instance is not None
                and player_instance != corpse_instance):
            return None
        return {"kind": "WORLD_CORPSE", "corpse_guid": str(corpse_guid), "stop_distance": 3.5}

    def resume_after_approach(self, state: ActiveSkillState, world_state: dict) -> SkillResult:
        context = state.skill_context.setdefault("loot", {})
        corpse_guid = context.get("corpse_guid")
        target = world_state.get("target") or {}
        if (not corpse_guid or str(target.get("guid") or "") != str(corpse_guid)
                or target.get("dead", target.get("is_dead")) is not True):
            return SkillResult(SkillStatus.FAILURE, FailureReason.CORPSE_NOT_FOUND,
                               retryable=True, replan_required=True)
        context.pop("approach_request", None)
        state.phase = LootPhase.INTERACT.value
        return SkillResult(SkillStatus.RUNNING, commands=(Command("BIND", "INTERACTTARGET"),),
                           metadata={"post_approach_loot": True})

    def verify(self, state: ActiveSkillState, world_state: dict, now: float) -> SkillResult:
        corpse_guid = (state.skill_context.get("loot") or {}).get("corpse_guid")
        if (state.skill_context.get("loot") or {}).get("hover_pending"):
            context = state.skill_context.setdefault("loot", {})
            # Loot that arrives anyway (auto-loot, an earlier click) wins.
            early = self.verifier.evaluate(
                state.before_snapshot, world_state, corpse_guid=corpse_guid,
                expected_item_ids=tuple(context.get("expected_item_ids") or ()))
            if early.success:
                context["hover_pending"] = False
                return SkillResult(SkillStatus.SUCCESS, evidence=early.evidence)
            if soft_interact_corpse(world_state, corpse_guid) and not context.get("soft_interact_sent"):
                context["hover_pending"] = False
                context["soft_interact_sent"] = True
                state.phase = LootPhase.INTERACT.value
                return SkillResult(SkillStatus.RUNNING, commands=(Command("BIND", "INTERACTTARGET"),),
                                   metadata={"loot_via": "SOFT_INTERACT"})
            outcome, commands = hover_confirm_step(context, world_state, now,
                                                   expected_guid=str(corpse_guid or ""),
                                                   click_button="RIGHT", lower=True,
                                                   max_hovers=len(CORPSE_SEARCH_OFFSETS),
                                                   search_offsets=CORPSE_SEARCH_OFFSETS)
            if outcome == "CLICK":
                context["hover_pending"] = False
                state.phase = LootPhase.INTERACT.value
                return SkillResult(SkillStatus.RUNNING, commands=commands)
            if outcome == "HOVER":
                return SkillResult(SkillStatus.RUNNING, commands=commands)
            if outcome == "EMPTY":
                return SkillResult(SkillStatus.FAILURE, FailureReason.NOT_LOOTABLE,
                                   replan_required=True,
                                   metadata={"detail": "addon reports the corpse empty"})
            if outcome == "WAIT" and now < state.attempt.deadline:
                return SkillResult(SkillStatus.RUNNING)
            return SkillResult(SkillStatus.FAILURE, FailureReason.CORPSE_NOT_FOUND,
                               retryable=True, replan_required=True)
        expected_item_ids = tuple((state.skill_context.get("loot") or {}).get("expected_item_ids") or ())
        state.phase = LootPhase.VERIFY.value
        result = self.verifier.evaluate(state.before_snapshot, world_state, corpse_guid=corpse_guid,
                                        expected_item_ids=expected_item_ids)
        if result.success:
            return SkillResult(SkillStatus.SUCCESS, evidence=result.evidence)
        if result.reason is FailureReason.OUT_OF_RANGE:
            context = state.skill_context.setdefault("loot", {})
            if context.get("approach_attempts", 0) < 1:
                request = self._world_approach_request(world_state, corpse_guid)
                if request:
                    context["approach_attempts"] = context.get("approach_attempts", 0) + 1
                    context["approach_request"] = request
                    state.local_retry_count += 1
                    state.failure_history.append(FailureReason.OUT_OF_RANGE)
                    state.phase = LootPhase.APPROACH.value
                    return SkillResult(SkillStatus.RUNNING, metadata={"approach_request": request})
        if result.reason is not None:
            return SkillResult(SkillStatus.FAILURE, result.reason,
                               retryable=result.retry_recommended, replan_required=True)
        if now >= state.attempt.deadline:
            terminal_reason = (FailureReason.EXPECTED_ITEM_NOT_RECEIVED
                               if expected_item_ids else FailureReason.LOOT_UI_NOT_OPENED)
            return SkillResult(SkillStatus.FAILURE, terminal_reason,
                               retryable=True, replan_required=True)
        return SkillResult(SkillStatus.RUNNING)
