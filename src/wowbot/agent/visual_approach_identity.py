"""VisualApproachController identity checks: addon mouseover confirmation and re-hover candidates.

Split out of visual_approach.py (2026-10-05); unchanged.
"""
from __future__ import annotations
import math
from .models import number


class VisualApproachIdentityMixin:
    """Methods of VisualApproachController (visual_approach.py); moved verbatim."""

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
        if not expected or str(mouse.get("guid") or "") != expected:
            return False
        if mouse_time is None or not 0 <= now-mouse_time <= .75:
            return False
        if cursor_time is not None and not 0 <= now-cursor_time <= .75:
            return False
        return after is None or mouse_time > after + .000001

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
        if (mouse_time is None or mouse_time <= self.last_pointer_hover_at + .03
                or not 0 <= now-mouse_time <= .75):
            return None
        cursor = state.get("cursor_position") or {}
        cx, cy = number(cursor.get("nx")), number(cursor.get("ny"))
        sample = self.samples[-1] if self.samples else None
        if (sample is None or None in (cx, cy, sample.x, sample.y)
                or math.hypot(cx-sample.x, cy-sample.y) > 2*self.POINTER_TOLERANCE):
            return None
        guid = str(mouse.get("guid") or "")
        if not guid:
            return None
        if guid == expected:
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
                and mouse.get("guid") and str(mouse.get("guid")) != expected):
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
