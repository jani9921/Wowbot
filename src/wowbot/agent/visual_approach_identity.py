"""VisualApproachController identity checks: addon mouseover confirmation and re-hover candidates.

Split out of visual_approach.py (2026-10-05); unchanged.
"""
from __future__ import annotations
import math
from .models import Command, number
from .pointer_tracking import follow_pointer
from wowbot.runtime.entity_identity import IdentityCheck, check_entity_identity
from wowbot.runtime.skill_identity import check_command_identity, expected_identity


class VisualApproachIdentityMixin:
    """Methods of VisualApproachController (visual_approach.py); moved verbatim."""

    def _approach_identity_check(self, state: dict, now: float) -> IdentityCheck:
        """A box may steer a search, never extend lost entity authority.

        Selected units use the same per-command gate as other skills. A
        GUID-less quest object instead needs its real current mouseover ID;
        it must not be rejected merely because GameObjects cannot be selected.
        The command below is an input-free description, never dispatched.
        """
        parameters = self.intent or {}
        if parameters.get("purpose") == "IDENTIFY":
            return IdentityCheck(True, "SEARCH_ONLY")
        role = "OBJECT_USE" if parameters.get("object_use_approach") else "APPROACH_TARGET"
        return check_command_identity(
            role, parameters, expected_identity(parameters), state,
            (Command("BIND", "MOVEFORWARD"),), now)

    def follow_pointer_command(self, state: dict, now: float) -> Command | None:
        """Track the active servo's live box without consuming a movement update."""
        rechecking = self.identity_recheck_requested_at is not None
        if (not self.pointer_tracking or not self.intent
                or self.phase.value in {"IDLE", "FAILED", "INTERACTION_READY"}
                or (not rechecking and self.phase.value not in {"ADVANCING", "CENTERING"})):
            return None
        guid = self.intent.get("guid")
        if guid and str((state.get("target") or {}).get("guid") or "") != str(guid):
            return None
        track_id = self.identity_recheck_track_id if rechecking else None
        track_id = track_id or self.intent.get("track_id")
        if not track_id or (not rechecking and str(track_id) in self.rejected_reacquire_track_ids):
            return None
        if state.get("is_in_combat") and self.intent.get("purpose") not in {
                "COMBAT", "VEHICLE_AIM", "VEHICLE_ATTACK"}:
            return None
        command = follow_pointer(self.pointer_follow_context, state, track_id, now)
        if command is not None:
            if rechecking:
                self.identity_recheck_point = (command.x, command.y)
            if self.pointer_tracking_track_id != track_id:
                self.pointer_tracking_track_id = track_id
                self.pointer_tracking_started_at = now
            self.last_pointer_hover_at = now
            self.pointer_hovers += 1
        return command

    def _reject_reacquire_track(self, track_id: str, state: dict) -> None:
        self.rejected_reacquire_track_ids.add(str(track_id))
        cursor = state.get("cursor_position") or {}
        x, y = number(cursor.get("nx")), number(cursor.get("ny"))
        if x is not None and y is not None:
            self.rejected_reacquire_positions[str(track_id)] = (x, y)

    def _selected_target_recheck_candidate(self, state: dict, now: float) -> dict | None:
        """Fresh selected-target binding authorizes a hover, never movement.

        A rejected box can move with the camera and again belong to the selected
        unit (Henry, 2026-10-15). Probe its current position instead of looping
        on the frozen starting pixel. A repeated negative at the same position
        remains rejected until fresh matching mouseover evidence arrives.
        """
        guid = str((self.intent or {}).get("guid") or "")
        target = state.get("target") or {}
        anchor = target.get("screen_position") or {}
        if (not guid or str(target.get("guid") or "") != guid
                or anchor.get("source") not in {"BOUND_WORLD3D_TRACK", "NAMEPLATE_API"}
                or not self._anchor_scene_valid(anchor, state, now)):
            return None
        track_id = str(anchor.get("track_id") or "")
        for item in state.get("visual_candidates") or ():
            observed_at = number(item.get("observed_at"))
            if (str(item.get("track_id") or "") != track_id or not track_id
                    or item.get("source") != "WORLD3D"
                    or "subject" not in str(item.get("detector_kind") or item.get("kind") or "")
                    or str(item.get("lifecycle") or "ACTIVE").upper() not in self._LIVE_LIFECYCLES
                    or item.get("coasting") or observed_at is None
                    or not 0 <= now-observed_at <= .75
                    or (number(item.get("confidence")) or 0.) < .30
                    or item.get("self_player_avatar") is True
                    or (item.get("visual_identity") or {}).get("kind") == "SELF_PLAYER"
                    or (item.get("appearance") or {}).get("self_avatar_suppression_hint")):
                continue
            x, y = number(item.get("x")), number(item.get("y"))
            if x is None or y is None:
                continue
            if track_id in self.rejected_reacquire_track_ids:
                previous = self.rejected_reacquire_positions.get(track_id)
                if not self._matching_fresh_mouseover(state, now) and (
                        previous is None or math.hypot(x-previous[0], y-previous[1]) < .035):
                    continue
            return item
        return None

    def _matching_fresh_mouseover(self, state: dict, now: float,
                                  *, after: float | None = None) -> bool:
        """Whether a *new* addon hover confirms the committed identity.

        The cursor and mouseover are sampled independently by the exporter;
        requiring both to be recent prevents an older tooltip from validating
        a HOVER that has already moved to another screen point.
        """
        expected = str((self.intent or {}).get("guid") or "")
        mouse = state.get("mouseover") or {}
        mouse_time = number(state.get("mouseover_sample_time"))
        cursor_time = number(state.get("cursor_sample_time"))
        if not expected or not check_entity_identity(expected_identity(self.intent), mouse):
            return False
        if mouse_time is None or not 0 <= now-mouse_time <= .75:
            return False
        if cursor_time is not None and not 0 <= now-cursor_time <= .75:
            return False
        if self.identity_recheck_requested_at is not None and not self._recheck_cursor_matches(state):
            return False
        return after is None or mouse_time > after + .000001

    def _recheck_cursor_matches(self, state: dict) -> bool:
        point = self.identity_recheck_point
        if point is None:
            return True
        cursor = state.get("cursor_position") or {}
        x, y = number(cursor.get("nx")), number(cursor.get("ny"))
        return x is not None and y is not None and math.hypot(x-point[0], y-point[1]) <= .015

    def _pointer_names_other_unit(self, state: dict, now: float) -> str | None:
        """Track id under the pointer when a fresh mouseover names another GUID.

        Only evaluated after our own POINTER put the cursor on the followed
        box and the cursor is still there; a confirming sample marks the
        track as identity-confirmed instead.
        """
        expected = str((self.intent or {}).get("guid") or "")
        track_id = (self.intent or {}).get("track_id")
        if not expected or not track_id or self.last_pointer_hover_at == -float("inf"):
            return None
        mouse = state.get("mouseover") or {}
        mouse_time = number(state.get("mouseover_sample_time"))
        pointer_started = (self.pointer_tracking_started_at
                           if self.pointer_tracking_started_at is not None else self.last_pointer_hover_at)
        if (mouse_time is None or mouse_time <= pointer_started + .03
                or not 0 <= now-mouse_time <= .75):
            return None
        cursor = state.get("cursor_position") or {}
        cx, cy = number(cursor.get("nx")), number(cursor.get("ny"))
        sample = self.samples[-1] if self.samples else None
        if (sample is None or None in (cx, cy, sample.x, sample.y)
                or math.hypot(cx-sample.x, cy-sample.y) > 2*self.POINTER_IDENTITY_TOLERANCE):
            return None
        guid = str(mouse.get("guid") or "")
        if not guid:
            return None
        if check_entity_identity(expected_identity(self.intent), mouse):
            self.identity_confirmed_track_id = track_id
            return None
        return str(track_id)

    def _identity_recheck_failed(self, state: dict, now: float) -> bool:
        """Return true only after a requested hover had time to answer."""
        requested = self.identity_recheck_requested_at
        if requested is None:
            return False
        mouse = state.get("mouseover") or {}
        mouse_time = number(state.get("mouseover_sample_time"))
        expected = str((self.intent or {}).get("guid") or "")
        # A new, different GUID is direct contradictory evidence.  A missing
        # sample is allowed only for the bounded addon-latency window.
        if (mouse_time is not None and mouse_time > (self.identity_recheck_mouse_sample_before or -math.inf) + .000001
                and mouse.get("guid") and str(mouse.get("guid")) != expected
                and self._recheck_cursor_matches(state)):
            return True
        return now-requested >= self.identity_recheck_timeout_seconds

    def _requires_identity_recheck(self) -> bool:
        """Only re-hover a one-shot mouseover↔World3D association.

        A direct `NAMEPLATE_API` target position and the generic unit-test
        servo already have their own tracking authority.  The live failure
        involved precisely the weaker `CANDIDATE` association created from a
        cursor hover, so keep the extra probe scoped to that case.
        """
        screen = (self.intent or {}).get("screen_position") or {}
        track_id = (self.intent or {}).get("track_id")
        if track_id is not None and track_id == self.identity_confirmed_track_id:
            return False
        return (self.intent or {}).get("purpose") == "INTERACT" and (
            screen.get("source") in {"CONFIRMED_MOUSEOVER", "CONFIRMED_MOUSEOVER_ANCHOR"}
            and screen.get("track_association") == "CANDIDATE")

    def _reacquire_hover_candidate(self, state: dict) -> dict | None:
        """Choose a plausible new visual track to verify with addon hover.

        This does not reassign identity.  It only chooses where to put the
        pointer while the exact selected GUID remains authoritative.  The
        track is adopted later only if that hover returns the same GUID.
        """
        current_id = str((self.intent or {}).get("track_id") or "")
        previous_height = next((sample.bbox_height for sample in reversed(self.samples)
                                if not sample.predicted and sample.bbox_height is not None), None)
        ranked = []
        for item in state.get("visual_candidates", []):
            kind = str(item.get("detector_kind") or item.get("kind") or "")
            lifecycle = str(item.get("lifecycle") or item.get("track_state") or "ACTIVE").upper()
            appearance = item.get("appearance") or {}
            identity = item.get("visual_identity") or {}
            if (item.get("source") != "WORLD3D" or not item.get("track_id")
                    or str(item.get("track_id")) == current_id
                    or str(item.get("track_id")) in self.rejected_reacquire_track_ids
                    or "subject" not in kind or lifecycle in {
                        "TERMINATED", "LOST", "LOST_TEMPORARY", "OCCLUDED"}
                    or item.get("self_player_avatar") is True
                    or identity.get("kind") == "SELF_PLAYER"
                    or appearance.get("self_player_avatar") is True
                    or number(item.get("x")) is None or number(item.get("y")) is None):
                continue
            relations = item.get("visual_relations") or ()
            overhead_supported = any(
                str(edge.get("type") or "").upper() == "ABOVE"
                and str(edge.get("belief") or "").upper() == "SUPPORTED"
                for edge in relations)
            group = item.get("visual_group") or {}
            group_supported = str(group.get("belief") or "").upper() == "SUPPORTED"
            height = self._height(item)
            scale_similarity = (1.-min(1., abs(height-previous_height)/max(.03, previous_height))
                                if height is not None and previous_height is not None else 0.)
            real_body = kind != "unknown_subject_probe"
            score = (3. if overhead_supported else 0.) + (2. if group_supported else 0.)
            score += (1. if real_body else 0.) + scale_similarity
            score += (number(appearance.get("body_geometry")) or 0.)
            score += (number(item.get("confidence")) or 0.)*.25
            ranked.append((score, item))
        if not ranked:
            return None
        score, candidate = max(ranked, key=lambda entry: entry[0])
        # A replacement without either an overhead relation/group or strong
        # body evidence is too ambiguous to probe in a crowded NPC cluster.
        appearance = candidate.get("appearance") or {}
        relations = candidate.get("visual_relations") or ()
        supported = any(str(edge.get("belief") or "").upper() == "SUPPORTED"
                        for edge in relations)
        supported = supported or str((candidate.get("visual_group") or {}).get(
            "belief") or "").upper() == "SUPPORTED"
        return candidate if supported or (number(appearance.get("body_geometry")) or 0.) >= .82 else None
