"""VisualApproachController box geometry: heights, screen-edge exits, beside-self arrival, servo measurements.

Split out of visual_approach.py (2026-10-05); unchanged.
"""
from __future__ import annotations
from .models import number
from .visual_approach_types import VisualServoMeasurement


class VisualApproachGeometryMixin:
    """Methods of VisualApproachController (visual_approach.py); moved verbatim."""

    @staticmethod
    def _height(track: dict) -> float | None:
        value = number(track.get("servo_scale_fraction"))
        if value is not None:
            return value
        value = number(track.get("bbox_height_fraction"))
        if value is not None:
            return value
        history = track.get("bbox_history") or []
        bbox = track.get("bbox") or (history[-1] if history else {})
        top, bottom = number(bbox.get("top")), number(bbox.get("bottom"))
        frame_height = number(track.get("frame_height"))
        return (bottom-top)/frame_height if None not in (top, bottom, frame_height) and frame_height else None

    @staticmethod
    def _edges(track: dict) -> tuple[float, float, float, float] | None:
        """Normalised (left, top, right, bottom) of a track box, top-left origin."""
        bbox = track.get("bbox") or {}
        left, top = number(bbox.get("left")), number(bbox.get("top"))
        right, bottom = number(bbox.get("right")), number(bbox.get("bottom"))
        frame_h = number(track.get("frame_height"))
        frame_w = number(track.get("frame_width"))
        fraction_h = number(track.get("bbox_height_fraction"))
        fraction_w = number(track.get("bbox_width_fraction"))
        if None in (left, top, right, bottom) or bottom <= top or right <= left:
            return None
        if not frame_h and fraction_h:
            frame_h = (bottom-top)/fraction_h
        if not frame_w and fraction_w:
            frame_w = (right-left)/fraction_w
        if not frame_h or not frame_w:
            return None
        return left/frame_w, top/frame_h, right/frame_w, bottom/frame_h

    @classmethod
    def _self_edges(cls, state: dict) -> tuple[float, float, float, float] | None:
        """Edges of the own avatar's box (self identity or screen-anchored)."""
        for item in state.get("visual_candidates", []):
            appearance = item.get("appearance") if isinstance(item.get("appearance"), dict) else {}
            identity = item.get("visual_identity") if isinstance(item.get("visual_identity"), dict) else {}
            if (item.get("self_player_avatar") is True or identity.get("kind") == "SELF_PLAYER"
                    or appearance.get("self_player_avatar") is True
                    or appearance.get("screen_anchored") is True):
                edges = cls._edges(item)
                if edges is not None:
                    return edges
        return None

    @staticmethod
    def _beside_self(target: tuple[float, float, float, float],
                     own: tuple[float, float, float, float], *, lying: bool = False) -> bool:
        """User 2026-10-01: arrived when the unit's box stands next to / overlaps
        the own avatar's box by roughly a quarter to a third.  Similar height
        and feet at a similar screen level keep a distant unit standing
        *behind* the avatar from counting."""
        tl, tt, tr, tb = target
        sl, st, sr, sb = own
        t_h, s_h = tb-tt, sb-st
        if t_h <= 0 or s_h <= 0 or abs(tb-sb) > (.10 if lying else .12):
            return False
        if not lying and not .6 <= t_h/s_h <= 1.8:
            return False
        overlap_w = max(0., min(tr, sr)-max(tl, sl))
        gap = max(0., max(tl, sl)-min(tr, sr))
        narrower = max(1e-6, min(tr-tl, sr-sl))
        return overlap_w/narrower >= .25 or gap <= .5*(sr-sl)

    def _edge_recovery_pending(self, now: float) -> bool:
        if self._exit_edge(now) is None:
            return False
        started = self.edge_recovery_started_at
        return started is None or now-started <= 1.5

    def _exit_edge(self, now: float) -> str | None:
        """Screen edge the committed box was last seen touching (≤1.2 s ago)."""
        if self.last_edges is None or self.last_edges_at is None or now-self.last_edges_at > 2.0:
            return None
        left, top, right, bottom = self.last_edges
        if bottom >= .90:
            return "BOTTOM"
        own = self.last_self_edges
        if own is not None:
            sl, st, sr, sb = own
            overlap = max(0., min(right, sr)-max(left, sl))
            near_feet = bottom >= sb-.20*(sb-st)
            if overlap > 0. and near_feet and (bottom-top) >= .5*(sb-st):
                return "BOTTOM"   # ran into/past it: it vanished at the avatar
        if left <= .04:
            return "LEFT"
        if right >= .96:
            return "RIGHT"
        if top <= .04:
            return "TOP"
        return None

    @staticmethod
    def _obstacle_evidence(state: dict) -> float:
        """Return visual support only; this is never a proven blocked path."""
        values = []
        for item in state.get("visual_candidates", []):
            if (item.get("source") == "WORLD3D"
                    and (item.get("detector_kind") or item.get("kind")) == "obstacle_candidate"
                    and (number(item.get("stable_frames")) or 0) >= 3):
                x = number(item.get("x"))
                if x is not None and .32 <= x <= .68:
                    values.append(number(item.get("confidence")) or 0.)
        return max(values, default=0.)

    def _measurement(self, state: dict, observation_id: str, now: float,
                     track: dict, *, predicted: bool) -> VisualServoMeasurement:
        if not predicted:
            edges = self._edges(track)
            if edges is not None:
                self.last_edges, self.last_edges_at = edges, now
                self.edge_recovery_started_at = None
                own = self._self_edges(state)
                if own is not None:
                    self.last_self_edges = own
        x, y = number(track.get("x")), number(track.get("y"))
        height = self._height(track)
        previous_height = next((item.bbox_height for item in reversed(self.samples)
                                if not item.predicted and item.bbox_height is not None), None)
        scale_delta = height-previous_height if height is not None and previous_height is not None else None
        appearance = track.get("appearance") or {}
        player = state.get("player_world_position") or {}
        movement = state.get("movement") or {}
        moving = movement.get("moving", state.get("is_moving"))
        return VisualServoMeasurement(
            observation_id=observation_id, at=now,
            track_id=str(track.get("track_id")) if track.get("track_id") is not None else None,
            x=x, y=y, bbox_height=height, bbox_scale_delta=scale_delta,
            center_error=x-.5 if x is not None else None,
            confidence=number(track.get("confidence")) or .5,
            source=str(track.get("source") or "UNKNOWN"),
            lifecycle=str(track.get("lifecycle") or track.get("track_state") or "ACTIVE").upper(),
            predicted=predicted,
            camera_motion_x=number(appearance.get("camera_motion_dx")),
            camera_motion_y=number(appearance.get("camera_motion_dy")),
            player_x=number(player.get("x")), player_y=number(player.get("y")),
            player_heading=number(state.get("orientation")),
            player_speed=number(movement.get("speed", state.get("movement_speed"))),
            player_moving=moving if isinstance(moving, bool) else None,
            telemetry_sample_time=number(state.get("monotonic_time")),
            obstacle_evidence=self._obstacle_evidence(state),
            visual_sample_time=(number(track.get("observed_at", track.get("last_seen")))
                                or number(track.get("sample_time")) or now))
