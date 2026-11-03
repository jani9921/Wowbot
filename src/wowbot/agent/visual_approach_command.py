"""VisualApproachController.command(): turns the current assessment into movement/pointer commands.

Split out of visual_approach.py (2026-10-05); unchanged.
"""
from __future__ import annotations
import math
from .models import Command, number
from .visual_approach_types import VisualApproachPhase
from wowbot.runtime.skill_identity import check_interaction_recipient, expected_identity


class VisualApproachCommandMixin:
    """Methods of VisualApproachController (visual_approach.py); moved verbatim."""

    def command(self, state: dict, observation_id: str, now: float) -> tuple[Command, ...]:
        if ((state.get("quest_ui") or {}).get("open") is True
                or state.get("quest_ui_open") is True
                or (state.get("gossip_ui") or {}).get("open") is True
                or state.get("gossip_open") is True):
            return ()
        # command() also runs on fast-lane refreshes of the same visual
        # observation. Never re-lease movement from a now-lost/stale GUID.
        if not self._approach_identity_check(state, now):
            return ()
        # HOVER has moved the physical pointer and the movement lease was
        # deliberately released by the executor.  Do not issue another W
        # refresh until a *new* addon mouseover sample either confirms or
        # disproves the visual association.
        if self.identity_recheck_requested_at is not None:
            return ()
        if self.phase == VisualApproachPhase.OCCLUDED:
            edge = self._exit_edge(now)
            if edge is not None:
                if self.edge_recovery_started_at is None:
                    self.edge_recovery_started_at = now
                if (now-self.edge_recovery_started_at <= 1.5
                        and now-self.last_edge_command_at >= .15):
                    self.last_edge_command_at = now
                    self.edge_corrections += 1
                    self.control_updates += 1
                    self.last_command_at = now
                    binding, duration = {
                        "BOTTOM": ("MOVEBACKWARD", .20),   # ran past it: step back
                        "LEFT": ("TURNLEFT", .08),         # over-turned: turn back
                        "RIGHT": ("TURNRIGHT", .08),
                        "TOP": ("MOVEFORWARD", .12),       # fell behind: close in
                    }[edge]
                    return (Command("BIND", binding, duration),)
            # Purposeful widening scan around the last screen bearing. With
            # follow-camera enabled this is a bounded player-yaw pulse, so the
            # character and camera rotate together without changing identity.
            predicted = bool(self.samples and self.samples[-1].predicted)
            scan_steps = {1, 3, 5} if predicted else {2, 4, 6}
            target = state.get("target") or {}
            committed_guid = str((self.intent or {}).get("guid") or "")
            # While the exact committed GUID is still selected, never rotate
            # or move blindly. The prior implementation sent only
            # INTERACTTARGET here. In a live Jaina run the World3D projection
            # briefly dropped despite the NPC still being visibly selected;
            # those probes could neither restore a visual anchor nor safely
            # advance. First re-hover the last *freshly GUID-confirmed* point
            # while stationary. That lets the WorldModel bind any newly
            # published candidate to the selected identity again. It is a
            # bounded perception action, never a click or a guessed move.
            if committed_guid and target.get("guid") == committed_guid:
                candidate = self._selected_target_recheck_candidate(state, now)
                if candidate is None and self._requires_identity_recheck():
                    candidate = self._reacquire_hover_candidate(state)
                if (candidate is not None
                        and (self.last_occluded_reacquire_at is None
                             or now-self.last_occluded_reacquire_at >= .40)):
                    self.last_occluded_reacquire_at = now
                    self.identity_recheck_requested_at = now
                    self.identity_recheck_mouse_sample_before = number(
                        state.get("mouseover_sample_time"))
                    self.identity_recheck_track_id = str(candidate.get("track_id"))
                    self.identity_recheck_point = (float(candidate["x"]), float(candidate["y"]))
                    self.identity_rechecks += 1
                    self.control_updates += 1
                    self.last_command_at = now
                    return (Command("HOVER", x=float(candidate["x"]),
                                    y=float(candidate["y"]), duration=.05),)
                point = self.last_confirmed_hover_point
                if (point and self._requires_identity_recheck()
                        and 0 <= now-point.get("at", -math.inf) <= .75
                        and (self.last_occluded_reacquire_at is None
                             or now-self.last_occluded_reacquire_at >= .40)):
                    self.last_occluded_reacquire_at = now
                    self.identity_recheck_requested_at = now
                    self.identity_recheck_mouse_sample_before = number(
                        state.get("mouseover_sample_time"))
                    self.identity_recheck_track_id = None
                    self.identity_recheck_point = (point["x"], point["y"])
                    self.identity_rechecks += 1
                    self.control_updates += 1
                    self.last_command_at = now
                    return (Command("HOVER", x=point["x"], y=point["y"], duration=.05),)
                # A bounded INTERACTTARGET probe remains authoritative after a
                # reacquisition try: it opens the UI at real client range and
                # otherwise returns the same explicit range feedback.
                if (self.intent.get("purpose") == "INTERACT"
                        and not self.intent.get("item_use_approach")
                        and check_interaction_recipient(expected_identity(self.intent), state, now)
                        and (self.last_interaction_probe_at is None
                             or now-self.last_interaction_probe_at >= 1.2)):
                    self.last_interaction_probe_at = now
                    self.control_updates += 1
                    self.last_command_at = now
                    return (Command("BIND", "INTERACTTARGET", .05),)
                return ()
            identify_scan = (self.intent or {}).get("purpose") == "IDENTIFY"
            if identify_scan:
                # SEEK_VISUAL_CUE owns an UNKNOWN cue, not a confirmed unit.
                # Reacquire it with the same slow one-way sweep used by the
                # outer search controller.  Alternating at successive missing
                # frames made the camera whip before a new detector result
                # could arrive and repeatedly threw distant quest badges out
                # of view.
                if (self.last_occluded_reacquire_at is not None
                        and now-self.last_occluded_reacquire_at + 1e-9 < .90):
                    return ()
                self.last_occluded_reacquire_at = now
                self.reacquire_actions += 1
                return (Command("BIND", "TURNLEFT", .16),)
            if self.missing_observations in scan_steps:
                last_x = self.samples[-1].x if self.samples and self.samples[-1].x is not None else .5
                direction = -1 if self.missing_observations % 4 == 0 else 1
                endpoint = max(.32, min(.68, .5 + direction*max(.06, abs(last_x-.5)*.35)))
                self.reacquire_actions += 1
                turn = "TURNRIGHT" if endpoint >= .5 else "TURNLEFT"
                return (Command("BIND", turn, .07),)
            return ()
        if self.phase in {VisualApproachPhase.IDLE,
                          VisualApproachPhase.INTERACTION_READY, VisualApproachPhase.FAILED}:
            return ()
        sample = self.samples[-1] if self.samples else None
        if not sample or sample.center_error is None:
            return ()
        # FAST_STATE telemetry can arrive many times while the pixel-strip
        # projection is unchanged.  It may update range/UI facts, but it must
        # never keep refreshing W from one frozen visual measurement.
        # A brief gap between distinct visual samples must not release the
        # forward lease (live 2026-10-01: 1.5 s of stop-and-go); a still
        # fresh measurement may re-lease W every .25 s, never a stale one.
        if (now-sample.visual_sample_time > .45
                or (sample.visual_sample_time == self.last_command_visual_sample_time
                    and now-(self.last_command_at or -1e9) < .25)):
            return ()
        error = sample.center_error
        # Generic proposal height is not calibrated entity distance. The live
        # Jaina track measured ~.093 while still roughly sixteen yards away,
        # so treating .085 as "near" caused MOVE/probe alternation after every
        # single update. Only a much stronger scale cue shortens the probe
        # cadence; the authoritative INTERACT result remains the range check.
        near = sample.bbox_height is not None and sample.bbox_height >= .12
        closing_fast = (sample.bbox_scale_delta is not None
                        and sample.bbox_scale_delta >= .003)
        probe_updates = 3 if near or closing_fast else 5
        probe_interval = .8 if near or closing_fast else 1.2
        # User 2026-10-01: approach continuously until arrival, no separate
        # click to learn "out of range".  Each INTERACTTARGET probe (and its
        # lease release) made the walk stop-and-go; arrival is decided by the
        # visual scale (learned per GUID from real client range errors).
        if (self.range_probe_enabled and self.intent.get("purpose") == "INTERACT"
                and not self.intent.get("item_use_approach")
                and check_interaction_recipient(expected_identity(self.intent), state, now)
                and str((state.get("target") or {}).get("guid") or "")
                    == str(self.intent.get("guid") or "")
                and self.forward_updates_since_probe >= probe_updates
                and (self.last_interaction_probe_at is None
                     or now-self.last_interaction_probe_at >= probe_interval)):
            # The selected GUID makes this a safe, authoritative range probe.
            # It opens the interaction immediately at real client range and
            # avoids estimating yards solely from apparent bbox scale.
            self.last_interaction_probe_at = now
            self.forward_updates_since_probe = 0
            self.control_updates += 1
            self.last_command_at = now
            self.last_command_visual_sample_time = sample.visual_sample_time
            return (Command("BIND", "INTERACTTARGET", .05),)
        # User 2026-10-01: approach without the pointer on the NPC; only once
        # in range re-hover it.  Mid-approach re-hovers released W.
        if (self._requires_identity_recheck()
                and self.final_align_started_at is not None):
            # Freeze the movement lease while this exact, live visual point is
            # checked.  Without this checkpoint a stale mouseover↔track
            # association can drive several yards past a selected NPC.
            self.identity_recheck_requested_at = now
            self.identity_recheck_mouse_sample_before = number(state.get("mouseover_sample_time"))
            # This is a direct checkpoint of the already-bound track.  A
            # failure remains terminal; only speculative replacement-track
            # probes populate identity_recheck_track_id and may be skipped.
            self.identity_recheck_track_id = None
            self.identity_rechecks += 1
            self.control_updates += 1
            self.last_command_at = now
            self.last_command_visual_sample_time = sample.visual_sample_time
            if not (sample.x is not None and sample.y is not None
                    and 0. < sample.x < 1. and 0. < sample.y < 1.):
                return ()
            self.identity_recheck_point = (sample.x, sample.y)
            return (Command("HOVER", x=sample.x, y=sample.y, duration=.05),)
        # Pointer following has its own engine hook. Returning only POINTER
        # here would consume this movement update (at 30 Hz it starves W).
        turn = "TURNRIGHT" if error > 0 else "TURNLEFT"
        if self._last_turn and turn != self._last_turn and abs(error) > .055:
            self.steering_reversals += 1
        if abs(error) > .055:
            self._last_turn = turn
        if self.intent.get("purpose") == "VEHICLE_AIM":
            # Aim only (see observe): walking into a cadaver gets knocked back.
            command = Command("BIND", turn, min(.10, max(.04, abs(error)*.25)))
        elif self.final_align_started_at is not None:
            # In range: face the NPC without walking past it.
            # The executor accepts movement leases of .04-.35 s only (live
            # 2026-10-01: a .03 s face-align turn was rejected and failed the
            # whole approach with executor_failure).
            command = Command("BIND", turn, min(.08, max(.04, abs(error)*.25)))
        elif abs(error) > .35:
            # Only a target far off-centre turns in place; otherwise keep the
            # forward lease and steer while walking (one continuous arc).
            command = Command("BIND", turn, min(.10, max(.04, abs(error)*.28)))
        elif abs(error) > .055:
            command = Command("BIND", "MOVEFORWARD", min(.08, max(.04, abs(error)*.22)),
                              simultaneous=(turn,))
        else:
            command = Command("BIND", "MOVEFORWARD", .05 if near else .16)
        if command.binding == "MOVEFORWARD":
            self.forward_updates_since_probe += 1
            self.forward_commands_total = getattr(self, "forward_commands_total", 0)+1
        self.control_updates += 1
        self.last_command_at = now
        self.last_command_visual_sample_time = sample.visual_sample_time
        return (command,)
