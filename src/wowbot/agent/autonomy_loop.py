"""Event-gated subgoal commitment for the single AutonomousAgent loop."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum
import hashlib

from .models import Proposal, canonical


class RuntimePhase(StrEnum):
    IDLE = "IDLE"
    OBSERVING = "OBSERVING"
    ACQUIRING = "ACQUIRING"
    TARGET_COMMITTED = "TARGET_COMMITTED"
    APPROACHING = "APPROACHING"
    INTERACTING = "INTERACTING"
    COMBAT = "COMBAT"
    VERIFYING = "VERIFYING"
    RECOVERING = "RECOVERING"
    REPLANNING = "REPLANNING"


TARGET_SKILLS = {"TARGET", "APPROACH_TARGET", "VISUAL_APPROACH", "REACQUIRE_TARGET", "REACH_OBJECT", "COMBAT", "DEFEND", "LOOT", "TALK",
                 "INTERACT", "ASSIST", "USE_ON_TARGET", "OBJECT_USE", "FOLLOW_INSTRUCTION"}
TRANSIENT_SKILLS = {"INSPECT", "SEEK_VISUAL_CUE", "OPEN_MAP", "CLOSE_MAP", "QUEST_DIALOG", "FIELD_TURN_IN", "EXTRA_ACTION", "VEHICLE_ABILITY", "EXIT_VEHICLE", "REPAIR",
                    "CAMERA_CONTROL",
                    "BUY_VENDOR", "SELL_VENDOR", "OPEN_BAGS", "MOUNT", "DISMOUNT",
                    "GATHER", "HERB", "MINE", "FISH", "USE", "OBJECT_USE", "USE_ON_TARGET"}
SAFETY_SKILLS = {"ESCAPE", "DEFEND"}
# How long a commitment may sit in "no proposal matches" WAIT
# (RuntimePhase.TARGET_COMMITTED / "committed_skill_waiting") before giving
# up on it. Live-confirmed 2026-09-12: once an NPC has nothing left to offer
# (quest already accepted, Accept greyed out, INTERACT concludes with
# "expected_observation_missing"), NOTHING makes a proposal start matching
# again -- the world state that would produce a match just never occurs --
# so this WAIT would otherwise persist indefinitely, observed up to 35s in
# one run, only ever ended by the unrelated receive_gap freshness check
# forcing MANUAL. Nothing is actually in flight during this WAIT (unlike a
# skill mid-execution, which has its own SkillContract timeout), so a short
# timeout is safe -- long enough to absorb a single-tick proposal-generation
# gap, short enough to stop wasting seconds once truly stuck.
STUCK_COMMITMENT_TIMEOUT_SECONDS = 3.0

ALLOWED_PHASE_TRANSITIONS = {
    RuntimePhase.IDLE: set(RuntimePhase),
    RuntimePhase.OBSERVING: {RuntimePhase.OBSERVING, RuntimePhase.VERIFYING,
        RuntimePhase.REPLANNING, RuntimePhase.COMBAT, RuntimePhase.RECOVERING, RuntimePhase.IDLE},
    RuntimePhase.ACQUIRING: {RuntimePhase.ACQUIRING, RuntimePhase.VERIFYING,
        RuntimePhase.TARGET_COMMITTED, RuntimePhase.COMBAT, RuntimePhase.REPLANNING, RuntimePhase.IDLE},
    RuntimePhase.TARGET_COMMITTED: {RuntimePhase.TARGET_COMMITTED, RuntimePhase.APPROACHING,
        RuntimePhase.INTERACTING, RuntimePhase.COMBAT, RuntimePhase.VERIFYING,
        RuntimePhase.RECOVERING, RuntimePhase.REPLANNING, RuntimePhase.IDLE},
    RuntimePhase.APPROACHING: {RuntimePhase.APPROACHING, RuntimePhase.VERIFYING,
        RuntimePhase.TARGET_COMMITTED, RuntimePhase.COMBAT, RuntimePhase.RECOVERING,
        RuntimePhase.REPLANNING, RuntimePhase.IDLE},
    RuntimePhase.INTERACTING: {RuntimePhase.INTERACTING, RuntimePhase.VERIFYING,
        RuntimePhase.TARGET_COMMITTED, RuntimePhase.COMBAT, RuntimePhase.RECOVERING,
        RuntimePhase.REPLANNING, RuntimePhase.IDLE},
    RuntimePhase.COMBAT: {RuntimePhase.COMBAT, RuntimePhase.VERIFYING,
        RuntimePhase.TARGET_COMMITTED, RuntimePhase.INTERACTING, RuntimePhase.RECOVERING,
        RuntimePhase.REPLANNING, RuntimePhase.IDLE},
    RuntimePhase.VERIFYING: set(RuntimePhase),
    RuntimePhase.RECOVERING: {RuntimePhase.RECOVERING, RuntimePhase.VERIFYING,
        RuntimePhase.TARGET_COMMITTED, RuntimePhase.COMBAT, RuntimePhase.REPLANNING, RuntimePhase.IDLE},
    RuntimePhase.REPLANNING: set(RuntimePhase),
}


@dataclass
class CommittedSubgoal:
    commitment_id: str
    goal_id: str
    reference: str
    kind: str
    target_guid: str | None
    entity_key: str | None
    objective_refs: tuple[str, ...]
    initial_skill: str
    selected_at: float
    last_updated: float
    status: str = "ACTIVE"
    reason: str = "selected"
    successful_actions: int = 0
    failures: int = 0
    target_missing_observations: int = 0
    target_missing_since: float | None = None
    visual_track_lost_since: float | None = None
    visual_approach_blocked: bool = False
    last_target_observation_id: str | None = None
    quest_signature: str = ""
    session_id: str | None = None
    map_id: int | str | None = None


class AutonomousLoop:
    """Keeps one subgoal until an explicit completion/failure event.

    Candidate generation may observe the changing world, but it cannot replace
    an active commitment with unrelated active perception or exploration.
    """

    def __init__(self) -> None:
        self.phase = RuntimePhase.IDLE
        self.commitment: CommittedSubgoal | None = None
        self.lifecycle: list[dict] = []
        self.last_replan_trigger = "GOAL_CREATED"
        self.replan_revision = 0
        self.event_sequence = 0

    def reset(self, now: float = 0., reason: str = "reset") -> None:
        if self.commitment:
            self._event("COMMITMENT_RELEASED", now, reason)
        self.commitment = None
        self.phase = RuntimePhase.IDLE
        self.last_replan_trigger = reason
        self.replan_revision += 1

    @staticmethod
    def _objective_refs(proposal: Proposal) -> tuple[str, ...]:
        params = proposal.parameters
        values = []
        for value in (params.get("objective_id"), params.get("quest_id")):
            if value is not None:
                values.append(str(value))
        values.extend(str(value) for value in params.get("objective_ids", []) if value is not None)
        values.extend(f"quest:{value}" for value in params.get("quest_ids", []) if value is not None)
        return tuple(dict.fromkeys(values))

    @staticmethod
    def _entity_key(target: dict) -> str | None:
        if target.get("npc_id") is not None:
            return f"npc:{target['npc_id']}"
        if target.get("guid"):
            return f"guid:{target['guid']}"
        return None

    @staticmethod
    def _phase_for(skill: str, committed=False) -> RuntimePhase:
        if skill in {"INSPECT", "SEEK_VISUAL_CUE", "CAMERA_CONTROL", "OPEN_MAP", "CLOSE_MAP"}:
            return RuntimePhase.OBSERVING
        if skill in {"TARGET", "ACQUIRE_TARGET"}:
            return RuntimePhase.ACQUIRING
        if skill in {"MOVE", "FOLLOW", "REACH_LOCATION", "APPROACH_TARGET", "VISUAL_APPROACH", "REACH_OBJECT"}:
            return RuntimePhase.APPROACHING
        if skill in {"COMBAT", "DEFEND", "FOLLOW_INSTRUCTION"}:
            return RuntimePhase.COMBAT
        if skill in {"RECOVER", "ESCAPE"}:
            return RuntimePhase.RECOVERING
        if skill in {"TALK", "INTERACT", "LOOT", "ASSIST", "USE_ON_TARGET", "OBJECT_USE", "USE",
                     "QUEST_DIALOG", "FIELD_TURN_IN", "EXTRA_ACTION", "GATHER", "HERB", "MINE", "FISH", "REPAIR",
                     "BUY_VENDOR", "SELL_VENDOR", "OPEN_BAGS"}:
            return RuntimePhase.INTERACTING
        return RuntimePhase.TARGET_COMMITTED if committed else RuntimePhase.REPLANNING

    def _event(self, event: str, now: float, reason: str, **extra) -> None:
        self.event_sequence += 1
        self.lifecycle.append({"event": event, "sequence": self.event_sequence,
                               "at": now, "reason": reason,
                               "commitment_id": self.commitment.commitment_id if self.commitment else None,
                               **extra})
        self.lifecycle[:] = self.lifecycle[-100:]

    def _set_phase(self, phase: RuntimePhase, now: float, reason: str) -> None:
        phase = RuntimePhase(phase)
        if phase == self.phase:
            return
        if phase not in ALLOWED_PHASE_TRANSITIONS[self.phase]:
            self._event("INVALID_TRANSITION_BLOCKED", now, reason,
                        previous=self.phase.value, requested=phase.value)
            return
        previous = self.phase
        self.phase = phase
        self._event("PHASE_CHANGED", now, reason, previous=previous.value, phase=phase.value)

    def _commit(self, proposal: Proposal, goal, world, now: float) -> None:
        params = proposal.parameters
        target = world.query.target()
        target_guid = params.get("guid")
        if target_guid is None and proposal.skill in TARGET_SKILLS:
            target_guid = target.get("guid")
        refs = self._objective_refs(proposal)
        if target_guid:
            kind = "TARGET"
            reference = refs[0] if refs else f"target:{target_guid}"
        elif proposal.skill in {"MOVE", "FOLLOW", "REACH_LOCATION"}:
            kind = "LOCATION"
            reference = refs[0] if refs else canonical({key: params.get(key) for key in
                ("map_id", "world_map_id", "coordinate_space", "x", "y")})
        elif proposal.skill == "ACQUIRE_TARGET":
            kind, reference = "ACQUIRE", refs[0] if refs else "acquire:goal-relevant-target"
        else:
            kind, reference = "TRANSIENT", refs[0] if refs else proposal.key
        identity = hashlib.sha256(f"{goal.goal_id}:{kind}:{reference}:{now}".encode()).hexdigest()[:24]
        entity_key = self._entity_key(target) if target_guid and target.get("guid") == target_guid else None
        self.commitment = CommittedSubgoal(identity, goal.goal_id, reference, kind,
                                            target_guid, entity_key, refs, proposal.skill, now, now,
                                            quest_signature=world.quest_signature(world.state),
                                            session_id=world.session_id, map_id=world.state.get("map_id"))
        self._set_phase(RuntimePhase.TARGET_COMMITTED if kind == "TARGET" else
                        self._phase_for(proposal.skill, True), now, "subgoal_committed")
        self._event("SUBGOAL_COMMITTED", now, proposal.reason, skill=proposal.skill,
                    kind=kind, reference=reference, target_guid=target_guid)

    def _release(self, trigger: str, now: float, reason: str) -> None:
        self._event("COMMITMENT_RELEASED", now, reason, trigger=trigger)
        self.commitment = None
        self._set_phase(RuntimePhase.REPLANNING, now, trigger)
        self.last_replan_trigger = trigger
        self.replan_revision += 1

    @staticmethod
    def _target_is_locatable(world, target: dict, now: float) -> bool:
        """Whether a selected unit has evidence usable by a controller.

        A GUID proves client identity, not screen/world location.  In
        particular TARGETNEARESTENEMY may select an off-screen unit.  Such a
        target must not become a persistent movement commitment unless a
        fresh visual anchor exists or the action bar confirms that a harmful
        action is already in range.
        """
        guid = str(target.get("guid") or "")
        anchor = (target.get("screen_position") or
                  (world.state.get("confirmed_mouseover_anchors") or {}).get(guid) or {})
        if isinstance(anchor, dict):
            x = anchor.get("x", anchor.get("nx"))
            y = anchor.get("y", anchor.get("ny"))
            sample_time = anchor.get("sample_time")
            fresh = (sample_time is None or
                     (isinstance(sample_time, (int, float)) and 0 <= now-float(sample_time) <= 5.0))
            if x is not None and y is not None and fresh:
                return True
        return any(action.get("is_harmful") is True and action.get("in_range") is True
                   for action in world.state.get("actionbar", []))

    def _promote_late_acquired_target(self, world, now: float) -> None:
        """Accept authoritative target telemetry that arrived after verify.

        The target binding and the addon FAST packet are asynchronous.  A
        bounded ACQUIRE commitment therefore survives its first verification
        timeout and is promoted here when the selected unit finally appears.
        CV is not allowed to create the identity: GUID/attackable/dead all
        come from the addon target observation.
        """
        commitment = self.commitment
        if not commitment or commitment.kind != "ACQUIRE":
            return
        target = world.query.target()
        if (not target.get("guid")
                or target.get("attackable", target.get("is_attackable")) is not True
                or target.get("dead", target.get("is_dead")) is True):
            return
        if not self._target_is_locatable(world, target, now):
            self._release("BLIND_TARGET_UNLOCATABLE", now,
                          "addon_identity_without_visual_anchor_or_range_evidence")
            return
        commitment.kind = "TARGET"
        commitment.target_guid = str(target["guid"])
        commitment.entity_key = self._entity_key(target)
        commitment.target_missing_observations = 0
        commitment.target_missing_since = None
        commitment.visual_track_lost_since = None
        commitment.visual_approach_blocked = False
        commitment.last_updated = now
        self._set_phase(RuntimePhase.TARGET_COMMITTED, now,
                        "late_target_identity_verified")
        self._event("TARGET_COMMITTED", now, "late_target_identity_verified",
                    target_guid=commitment.target_guid)

    def _matching(self, proposal: Proposal, world) -> bool:
        commitment = self.commitment
        if not commitment:
            return True
        params = proposal.parameters
        if ((getattr(world, "state", None) or {}).get("vehicle_controls")
                and (proposal.skill == "VEHICLE_ABILITY"
                     or (proposal.skill == "VISUAL_APPROACH"
                         and params.get("purpose") in {"VEHICLE_AIM", "VEHICLE_ATTACK"}))):
            # Live 2026-10-04 17:40 (Giant Boar, 3/8 in 310 s): a TARGET
            # commitment to one cadaver rejected the vehicle's own ability
            # (not a TARGET_SKILL), and the agent WAITed 161 s in total.  A
            # ridden vehicle's attack/aim serves the quest whichever unit the
            # commitment named.
            return True
        refs = set(self._objective_refs(proposal))
        if commitment.kind == "TARGET":
            guid = params.get("guid")
            if proposal.skill == "CLOSE_MAP":
                return guid == commitment.target_guid
            if proposal.skill == "OPEN_MAP":
                return (guid == commitment.target_guid
                        and params.get("purpose") == "LOCATE_COMMITTED_TARGET")
            if proposal.skill == "REACQUIRE_TARGET":
                return guid == commitment.target_guid
            if proposal.skill in {"QUEST_DIALOG", "FIELD_TURN_IN"}:
                # QUEST_DIALOG is in TRANSIENT_SKILLS (on_execute releases the
                # commitment once it verifies, line ~372 below -- treating
                # ACCEPT as the natural conclusion of the target-interaction
                # subgoal), but it was never in TARGET_SKILLS either, so the
                # generic checks further down always rejected it. Live-
                # confirmed 2026-09-12: with an active TARGET commitment (the
                # normal case while approaching an NPC), the dialog opening
                # mid-approach (VISUAL_APPROACH's own
                # interaction_ui_opened_during_approach success signal) was
                # followed by 60+ seconds of WAIT ("committed_skill_waiting")
                # because no proposal ever matched. Unlike CLOSE_MAP/
                # REACQUIRE_TARGET, QUEST_DIALOG proposals (planner.py's
                # QUEST_DIALOG proposals, built from quest_ui's x/y/action or
                # its raw entries) never carry a "guid" -- the dialog is a
                # screen-space button/UI element, not an addressed unit -- so
                # matching on guid would just as reliably reject it. Only one
                # NPC's quest dialog can be open at a time, and it can only
                # be the one we're currently committed to and interacting
                # with, so any QUEST_DIALOG proposal is unambiguous here.
                return True
            if proposal.skill == "VISUAL_APPROACH" and commitment.visual_approach_blocked:
                # Live-observed 2026-09-13: repeated "visual_track_lost"
                # failures against the same guid (identity intact, only the
                # 3D anchor keeps slipping) kept re-matching VISUAL_APPROACH
                # every single retry via the generic TARGET_SKILLS fallback
                # below -- 50 attempts over ~2 minutes on one unreachable
                # subject before engine.py's separate approach_counts budget
                # finally forced MANUAL. Once outcome()'s exemption (below)
                # decides this has gone on long enough, it sets this flag so
                # VISUAL_APPROACH itself stops matching -- forcing REACQUIRE_
                # TARGET (a bounded player turn back to the last anchor, not just
                # another blind approach attempt) or a genuine replan to get
                # a turn instead of the identical strategy being retried
                # unchanged forever.
                return False
            if proposal.skill == "CAMERA_CONTROL":
                return (guid == commitment.target_guid
                        and params.get("purpose") == "REACQUIRE_COMMITTED_TARGET")
            if proposal.skill == "INSPECT":
                if guid == commitment.target_guid:
                    return True
                target = world.query.target()
                anchor = ((world.state.get("confirmed_mouseover_anchors") or {})
                          .get(str(commitment.target_guid or "")) or
                          (target.get("screen_position") if
                           target.get("guid") == commitment.target_guid else {}) or {})
                return bool(anchor.get("track_id") and
                            params.get("track_id") == anchor.get("track_id"))
            if proposal.skill == "WAIT" and guid == commitment.target_guid:
                return True
            if guid and guid == commitment.target_guid and proposal.skill in TARGET_SKILLS:
                return True
            current = world.query.target()
            if current.get("guid") == commitment.target_guid and proposal.skill in TARGET_SKILLS:
                return True
            return bool(refs.intersection(commitment.objective_refs)) and proposal.skill in TARGET_SKILLS
        if commitment.kind == "LOCATION":
            if proposal.skill not in {"MOVE", "FOLLOW", "REACH_LOCATION"}:
                return False
            destination = self.commitment.reference
            return (bool(refs.intersection(commitment.objective_refs)) if commitment.objective_refs
                    else canonical({key: params.get(key) for key in
                                    ("map_id", "world_map_id", "coordinate_space", "x", "y")}) == destination)
        if commitment.kind == "ACQUIRE":
            return proposal.skill == "ACQUIRE_TARGET" or bool(refs.intersection(commitment.objective_refs))
        return proposal.key == commitment.reference or bool(refs.intersection(commitment.objective_refs))

    def choose(self, proposals: list[Proposal], preferred: Proposal, goal, world, now: float) -> Proposal:
        self._promote_late_acquired_target(world, now)
        if world.state.get("is_in_combat"):
            # Live-observed 2026-09-13: a quest-relevant fight uses the
            # "COMBAT" skill (not "DEFEND", which alone gets the SAFETY_SKILLS
            # fast path below), so when its own TARGET commitment briefly had
            # no matching proposal (STUCK_COMMITMENT_TIMEOUT_SECONDS elapsed
            # with none in `matches`), the release fell through to a fresh
            # LOCATION commitment for a quest-map MOVE -- which engine.py then
            # correctly cancelled every single tick as
            # "combat_interrupted_previous_skill", repeating for 20+ seconds
            # while a live, attackable target sat right there. MOVE/FOLLOW/
            # REACH_LOCATION are the only skills _commit() ever turns into a
            # LOCATION commitment; drop them from consideration while the game
            # reports combat so that path is structurally unreachable here,
            # regardless of why the TARGET commitment's own matching came up
            # empty. Everything else (INSPECT, SEEK_VISUAL_CUE, QUEST_DIALOG,
            # ...) stays -- _matching() already scopes those to the committed
            # target's own guid/track_id, so leaving them in is not the risk.
            proposals = [proposal for proposal in proposals
                         if proposal.skill not in {"MOVE", "FOLLOW", "REACH_LOCATION"}]
        safety = [proposal for proposal in proposals if proposal.skill in SAFETY_SKILLS]
        if safety:
            chosen = max(safety, key=lambda proposal: proposal.priority)
            self._set_phase(self._phase_for(chosen.skill), now, "safety_interrupt")
            self._event("SAFETY_INTERRUPT", now, chosen.reason, skill=chosen.skill)
            return chosen
        # An addressable quest dialog is a short-lived, addon-confirmed UI
        # transaction.  It must preempt a continued visual approach: the
        # latter has already achieved its purpose as soon as the frame opens.
        #
        # Live regression (Jaina / quest 55122, 2026-09-17): the candidate
        # set contained both VISUAL_APPROACH (priority 102) and QUEST_DIALOG
        # (priority 90).  Generic commitment ranking chose the former every
        # time, repeatedly re-starting a successful approach while the Accept
        # button remained unclicked.  Safety still wins above; this only
        # orders exact, visible UI ground truth ahead of navigation.
        dialogs = [proposal for proposal in proposals
                   if proposal.skill in {"QUEST_DIALOG", "FIELD_TURN_IN"}]
        if dialogs:
            chosen = max(dialogs, key=lambda proposal: (proposal.priority, proposal.confidence))
            self._set_phase(self._phase_for(chosen.skill, bool(self.commitment)), now,
                            "confirmed_quest_dialog_preempts_navigation")
            if self.commitment:
                self.commitment.last_updated = now
            return chosen
        # A ridden vehicle's own attack/aim preempts commitment bookkeeping
        # (live 2026-10-04 17:58: after Trample killed the committed cadaver
        # the loop chose an unexecutable "target_click_retry" TARGET for 11 s
        # while a 107-utility VEHICLE_ABILITY waited).
        if (world.state or {}).get("vehicle_controls"):
            vehicle = [proposal for proposal in proposals
                       if proposal.skill in {"VEHICLE_ABILITY", "EXIT_VEHICLE"}
                       or (proposal.skill == "VISUAL_APPROACH"
                           and proposal.parameters.get("purpose") in {"VEHICLE_AIM", "VEHICLE_ATTACK"})]
            if vehicle:
                chosen = max(vehicle, key=lambda proposal: (proposal.priority, proposal.confidence))
                self._set_phase(self._phase_for(chosen.skill, bool(self.commitment)), now,
                                "vehicle_action_preempts_commitment")
                if self.commitment:
                    self.commitment.last_updated = now
                return chosen
        # Live 2026-10-06: after a DEFEND kill the planner already offered a
        # confirmed own-corpse LOOT (priority 108), yet an interrupted
        # minimap-dot LOCATION commitment resumed MOVE for 4.8 seconds first.
        # A fresh, owned corpse must interrupt unrelated navigation before
        # its screen anchor becomes stale.  This is not a generic dead-target
        # guess: CombatPlanning supplied exact GUID + confirmed corpse anchor.
        if not world.state.get("is_in_combat"):
            corpse_actions = [proposal for proposal in proposals
                              if proposal.skill in {"LOOT", "VISUAL_APPROACH"}
                              and proposal.parameters.get("corpse_anchor") is True
                              and proposal.parameters.get("guid", proposal.parameters.get("corpse_guid"))
                              and world.corpse_is_owned(
                                  proposal.parameters.get("guid", proposal.parameters.get("corpse_guid")), now)]
            if corpse_actions:
                chosen = max(corpse_actions, key=lambda proposal: (proposal.priority,
                                                                    proposal.confidence))
                self._set_phase(self._phase_for(chosen.skill, bool(self.commitment)), now,
                                "confirmed_own_corpse_preempts_navigation")
                if self.commitment:
                    self.commitment.last_updated = now
                return chosen
            # A screen-space object has been named by addon mouseover on the
            # current cursor.  The destination LOCATION commitment has done
            # its job; it must not keep returning a map-relocation WAIT while
            # the quest cocoon is literally under the pointer (12:53 live).
            from .tooltip_quest import effective_mouseover
            from .models import number
            cursor = world.state.get("cursor_position") or {}
            mouse = effective_mouseover(world.state)
            observed_identity = mouse.get("tooltip") or mouse.get("name")
            object_actions = [proposal for proposal in proposals
                              if proposal.skill == "OBJECT_USE"
                              and proposal.parameters.get("activation_source") != "INTERACT_KEY"
                              and proposal.parameters.get("mouseover_tooltip")
                                  == observed_identity
                              and (mouse.get("tooltip") or
                                   (mouse.get("quest_related") is True
                                    and any(str(mouse.get("quest_id")) == str(qid)
                                            for qid in proposal.parameters.get("quest_ids") or ())))
                              and None not in (number(cursor.get("nx")),
                                               number(cursor.get("ny")),
                                               number(proposal.parameters.get("x")),
                                               number(proposal.parameters.get("y")))
                              and abs(number(cursor["nx"])-number(proposal.parameters["x"])) <= .004
                              and abs(number(cursor["ny"])-number(proposal.parameters["y"])) <= .004]
            if object_actions:
                chosen = max(object_actions, key=lambda proposal: (proposal.priority,
                                                                     proposal.confidence))
                self._set_phase(self._phase_for(chosen.skill, bool(self.commitment)), now,
                                "confirmed_quest_object_preempts_navigation")
                if self.commitment:
                    self.commitment.last_updated = now
                return chosen
        if self.commitment:
            if self.commitment.session_id != world.session_id:
                self._release("SESSION_CHANGED", now, "committed_session_changed")
            elif (self.commitment.objective_refs and
                  self.commitment.quest_signature != world.quest_signature(world.state)):
                self._release("QUEST_STATE_CHANGED", now, "quest_progress_or_state_changed")
        if self.commitment:
            target = world.query.target()
            if self.commitment.kind == "TARGET":
                if target.get("guid") == self.commitment.target_guid:
                    self.commitment.target_missing_observations = 0
                    self.commitment.target_missing_since = None
                    if target.get("dead", target.get("is_dead")):
                        matches = [proposal for proposal in proposals
                                   if self._matching(proposal, world) and proposal.skill == "LOOT"]
                        if matches:
                            chosen = max(matches, key=lambda proposal: proposal.priority)
                            self._set_phase(self._phase_for(chosen.skill, True), now, "committed_target_dead")
                            return chosen
                else:
                    corpse_loot = [proposal for proposal in proposals
                                   if proposal.skill == "LOOT"
                                   and proposal.parameters.get("corpse_anchor")
                                   and proposal.parameters.get("guid") == self.commitment.target_guid]
                    if corpse_loot:
                        chosen = max(corpse_loot, key=lambda proposal: proposal.priority)
                        self._set_phase(self._phase_for(chosen.skill, True), now,
                                        "committed_target_confirmed_as_corpse")
                        return chosen
                    # Live-observed 2026-09-13: a missed TARGET click (cursor
                    # already stale by the time the click fires, or the mob
                    # moved a pixel) fell straight into passive WAIT-and-hope
                    # here instead of trying again, even though the mouseover
                    # identity clearly still resolves to the same guid on this
                    # very tick (a fresh TARGET proposal for it is sitting
                    # right there in proposals) -- observed live as "targeted
                    # it, then walked away" once the flicker window ran out
                    # and the planner moved on to something else entirely.
                    retry = [proposal for proposal in proposals
                             if proposal.skill == "TARGET"
                             and proposal.parameters.get("guid") == self.commitment.target_guid]
                    if retry:
                        chosen = max(retry, key=lambda proposal: proposal.priority)
                        self._set_phase(RuntimePhase.TARGET_COMMITTED, now, "target_click_retry")
                        return chosen
                    if self.commitment.target_missing_since is None:
                        self.commitment.target_missing_since = now
                    observation_id = world.latest.observation_id if world.latest else None
                    if observation_id != self.commitment.last_target_observation_id:
                        self.commitment.target_missing_observations += 1
                        self.commitment.last_target_observation_id = observation_id
                    # Live-observed 2026-09-13: a target that flickers present/
                    # missing across observations resets target_missing_observations
                    # to 0 on every reappearance (line above), so the <3 counter
                    # alone never reaches its ceiling and this WAIT can repeat
                    # indefinitely (53+ seconds seen live) even though telemetry
                    # itself stayed fresh throughout. Cap total flicker tolerance
                    # by wall clock too, independent of how the observations land.
                    if (self.commitment.target_missing_observations < 3
                            and now - self.commitment.target_missing_since < 6.0):
                        self._set_phase(RuntimePhase.TARGET_COMMITTED, now, "target_temporarily_missing")
                        return Proposal.make("WAIT", "Commitolt target rövid idejű eltűnése; identity megőrzése",
                                             {"commitment_id": self.commitment.commitment_id,
                                              "waiting_for": ["TARGET_REAPPEAR", "TARGET_REACQUIRE_EVIDENCE"],
                                              "next_action": "RELEASE_TARGET_AND_REPLAN"}, priority=99)
                    self._release("TARGET_LOST", now, "target_missing_in_three_fresh_observations_or_6s")
            if self.commitment:
                matches = [proposal for proposal in proposals if self._matching(proposal, world)]
                if matches:
                    chosen = max(matches, key=lambda proposal: (proposal.priority, proposal.confidence))
                    self._set_phase(self._phase_for(chosen.skill, True), now, "continue_committed_subgoal")
                    self.commitment.last_updated = now
                    return chosen
                if now - self.commitment.last_updated < STUCK_COMMITMENT_TIMEOUT_SECONDS:
                    self._set_phase(RuntimePhase.TARGET_COMMITTED, now, "committed_skill_waiting")
                    return Proposal.make("WAIT", "A commitolt subgoal folytatásához szükséges skill/evidence várakozik",
                                         {"commitment_id": self.commitment.commitment_id,
                                          "waiting_for": ["MATCHING_COMMITTED_SKILL", "GOAL_RELEVANT_EVIDENCE"],
                                          "next_action": "RELEASE_COMMITMENT_AND_REPLAN"}, priority=98)
                self._release("STUCK_NO_MATCHING_PROPOSAL", now, "committed_skill_waiting_timeout")
        self._set_phase(RuntimePhase.REPLANNING, now, "choose_subgoal")
        if preferred.skill == "WAIT":
            self._set_phase(RuntimePhase.OBSERVING, now, "no_actionable_subgoal")
            return preferred
        self._commit(preferred, goal, world, now)
        self._set_phase(self._phase_for(preferred.skill, True), now, "execute_committed_subgoal")
        return preferred

    def on_execute(self, proposal: Proposal, now: float) -> None:
        self._set_phase(self._phase_for(proposal.skill, bool(self.commitment)), now, "skill_started")
        self._event("SKILL_OWNERSHIP_STARTED", now, proposal.reason, skill=proposal.skill)

    def on_verifying(self, now: float) -> None:
        self._set_phase(RuntimePhase.VERIFYING, now, "awaiting_skill_verification")

    def outcome(self, proposal: Proposal, success: bool, reason: str, world, now: float) -> None:
        if not self.commitment:
            return
        self.commitment.last_updated = now
        if not success:
            self.commitment.failures += 1
            if (self.commitment.kind == "ACQUIRE"
                    and proposal.skill == "ACQUIRE_TARGET"
                    and "expected_observation_missing" in str(reason).casefold()):
                # TARGETNEARESTENEMY may be reflected by the client one FAST
                # packet after the attempt deadline.  Keep the bounded ACQUIRE
                # commitment alive; choose() will promote only addon-confirmed
                # attackable identity, while the ordinary 3 s no-match budget
                # still prevents an endless wait when no unit is selected.
                self._set_phase(RuntimePhase.ACQUIRING, now,
                                "acquire_confirmation_grace")
                self._event("TARGET_CONFIRMATION_GRACE", now, reason)
                return
            if (self.commitment.kind == "TARGET" and proposal.skill == "TARGET"
                    and "expected_observation_missing" in str(reason).casefold()):
                # The click failed, not the addon-confirmed entity identity.
                # Keep that GUID committed and reacquire it visually instead
                # of falling through to another offline reference location.
                self._set_phase(RuntimePhase.TARGET_COMMITTED, now,
                                "target_click_unverified_identity_retained")
                self._event("TARGET_REACQUIRE_REQUIRED", now, reason,
                            target_guid=self.commitment.target_guid)
                return
            if (self.commitment.kind == "TARGET" and proposal.skill in {"INTERACT", "TALK"}
                    and any(token in str(reason).casefold() for token in (
                        "need to be closer", "too far away", "out of range", "közelebb", "túl messze"))):
                self._set_phase(RuntimePhase.TARGET_COMMITTED, now, "interaction_target_out_of_range")
                self._event("INTERACTION_RANGE_EVIDENCE", now, reason,
                            target_guid=self.commitment.target_guid)
                return
            if (self.commitment.kind == "TARGET" and proposal.skill in {"INTERACT", "TALK"}
                    and "expected_observation_missing" in str(reason).casefold()
                    and world.query.target().get("guid") == self.commitment.target_guid):
                # Missing dialog evidence does not disprove the already
                # selected identity. Under slow addon export it is also a
                # range hypothesis; retain commitment so the planner can use
                # a fresh visual anchor instead of opening the map immediately.
                self._set_phase(RuntimePhase.TARGET_COMMITTED, now,
                                "interaction_effect_unobserved_target_retained")
                self._event("INTERACTION_RANGE_CANDIDATE", now, reason,
                            target_guid=self.commitment.target_guid)
                return
            if (self.commitment.kind == "TARGET" and proposal.skill == "VISUAL_APPROACH"
                    and "visual_track_lost" in str(reason).casefold()
                    and world.query.target().get("guid") == self.commitment.target_guid):
                # Same shape as the TARGET/INTERACT/TALK exemptions above:
                # losing the 3D screen-space track disproves nothing about
                # the addon-confirmed identity (guid/name/attackable), only
                # the visual servo's own anchor. Live-confirmed 2026-09-12:
                # without this, any visual_track_lost released the whole
                # commitment -- including its "TARGET" kind and target_guid
                # -- even though the addon still reported the same creature
                # as a valid, attackable target. The next replan then had
                # nothing to commit to but a fresh TRANSIENT/INSPECT
                # subgoal, and COMBAT (which requires a TARGET commitment)
                # could never be proposed again for a target the bot was
                # still demonstrably fighting.
                if self.commitment.visual_track_lost_since is None:
                    self.commitment.visual_track_lost_since = now
                if now - self.commitment.visual_track_lost_since < 10.0:
                    self._set_phase(RuntimePhase.TARGET_COMMITTED, now,
                                    "visual_track_lost_identity_retained")
                    self._event("TARGET_REACQUIRE_REQUIRED", now, reason,
                                target_guid=self.commitment.target_guid)
                    return
                # Live-observed 2026-09-13: unbounded, this exemption let
                # VISUAL_APPROACH retry identically 50 times over ~2 minutes
                # on one subject before engine.py's separate approach_counts
                # budget forced MANUAL. Keep the identity commitment (still
                # nothing disproves it) but stop matching VISUAL_APPROACH
                # itself for a while (_matching() checks this flag) so the
                # next replan is forced to try something else -- REACQUIRE_
                # TARGET first, since it still matches the same commitment.
                self.commitment.visual_approach_blocked = True
                self.commitment.visual_track_lost_since = None
                self._set_phase(RuntimePhase.TARGET_COMMITTED, now,
                                "visual_approach_repeated_failure_blocked")
                self._event("TARGET_REACQUIRE_REQUIRED", now, reason,
                            target_guid=self.commitment.target_guid)
                return
            if (self.commitment.kind == "TARGET" and proposal.skill == "VISUAL_APPROACH"
                    and "visual_approach_safety_deadline" in str(reason).casefold()
                    and world.query.target().get("guid") == self.commitment.target_guid):
                # A 30s approach attempt that never converged (still tracking,
                # just not closing distance/centering fast enough) disproves
                # nothing about the addon-confirmed identity, only this one
                # approach trajectory. Unlike visual_track_lost there is no
                # flicker to wait out -- a full 30s already elapsed -- so
                # block VISUAL_APPROACH immediately and force REACQUIRE_TARGET
                # /replan instead of releasing the whole commitment through
                # the generic SKILL_FAILED path below. Live-observed
                # 2026-09-13: without this exemption, this reason fell
                # straight through to a full commitment release every time,
                # and since visual_approach.py's start() also never reset its
                # own 30s clock for a same-identity restart, the immediately
                # re-committed VISUAL_APPROACH re-hit the same expired
                # deadline on its very next tick -- a 9+ minute freeze where
                # no new Attempt ever completed, so this block-based retry
                # limit and the separate approach_counts budget in engine.py
                # never got a chance to run. Fixed together with that reset.
                self.commitment.visual_approach_blocked = True
                self._set_phase(RuntimePhase.TARGET_COMMITTED, now,
                                "visual_approach_repeated_failure_blocked")
                self._event("TARGET_REACQUIRE_REQUIRED", now, reason,
                            target_guid=self.commitment.target_guid)
                return
            if self.commitment.kind == "TARGET" and proposal.skill in {"COMBAT", "DEFEND"}:
                live_target = world.query.target()
                if (live_target.get("guid") == self.commitment.target_guid
                        and live_target.get("attackable", live_target.get("is_attackable")) is True
                        and not live_target.get("dead", live_target.get("is_dead"))):
                    # COMBAT/DEFEND is a multi-shot skill -- killing something
                    # takes many ability casts, not one. Same shape as the
                    # exemptions above: a single failed cast attempt (ability
                    # still on cooldown, briefly out of range, verify()
                    # missing the effect in time -- e.g. the stale-actionbar
                    # bug fixed earlier the same day) disproves nothing about
                    # the addon-confirmed identity, which is still alive and
                    # attackable. Live-confirmed 2026-09-12: without this, a
                    # single failed COMBAT attempt released the whole
                    # commitment exactly like the unhandled VISUAL_APPROACH
                    # failure did -- fixing that one surfaced this as the
                    # next thing standing between one engagement and
                    # actually finishing a kill.
                    self._set_phase(RuntimePhase.TARGET_COMMITTED, now,
                                    "combat_attempt_unverified_target_retained")
                    self._event("TARGET_REACQUIRE_REQUIRED", now, reason,
                                target_guid=self.commitment.target_guid)
                    return
            self._release("SKILL_FAILED", now, reason)
            return
        self.commitment.successful_actions += 1
        target = world.query.target()
        if (self.commitment.kind == "ACQUIRE" or proposal.skill == "TARGET") and target.get("guid"):
            if (self.commitment.kind == "ACQUIRE"
                    and not self._target_is_locatable(world, target, now)):
                self._release("BLIND_TARGET_UNLOCATABLE", now,
                              "acquired_identity_without_visual_anchor_or_range_evidence")
                return
            self.commitment.kind = "TARGET"
            self.commitment.target_guid = target["guid"]
            self.commitment.entity_key = self._entity_key(target)
            self.commitment.target_missing_observations = 0
            self.commitment.target_missing_since = None
            self.commitment.visual_track_lost_since = None
            self.commitment.visual_approach_blocked = False
            self._set_phase(RuntimePhase.TARGET_COMMITTED, now, "target_identity_verified")
            self._event("TARGET_COMMITTED", now, "target_identity_verified", target_guid=target["guid"])
            return
        if proposal.skill in {"APPROACH_TARGET", "VISUAL_APPROACH", "REACH_OBJECT", "COMBAT", "DEFEND", "FOLLOW_INSTRUCTION"}:
            if proposal.skill == "VISUAL_APPROACH":
                # A genuinely successful approach step proves the 3D anchor
                # is tracking again -- lift the temporary block so future
                # visual_track_lost bursts get their own full grace window
                # instead of inheriting an old one.
                self.commitment.visual_track_lost_since = None
                self.commitment.visual_approach_blocked = False
            self._set_phase(RuntimePhase.TARGET_COMMITTED, now, "committed_skill_step_verified")
            return
        if self.commitment.kind == "TARGET" and (proposal.skill in {"OPEN_MAP", "CLOSE_MAP"}
                or proposal.skill == "INSPECT" and proposal.parameters.get("source") in {"WORLD3D", "WORLD_MAP_CV"}):
            self._set_phase(RuntimePhase.TARGET_COMMITTED, now, "target_search_observation_verified")
            return
        if proposal.skill == "LOOT":
            self._release("QUEST_PROGRESS", now, reason)
            return
        if proposal.skill in {"MOVE", "FOLLOW", "REACH_LOCATION"}:
            self._release("ARRIVED", now, reason)
            return
        if self.commitment.kind == "TRANSIENT" or proposal.skill in TRANSIENT_SKILLS | {"TALK", "INTERACT"}:
            self._release("SKILL_VERIFIED", now, reason)

    def snapshot(self) -> dict:
        return {"phase": self.phase.value,
                "commitment": asdict(self.commitment) if self.commitment else None,
                "replan_revision": self.replan_revision,
                "last_replan_trigger": self.last_replan_trigger,
                "lifecycle": list(self.lifecycle[-30:])}
