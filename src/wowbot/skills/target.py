"""Canonical bounded M0 target acquisition FSM.

The instance is stateless. Its phase and all per-attempt details live in the
caller supplied ActiveSkillState, keeping ActiveSkillRuntime the only running
skill authority.
"""
from __future__ import annotations

from enum import StrEnum
from wowbot.runtime.entity_identity import check_entity_identity
from wowbot.runtime.skill_identity import identity_guarded, pin_skill_identity

from wowbot.agent.models import Command, number
from .hover_confirm import (CLICK_CONFIRM_SECONDS, MAX_HOVERS, confirmed_cursor_handoff,
                            hover_confirm_step, pointer_acquisition_retired, valid_point)
from wowbot.runtime import (ActiveSkillState, FailureReason, Intent, SkillResult,
                            SkillStatus, world_entity_id)


class TargetPhase(StrEnum):
    CONFIRM_HOVER = "CONFIRM_HOVER"
    ACQUIRE_CANDIDATES = "ACQUIRE_CANDIDATES"
    VALIDATE_IDENTITY = "VALIDATE_IDENTITY"
    SELECT_TARGET = "SELECT_TARGET"
    APPLY_TARGET = "APPLY_TARGET"
    VERIFY_TARGET = "VERIFY_TARGET"


class TargetSkill:
    # User 2026-10-31: "do not start casting on the first Tab: it may not be
    # the one attacking us; Tab until we target the creature that attacks us."
    # While the server names our attackers, a Tab defence succeeds only on one
    # of them; another Tab follows once the client reflected the last one.
    DEFEND_TAB_LIMIT = 6
    DEFEND_TAB_SETTLE_SECONDS = .25

    FACE_ATTACKER_RADIANS = .5
    KEY_TURN_RATE = 3.141592653589793          # keyboard turn speed, rad/s

    @classmethod
    def _face_attacker(cls, world_state: dict, attacker: dict):
        """One bounded turn toward an attacker outside Tab's frontal cone, else None."""
        from wowbot.agent.packet_entity_facts import best_position
        from wowbot.combat.target.facing import bearing_error
        point = best_position(attacker)
        error = (bearing_error(world_state.get("player_world_position") or {}, point,
                               world_state.get("orientation")) if point else None)
        if error is None or abs(error) <= cls.FACE_ATTACKER_RADIANS:
            return None
        return Command("BIND", "TURNLEFT" if error > 0 else "TURNRIGHT",
                       max(.05, min(.34, abs(error)/cls.KEY_TURN_RATE*.9)))

    def commands_for(self, intent: Intent) -> tuple[Command, ...]:
        params = intent.parameters
        if params.get("restore_last_target"):
            return (Command("BIND", "TARGETLASTTARGET"),)
        if params.get("activation_source") == "TAB_SERVER_GUID":
            # The server shows this exact unit as the nearest one straight
            # ahead; verify() still requires its GUID as the new target.
            return (Command("BIND", "TARGETNEARESTENEMY"),)
        if params.get("activation_source") == "TAB_DEFEND":
            # In combat without a live target: any enemy Tab selects will do.
            return (Command("BIND", "TARGETNEARESTENEMY"),)
        if params.get("activation_source") == "TAB_FRIEND_RESCUE":
            # User 2026-10-21: Ctrl+Tab selects Archivist Rellid on his drake;
            # verify() requires his GUID (another friend is a miss).
            return (Command("BIND", "TARGETNEARESTFRIEND"),)
        if params.get("click_current_cursor"):
            # A fresh ground-truth handoff has already positioned the actual
            # OS pointer over the identified unit. Do not move it again using
            # UI-space telemetry: UI scale/capture transforms are separate
            # from the physical pointer position. SkillRegistry only admits
            # this form while that mouseover/cursor sample is still fresh.
            return (Command("CLICK_CURRENT_CURSOR"),)
        x, y = number(params.get("x")), number(params.get("y"))
        if x is None or y is None or not (0 < x < 1 and 0 < y < 1):
            return ()
        return (Command("CLICK", x=x, y=y),)

    @identity_guarded
    def begin(self, state: ActiveSkillState, world_state: dict | None = None) -> SkillResult:
        intent = state.intent
        from wowbot.agent.tooltip_quest import known_dead_unit
        world = world_state or state.before_snapshot or {}
        wanted = world_entity_id(intent.target_ref or intent.parameters.get("guid"))
        if (wanted and intent.parameters.get("purpose") != "LOOT"
                and intent.parameters.get("allow_dead") is not True
                and any(isinstance(unit, dict) and unit.get("guid") == wanted
                        and known_dead_unit(unit, world)
                        for unit in (world.get("mouseover"), world.get("target")))):
            return SkillResult(SkillStatus.FAILURE, FailureReason.TARGET_DEAD,
                               replan_required=True, metadata={"detail": "known corpse is not a live target"})
        state.skill_context.setdefault("target", {
            "expected_guid": world_entity_id(intent.target_ref or intent.parameters.get("guid")),
            "expected_name": str(intent.parameters.get("expected_name") or "").casefold().strip(),
            "restore_last_target": bool(intent.parameters.get("restore_last_target")),
        })
        state.phase = TargetPhase.ACQUIRE_CANDIDATES.value
        context = state.skill_context["target"]
        context["expected_guid"] = world_entity_id(pin_skill_identity(state, world_state or {}).get("guid"))
        if not context.get("expected_guid"):
            return SkillResult(SkillStatus.FAILURE, FailureReason.IDENTITY_UNCERTAIN,
                               retryable=True, replan_required=True,
                               metadata={"detail": "name/track-only TARGET must inspect before selection"})
        hover = (valid_point(intent.parameters.get("hover_x"), intent.parameters.get("hover_y"))
                 or valid_point(intent.parameters.get("x"), intent.parameters.get("y")))
        current_handoff = bool(
            intent.parameters.get("ground_truth_handoff")
            and intent.parameters.get("click_current_cursor")
            and confirmed_cursor_handoff(intent.parameters, world_state or state.before_snapshot or {},
                                         state.started_at))
        retired = pointer_acquisition_retired(world)
        if (hover is not None and not retired and not context.get("restore_last_target")
                and context.get("expected_guid") and not current_handoff):
            # The runtime rewrites state.phase every tick (live 2026-10-03:
            # "VERIFY"), so the pending hover lives in the skill context.
            context.update(hover_point=hover, track_id=intent.parameters.get("track_id"),
                           hovers=1, hovered_at=state.started_at, hover_pending=True)
            state.phase = TargetPhase.CONFIRM_HOVER.value
            return SkillResult(SkillStatus.RUNNING,
                               commands=(Command("HOVER", x=hover[0], y=hover[1], duration=.05),))
        commands = self.commands_for(intent)
        if retired and any(command.kind in {"CLICK", "CLICK_CURRENT_CURSOR"} for command in commands):
            # SERVER: a screen click is no unit acquisition; Tab/GUID is.
            return SkillResult(SkillStatus.FAILURE, FailureReason.LOW_CONFIDENCE,
                               replan_required=True,
                               metadata={"detail": "pointer_acquisition_retired"})
        if not commands:
            return SkillResult(SkillStatus.FAILURE, FailureReason.LOW_CONFIDENCE,
                               replan_required=True,
                               metadata={"detail": "target intent has no safe click or configured restore binding"})
        state.phase = TargetPhase.APPLY_TARGET.value
        if current_handoff:
            # The addon already names the unit under this exact cursor. A
            # redundant HOVER to the predicted bbox centre discards that proof
            # and makes a moving target wait for another telemetry roundtrip.
            context["handoff_reused"] = True
        if context.get("expected_guid") and not context.get("restore_last_target"):
            context["clicked_at"] = state.started_at
        return SkillResult(SkillStatus.RUNNING, commands=commands)

    @identity_guarded
    def verify(self, state: ActiveSkillState, world_state: dict, now: float) -> SkillResult:
        context = state.skill_context.get("target") or {}
        target = world_state.get("target") or {}
        expected_guid = context.get("expected_guid")
        expected_name = context.get("expected_name") or ""
        observed_guid = target.get("guid")
        observed_name = str(target.get("name") or "").casefold().strip()
        if context.get("hover_pending") and observed_guid != expected_guid:
            outcome, commands = hover_confirm_step(context, world_state, now,
                                                   expected_guid=str(expected_guid or ""),
                                                   deadline=state.attempt.deadline)
            if outcome == "CLICK":
                context["hover_pending"] = False
                context["clicked_at"] = now
                state.phase = TargetPhase.APPLY_TARGET.value
                return SkillResult(SkillStatus.RUNNING, commands=commands)
            if outcome == "HOVER":
                return SkillResult(SkillStatus.RUNNING, commands=commands)
            if outcome == "WAIT" and now < state.attempt.deadline:
                return SkillResult(SkillStatus.RUNNING)
            return SkillResult(SkillStatus.FAILURE, FailureReason.TARGET_NOT_FOUND,
                               retryable=True, replan_required=True,
                               metadata={"detail": "hovered box never showed the expected GUID"})
        state.phase = TargetPhase.VERIFY_TARGET.value
        if state.intent.parameters.get("activation_source") == "TAB_DEFEND":
            from wowbot.agent.combat_target_safety import combat_target_allowed
            if (observed_guid and target.get("dead", target.get("is_dead")) is not True
                    and not combat_target_allowed(world_state, target)):
                return SkillResult(SkillStatus.FAILURE, FailureReason.TARGET_NOT_FOUND,
                                   replan_required=True, metadata={"detail": "unverified_elite_defence_target"})
            from wowbot.agent.packet_entity_facts import attackers
            engaged_rows = attackers(world_state)
            engaged = {str(row[1].get("guid")) for row in engaged_rows}
            live = (observed_guid and target.get("attackable", target.get("is_attackable")) is True
                    and target.get("dead", target.get("is_dead")) is not True)
            if live and (not engaged or str(observed_guid) in engaged):
                return SkillResult(SkillStatus.SUCCESS,
                                   metadata={"target_guid": observed_guid, "tab_defend": True,
                                             "attacker_verified": bool(engaged)})
            # Live 2026-11-01 (Westfall gnolls): this branch kept RUNNING past
            # its deadline with no further press while two gnolls killed the
            # character (70 s, twice).  The deadline always ends the attempt.
            if now >= state.attempt.deadline:
                return SkillResult(SkillStatus.FAILURE, FailureReason.TARGET_NOT_FOUND,
                                   retryable=True, replan_required=True,
                                   metadata={"detail": "tab_did_not_reach_an_attacker",
                                             "defend_tabs": int(context.get("defend_tabs") or 1)})
            if engaged:
                # The selected unit is no attacker, or Tab found nothing: an
                # attacker behind us is never in Tab's cone, so face the nearest
                # attacker's server position first, then Tab again.
                tabs = int(context.get("defend_tabs") or 1)
                if tabs >= self.DEFEND_TAB_LIMIT:
                    return SkillResult(SkillStatus.FAILURE, FailureReason.TARGET_NOT_FOUND,
                                       retryable=True, replan_required=True,
                                       metadata={"detail": "tab_did_not_reach_an_attacker",
                                                 "defend_tabs": tabs, "observed_guid": observed_guid})
                last = float(context.get("defend_tab_at", state.started_at))
                if now-last < self.DEFEND_TAB_SETTLE_SECONDS:
                    return SkillResult(SkillStatus.RUNNING)
                context.update(defend_tabs=tabs+1, defend_tab_at=now)
                turn = self._face_attacker(world_state, engaged_rows[0][1])
                if turn is not None:
                    return SkillResult(SkillStatus.RUNNING, commands=(turn,),
                                       metadata={"defend_tab": tabs+1, "face_attacker": True})
                return SkillResult(SkillStatus.RUNNING, commands=(Command("BIND", "TARGETNEARESTENEMY"),),
                                   metadata={"defend_tab": tabs+1, "not_an_attacker": observed_guid})
            return SkillResult(SkillStatus.RUNNING)
        if expected_guid:
            if observed_guid == expected_guid:
                checked = check_entity_identity(pin_skill_identity(state, world_state), target)
                if not checked:
                    return SkillResult(SkillStatus.FAILURE, FailureReason.IDENTITY_UNCERTAIN,
                                       retryable=True, replan_required=True,
                                       metadata={"identity_check": checked.reason})
                return SkillResult(SkillStatus.SUCCESS, metadata={"target_guid": observed_guid})
            acceptable = {str(guid) for guid in (state.intent.parameters.get("acceptable_guids") or ())}
            if (observed_guid and state.intent.parameters.get("activation_source") == "TAB_FRIEND_RESCUE"
                    and observed_guid != ((state.before_snapshot or {}).get("target") or {}).get("guid")
                    and str(observed_guid) not in acceptable):
                # Ctrl+Tab chose another friendly unit: a miss, retried later.
                return SkillResult(SkillStatus.FAILURE, FailureReason.TARGET_NOT_FOUND,
                                   retryable=True, replan_required=True,
                                   metadata={"detail": "friend tab selected another unit",
                                             "observed_guid": observed_guid})
            if (observed_guid and state.intent.parameters.get("activation_source") == "TAB_SERVER_GUID"
                    and str(observed_guid) in acceptable):
                # Tab chose another mob of the same objective (live 17:19:53):
                # just as good a target, verified by its own server GUID.
                return SkillResult(SkillStatus.SUCCESS,
                                   metadata={"target_guid": observed_guid, "tab_alternative": True})
            clicked_at = number(context.get("clicked_at"))
            target_time = number(world_state.get("target_sample_time"))
            if (clicked_at is not None and target_time is not None
                    and target_time >= clicked_at + CLICK_CONFIRM_SECONDS):
                # The click missed: hover the box again at once (user
                # 2026-10-05: "gyorsabbá/pörgősebbé tenni a kijelöléseket").
                if context.get("hover_point") and int(context.get("hovers") or 0) < MAX_HOVERS:
                    context.update(hover_pending=True, clicked_at=None, hovered_at=None)
                    return self.verify(state, world_state, now)
                return SkillResult(SkillStatus.FAILURE, FailureReason.TARGET_NOT_FOUND,
                                   retryable=True, replan_required=True,
                                   metadata={"detail": "click showed no target change"})
            previous_guid = ((state.before_snapshot or {}).get("target") or {}).get("guid")
            if (observed_guid and observed_guid == previous_guid
                    and now < state.attempt.deadline):
                # Live 2026-10-04 (Giant Boar): verify ran ~0.1 s after the
                # click while the addon still reported the *previous* target
                # and failed IDENTITY_UNCERTAIN every time.  The old target is
                # not evidence of a wrong click until the deadline.
                return SkillResult(SkillStatus.RUNNING)
            if observed_guid and observed_guid != expected_guid:
                return SkillResult(SkillStatus.FAILURE, FailureReason.IDENTITY_UNCERTAIN,
                                   replan_required=True,
                                   metadata={"expected_guid": expected_guid, "observed_guid": observed_guid})
        if now >= state.attempt.deadline:
            return SkillResult(SkillStatus.FAILURE, FailureReason.TARGET_NOT_FOUND,
                               retryable=True, replan_required=True)
        return SkillResult(SkillStatus.RUNNING)
