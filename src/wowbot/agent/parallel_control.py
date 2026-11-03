"""Compatible fast activities under ONE canonical active skill.

Unlike projekt_parallel's MOVE-only hook this advances the existing visual,
target, interaction, loot and combat FSMs too. It owns no second attempt,
planner, navigation controller or executor. Terminal results are handed to
the medium engine for durable verification/bookkeeping, never finalized here.
"""
from __future__ import annotations

from collections import Counter, deque
from types import SimpleNamespace

from wowbot.execution.command_dispatch import DispatchLane
from wowbot.execution.resource_arbiter import PRIORITY, Resource, ResourceArbiter
from .fast_movement_lane import advance_fast_movement
from .models import Mode, Outcome, number
from .parallel_view import control_safety, control_view
from .pointer_tracking import follow_pointer, live_pointer_point

MOVEMENT = frozenset({"MOVE", "FOLLOW", "REACH_OBJECT", "REACH_LOCATION"})
FAST_SKILLS = MOVEMENT | {"VISUAL_APPROACH", "SEEK_VISUAL_CUE", "TARGET", "INTERACT", "TALK",
                          "COMBAT", "DEFEND", "LOOT", "OBJECT_USE", "USE_ON_TARGET", "INSPECT"}


class ParallelControl:
    def __init__(self, agent):
        self.agent = agent
        self.enabled = False                 # enabled only by the live runtime lifecycle
        self.arbiter = ResourceArbiter()
        self.terminal = None
        self.expected_epoch = None
        self.last_reason = "disabled"
        self.counts = Counter()
        self.events = deque(maxlen=64)
        self.update_times = deque(maxlen=180)
        self.pointer_times = deque(maxlen=180)
        self.attention = {}
        self._identity_notified = None
        self._last_action = None
        self._last_observation = None
        self._last_control_at = -1e9
        from .track_motion import TrackMotion
        self.motion = TrackMotion()
        self._motion_context = None

    def drives(self, attempt, now):
        """Do not run the same FSM again on a lagging medium snapshot.

        Medium fusion/safety/planning still runs. Inspection verification,
        deadline handling and an explicit movement handoff stay with it.
        """
        return (self.enabled and attempt.proposal.skill in FAST_SKILLS - {"INSPECT"}
                and attempt.action_id == self._last_action
                and self.last_reason not in {"movement_ground_approach_pending", "movement_position_acquired_pending",
                                             'skill_navigation_plan_pending'}
                and self.last_reason!='movement_route_plan_pending'
                # The medium caller may have sampled its clock just before
                # this fast update. A newer control sample is not stale.
                and now < attempt.deadline and self._last_control_at >= now-.25)

    def stop(self, now, reason):
        self.arbiter.revoke_all(now, reason)
        self.last_reason = reason
        self.agent.command_dispatcher.stop_movement()

    def take_terminal(self, action_id):
        terminal, self.terminal = self.terminal, None
        return terminal[1] if terminal is not None and terminal[0] == action_id else None

    def _dispatch(self, commands, lane, now, channel):
        if not commands:
            return
        # The agent lock serializes the physical command groups; leases make
        # compatible ownership observable and keep attention off another
        # channel's mouse. Denial never drops an interaction/click command.
        pointer = all(command.kind == "POINTER" for command in commands)
        resources = ({Resource.MOUSE} if pointer else
                     {Resource.LEGS, Resource.BODY_YAW} if lane is DispatchLane.MOVEMENT else
                     {Resource.LEGS, Resource.MOUSE, Resource.ACTION_KEYS})
        owner = "ATTENTION" if pointer else channel
        if not pointer:
            # One canonical FSM may change from turn/approach to interaction
            # in the next sample. This is a handoff within the SAME attempt,
            # not a competing independent skill at a different priority.
            for previous in ("COMBAT", "INTERACTION", "LOCOMOTION"):
                self.arbiter.release(previous, resources)
        if not self.arbiter.request(owner, resources, PRIORITY[owner], now,
                                    ttl=.04 if pointer else .10):
            if pointer:
                self.counts["mouse_busy"] += 1
                return
            # Active canonical execution preempts advisory attention only.
            self.arbiter.release("ATTENTION")
            if not self.arbiter.request(owner, resources, PRIORITY[owner], now, ttl=.10):
                self.stop(now, "resource_conflict")
                raise RuntimeError("Conflicting canonical control resources")
        self.agent.command_dispatcher.dispatch(commands, lane,
            correlation_id=self.agent.pending.action_id)
        self.counts["dispatches"] += 1
        if pointer:
            self.pointer_times.append(now)
        self.events.append({"at": now, "action_id": self.agent.pending.action_id,
                            "channel": owner, "commands": [c.kind if not c.binding else c.binding for c in commands]})

    def _attention(self, state, now):
        agent = self.agent
        owned, command = agent._active_target_pointer(state, now)
        if owned:
            if command is not None:
                self._dispatch((command,), DispatchLane.DISCRETE, now, "ATTENTION")
            return
        skill = agent.pending.proposal.skill
        if skill not in MOVEMENT | {"WAIT", "WAIT_EVENT"} or state.get("is_in_combat"):
            return
        from .quest_giver_evidence import subject_has_quest_symbol
        from .object_interaction_flow import open_object_objective, quest_object_candidates
        boxes = state.get("visual_candidates") or ()
        objects = quest_object_candidates(state) if open_object_objective(state) else []
        candidates = [box for box in objects if live_pointer_point(state, box.get("track_id"), now)]
        if not candidates:
            candidates = [box for box in boxes if subject_has_quest_symbol(box, boxes)
                          and live_pointer_point(state, box.get("track_id"), now)]
        if not candidates:
            self.arbiter.release("ATTENTION")
            self.attention.clear()
            return
        committed = self.attention.get("track_id")
        candidate = next((box for box in candidates if box.get("track_id") == committed), None)
        candidate = candidate or max(candidates, key=lambda box: number(box.get("bbox_height_fraction")) or 0.)
        if candidate.get("track_id") != committed:
            self.attention = {"acquired_at": now}
        command = follow_pointer(self.attention, state, candidate.get("track_id"), now)
        if command is not None:
            self._dispatch((command,), DispatchLane.DISCRETE, now, "ATTENTION")

    def tick(self, payload, received_at, vision, now):
        agent = self.agent
        if not self.enabled or agent.mode != Mode.FULL_AI or agent.pending is None:
            return {"consumed": False}
        # The control thread never waits behind planning/database work. The
        # existing input watchdog expires a lease if no safe refresh can run.
        if not agent.lock.acquire(blocking=False):
            self.counts["busy_skips"] += 1
            return {"consumed": False, "reason": "canonical_owner_busy"}
        try:
            return self._tick_locked(payload, received_at, vision, now)
        finally:
            agent.lock.release()

    def _tick_locked(self, payload, received_at, vision, now):
        agent = self.agent
        if agent.mode != Mode.FULL_AI or agent.pending is None:
            return {"consumed": False}
        attempt = agent.pending
        skill = attempt.proposal.skill
        if skill not in FAST_SKILLS:
            return {"consumed": False}
        allows_flight = getattr(agent.navigation, "flight_controls_allowed", None)
        flight_control = callable(allows_flight) and allows_flight({**agent.world.state, **payload})
        reason = control_safety(agent.world.state, payload, received_at, now, flight_control=flight_control)
        # Combat may move/act within its own attempt, never hijack a quest MOVE.
        if payload.get("is_in_combat") and skill not in {"COMBAT", "DEFEND"}:
            reason = "combat_preemption"
        if vision is not None:
            context = vision.get("context")
            if (context is not None and tuple(context[:3]) != (
                    payload.get("session_id"), agent.world.state.get("character_guid"),
                    agent.world.state.get("map_id"))):
                reason = "vision_context_changed"
            if self.expected_epoch is not None and vision.get("epoch") != self.expected_epoch:
                reason = "vision_epoch_changed"
        if ((payload.get("loot_ui", agent.world.state.get("loot_ui")) or {}).get("open")
                and skill != "LOOT"):
            reason = "loot_ui"
        if reason:
            self._last_control_at = -1e9
            self.stop(now, reason)
            return {"consumed": False, "force_medium": True, "reason": reason}
        if self.terminal is not None:
            if self.terminal[0] == attempt.action_id:
                return {"consumed": True, "terminal": True}
            self.terminal = None
        if attempt.action_id != self._last_action:
            self._last_action = attempt.action_id
            self.attention.clear()
            self.arbiter.revoke_all(now, "new_attempt")
        state = control_view(agent.world.state, payload, vision, now)
        from .world_packet_reducer import WorldPacketReducer
        WorldPacketReducer.project_own_navigation(agent.world, state, now)
        self._last_control_at = now
        frame = (payload.get("fast_sequence"), payload.get("frame_id"),
                 vision.get("revision") if vision else None)
        identity = (attempt.action_id, frame)
        # New vision may re-aim between addon packets, but repeated old addon
        # data cannot renew movement indefinitely (control_safety checks age).
        if identity == self._last_observation:
            return {"consumed": True, "reason": "awaiting_new_control_observation"}
        self._last_observation = identity
        motion_context = (payload.get("session_id"), state.get("map_id"), vision.get("epoch") if vision else None)
        if motion_context != self._motion_context:
            from .track_motion import TrackMotion
            self.motion = TrackMotion()
            self._motion_context = motion_context
        # Measure the freshest boxes here, not a 1--3 Hz memory projection.
        # This is bounded aiming evidence, never ID association or pathing.
        self.motion.observe(state)
        self.update_times.append(now)
        self.counts[skill] += 1
        agent.world.last_received = max(agent.world.last_received, received_at)
        observation_id = f"parallel:{attempt.action_id}:{frame}"
        casting = bool(state.get("is_casting") or state.get("is_channeling"))
        if casting and skill == 'OBJECT_USE':
            from wowbot.skills.object_pull import channel_movement_allowed
            casting = not channel_movement_allowed(agent.active_skill.state,state,now)
        if casting:
            agent.command_dispatcher.stop_movement()
            self.arbiter.request("CAST_HOLD", {Resource.LEGS, Resource.BODY_YAW},
                                 PRIORITY["SAFETY"], now, ttl=.10)
            self._attention(state, now)
            if skill not in {"OBJECT_USE", "USE_ON_TARGET"}:
                # Only these two domain verifiers explicitly support
                # credit/cast observation without advancing a click stage.
                # Other FSMs must not "send" a command that we then withhold.
                self.last_reason = "cast_hold"
                return {"consumed": True, "reason": "cast_hold",
                        "force_medium": now >= attempt.deadline}
        else:
            self.arbiter.release("CAST_HOLD")
        if skill in MOVEMENT:
            self.arbiter.request("LOCOMOTION", {Resource.LEGS, Resource.BODY_YAW},
                                 PRIORITY["LOCOMOTION"], now, ttl=.10)
            result = advance_fast_movement(agent, payload, now, MOVEMENT, state_override=state,
                                           steer_pointer=False)
            if result.get("reason") in {"movement_ground_approach_pending", "movement_position_acquired_pending",
                                        'movement_route_plan_pending'}:
                # Let the medium FSM own the route replan on this same MOVE.
                self._last_control_at = -1e9
            if result.get("terminal"):
                self.arbiter.release("LOCOMOTION")
                terminal = agent._fast_control_terminal or {}
                step = agent.active_skill_supervisor._verified_outcome(
                    skill, Outcome.SUCCESS if terminal.get("success") else Outcome.FAILURE,
                    str(terminal.get("reason") or "fast_navigation_terminal"), state,
                    stop_movement=True, verifier="MOVEMENT_POSTCONDITION_VERIFIER")
                self.terminal = (attempt.action_id, step)
                result["force_medium"] = True
            if not result.get("terminal") and not result.get("force_medium"):
                self._attention(state, now)
                mouse = state.get("mouseover") or {}
                identity = (self.attention.get("track_id"), mouse.get("guid"), mouse.get("object_id"))
                if (identity[0] and (identity[1] or identity[2] or mouse.get("quest_related"))
                        and identity != self._identity_notified):
                    self._identity_notified = identity
                    result["force_medium"] = True
            self.last_reason = str(result.get("reason") or "moving")
            return result
        if not casting:
            self._attention(state, now)
        if skill == "INSPECT":
            self.last_reason = "inspect_following"
            return {"consumed": True}
        world = SimpleNamespace(state=state, latest=SimpleNamespace(
            source="FAST_CONTROL", payload={}, observation_id=observation_id))
        step = agent.active_skill_supervisor.step(attempt, agent.active_skill.state, world,
            world_observation_id=observation_id, visual_observation_id=observation_id, now=now,
            segment_baseline=agent._movement_segment_baseline, allow_route_queries=False)
        self.last_reason = step.reason or "active_skill_control"
        if step.stop_movement:
            agent.command_dispatcher.stop_movement()
        if step.yield_tick:
            self._last_control_at = -1e9
            self.arbiter.release('LOCOMOTION')
            return {'consumed':False, 'force_medium':True, 'reason':self.last_reason}
        if step.terminal_outcome is not None:
            self.terminal = (attempt.action_id, step)
            agent.command_dispatcher.stop_movement()
            return {"consumed": True, "terminal": True, "force_medium": True}
        if step.set_segment_baseline:
            agent._movement_segment_baseline = state.copy()
        if casting:
            # Keep observing cast/credit/death in the owning verifier, but
            # never dispatch a click, key or turn that interrupts the cast.
            self.last_reason = "cast_hold"
            return {"consumed": True, "reason": "cast_hold",
                    "force_medium": now >= attempt.deadline}
        channel = "COMBAT" if skill in {"COMBAT", "DEFEND"} else "INTERACTION"
        lane = DispatchLane.MOVEMENT if step.movement_lane else DispatchLane.DISCRETE
        if step.movement_lane:
            self.arbiter.release("INTERACTION", [Resource.LEGS, Resource.BODY_YAW])
        if step.commands:
            self._dispatch(tuple(step.commands), lane, now,
                           "LOCOMOTION" if step.movement_lane else channel)
            motion = step.diagnostics.get('post_use_motion')
            if motion:
                self.events[-1]['post_use_motion'] = motion
                if motion.get('steps') == 1:
                    agent._record(now,'OBJECT_POST_USE_MOTION_STARTED',{
                        'action_id':attempt.action_id,'post_use_motion':motion})
        return {"consumed": True}

    def snapshot(self, now):
        def rate(values):
            recent = [at for at in tuple(values) if 0 <= now-at < 3.]
            return round((len(recent)-1)/max(.001, recent[-1]-recent[0]), 2) if len(recent) > 1 else 0.
        return {"enabled": self.enabled, "implementation": "shared-fast-channels-v1",
                "authority": "ActiveSkillRuntime/CommandDispatcher",
                "control_hz": rate(self.update_times), "pointer_hz": rate(self.pointer_times),
                "reason": self.last_reason, "counts": dict(self.counts),
                "resources": self.arbiter.snapshot(now), "attention": dict(self.attention),
                "target_motion": self.motion.snapshot(self.attention.get("track_id") or
                    ((self.agent.active_skill.state.intent.parameters.get("track_id"))
                     if self.agent.active_skill.state else None)),
                "recent": list(self.events)[-12:]}

    def owns_attention(self):
        if not self.enabled:
            return False
        if self.attention.get("track_id"):
            return True
        active = self.agent.active_skill.state
        if active is None:
            return False
        controller = active.skill_context.get("visual_approach_controller")
        return bool(active.intent.parameters.get("track_id")
                    or controller is not None and (controller.intent or {}).get("track_id"))
