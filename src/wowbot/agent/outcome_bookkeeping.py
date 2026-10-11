"""Bounded compatibility state updates after a verified attempt outcome."""
from __future__ import annotations

from .interaction_range import recently_verified_in_range

from .models import Attempt, Goal, Outcome


class AttemptOutcomeBookkeeper:
    """Project terminal counters/backoff; never verify, dispatch or finalize."""

    @staticmethod
    def apply(attempt: Attempt, outcome: Outcome, reason: str, now: float, *,
              goal: Goal, world, planner, failures: dict,
              failure_manager, loop_guard, retries,
              failure_decision=None) -> None:
        key = attempt.proposal.key
        skill = attempt.proposal.skill
        parameters = attempt.proposal.parameters
        if outcome == Outcome.SUCCESS:
            goal.completed_steps += 1
            failures[key] = 0
            failure_manager.record_success(key)
            loop_guard.clear_prefix(
                f"{skill}:{parameters.get('guid') or key}:")
            clear_subject = getattr(loop_guard, "clear_subject", None)
            if clear_subject is not None:
                clear_subject(
                    skill, str(parameters.get("guid") or parameters.get("entity_id")
                               or parameters.get("target_guid") or parameters.get("track_id")
                               or parameters.get("marker_id") or parameters.get("objective_id")
                               or parameters.get("quest_id") or key))
            if skill == "LOOT":
                planner.blocked_until[key] = now + 60
                world.mark_corpse_looted(parameters.get("guid"), now)
                # Retail area loot empties every own corpse nearby with the
                # one opened (live 2026-10-01: the remaining corpses then
                # failed loot_ui_not_opened).  Retire the other recent kills
                # around the opened corpse (issue #91: not distant ones).
                area = getattr(world, "mark_area_looted", None)
                if callable(area):
                    area(now, window=30., origin_guid=parameters.get("guid"))
            elif skill in {"COMBAT", "DEFEND"}:
                mark_kill = getattr(world, "mark_combat_kill", None)
                if mark_kill is not None:
                    mark_kill(parameters.get("guid"), now)
            return
        if outcome != Outcome.FAILURE:
            return

        if skill == "LOOT":
            # Live 2026-10-01: the same stale point was clicked three times.
            # Two unopened loot windows retire the corpse anchor.
            note = getattr(world, "note_loot_failure", None)
            if callable(note):
                # The addon's CanLootUnit says the corpse holds nothing for
                # us: a second click cannot help (live 2026-10-02: an empty
                # murloc corpse opened nothing and showed no error).
                live = getattr(world, "state", None) or {}
                guid = str(parameters.get("guid") or "")
                empty = any(isinstance(unit, dict) and str(unit.get("guid") or "") == guid
                            and unit.get("lootable") is False
                            for unit in (live.get("mouseover"), live.get("target")))
                if empty:
                    note(guid, now, limit=1)
                else:
                    note(guid, now)

        goal.failures += 1
        failures[key] = failures.get(key, 0) + 1
        target_guid = str((world.query.target() or {}).get("guid") or "")
        attempted_guid = str(parameters.get("guid") or "")
        # Retail 12 exports no NPC position/distance and a far INTERACTTARGET
        # often raises no range error: the only symptom is a silent
        # ``no_response``.  Live 2026-09-30 (Jaina, '!' visible): the agent
        # interacted from far away, then opened the World Map instead of
        # walking over.  Treat an unobserved effect as a provisional range
        # block, which proposes the visual approach first.
        provisional_range = (
            skill in {"INTERACT", "TALK"}
            and reason in {"expected_observation_missing", "no_response"}
            and attempted_guid and target_guid == attempted_guid
            and not recently_verified_in_range(planner.quest, attempted_guid, now))
        range_failure = (
            skill in {"INTERACT", "TALK"}
            and any(token in str(reason).casefold() for token in (
                "out_of_range", "need to be closer", "too far away",
                "out of range", "közelebb", "túl messze")))
        if range_failure or provisional_range:
            planner.blocked_until.pop(key, None)
            learn = getattr(planner.quest, "learn_out_of_range", None)
            if range_failure and attempted_guid and callable(learn):
                learn(world.state, attempted_guid)
            if attempted_guid:
                planner.quest.interaction_range_blocks.setdefault(
                    attempted_guid, {
                        "started_at": now,
                        "observation_id": (world.latest.observation_id
                                           if world.latest else None),
                        "belief": "SUPPORTED" if range_failure else "CANDIDATE",
                        "source": ("CLIENT_ERROR" if range_failure
                                   else "INTERACTION_EFFECT_UNOBSERVED"),
                    })
            return
        backoff = (
            failure_decision.backoff_seconds
            if failure_decision is not None and failure_decision.retry_allowed
            else retries.max_backoff_seconds)
        live = getattr(world, "state", None) or {}
        target = live.get("target") or {}
        if (skill in {"COMBAT", "DEFEND"} and "facing" in str(reason).casefold()
                and live.get("is_in_combat")
                and target.get("attackable", target.get("is_attackable")) is True
                and not target.get("dead", target.get("is_dead"))):
            # Live 2026-10-02: after facing_failed the agent WAITed ~14 s
            # while the murloc kept hitting it.  Retry the fight at once.
            backoff = min(backoff, .5)
        planner.blocked_until[key] = now + backoff
