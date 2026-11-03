"""Pointer lock on a found quest object (user 2026-10-14).

User: "when it finds the cocoon it locks the mouse on it, literally tracks it
and does not let it go -- except in combat, where the attacker comes first."
Live 2026-10-14 (Hrun's pit): SEEK found the Thick Cocoon, the character
kept turning and carried the cursor off it before the addon tooltip
(~0.2-0.5 s through the pixel strip) arrived, and then turned again.

The lock issues no input itself: it says where the pointer belongs.  The
engine sends a POINTER (no button; it keeps the forward lease) while a MOVE
or a wait runs; SEEK and OBJECT_USE aim at the same box; other hovers and
camera searches are held back while it lasts.

Turn compensation: a World3D box is ~0.1 s old.  If the character turned
by d(psi) since the box was observed, the object moved on screen by
d(psi) / HFOV (facing grows counter-clockwise: a left turn moves the world
to the right).  The HFOV is WoW's default camera field of view; the pointer
is re-aimed from fresh boxes several times a second, so an approximate
value only has to be close.
"""
from __future__ import annotations

from collections import deque
import math

from .models import Command, number
from .object_interaction_flow import open_object_objective, quest_object_candidates
from .pointer_tracking import live_pointer_point, world_pointer_blocked


class QuestObjectLock:
    HFOV_RADIANS = math.radians(90.)
    LOST_SECONDS = 2.
    POINTER_INTERVAL_SECONDS = 1/30
    POINTER_MOVE_EPSILON = .003
    FACING_HISTORY_SECONDS = 2.
    SPENT_TRACK_SECONDS = 30.
    EDGE_MARGIN = .03
    # Pending skills during which the lock drives the pointer.  SEEK and
    # OBJECT_USE aim at the box themselves; every other skill owns the mouse.
    POINTER_SKILLS = frozenset({"MOVE", "FOLLOW", "REACH_OBJECT", "REACH_LOCATION",
                                "WAIT", "WAIT_EVENT"})

    def __init__(self) -> None:
        self.track_id: str | None = None
        self.signature_id: str | None = None
        self.quest_id = None
        self.box: dict | None = None
        self.acquired_at: float | None = None
        self.last_seen: float | None = None
        self.release_reason: str | None = None
        self._facing: deque[tuple[float, float]] = deque()
        self._last_pointer_at = -1e9
        self._last_point: tuple[float, float] | None = None
        self._spent: dict[str, float] = {}

    @property
    def active(self) -> bool:
        return self.track_id is not None

    # --- state ---------------------------------------------------------------------

    def observe_facing(self, now: float, facing: float | None) -> None:
        if facing is None:
            return
        self._facing.append((now, facing))
        while self._facing and now-self._facing[0][0] > self.FACING_HISTORY_SECONDS:
            self._facing.popleft()

    def _facing_at(self, at: float | None) -> float | None:
        if at is None or not self._facing:
            return None
        return min(self._facing, key=lambda row: abs(row[0]-at))[1]

    def _find(self, boxes: list[dict]) -> dict | None:
        exact = next((box for box in boxes if box.get("track_id") == self.track_id), None)
        if exact is not None or not self.signature_id:
            return exact
        return next((box for box in boxes
                     if (box.get("visual_signature") or {}).get("signature_id") == self.signature_id), None)

    @staticmethod
    def _object_quest(state: dict):
        for quest in state.get("active_quests") or ():
            if isinstance(quest, dict) and open_object_objective(state, quest.get("quest_id")):
                return quest.get("quest_id")
        return None

    def update(self, state: dict, now: float, *, object_at_hand=None) -> None:
        """Refresh the locked box, or release / acquire one from this state.

        ``object_at_hand(quest_id)`` (optional): False when the quest's
        known spawns say no usable object is near on this floor -- a cocoon
        seen on another floor is not locked.
        """
        self.observe_facing(now, number(state.get("orientation")))
        if state.get("is_in_combat") or state.get("is_dead") or state.get("is_ghost"):
            if self.active:
                self.release("combat", now)        # the attacker comes first
            return
        boxes = quest_object_candidates(state)
        if self.active:
            box = self._find(boxes)
            if box is not None:
                self.box, self.last_seen = box, now
            elif now-(self.last_seen or now) > self.LOST_SECONDS:
                self.release("lost", now)
            return
        quest_id = self._object_quest(state)
        if quest_id is None or not boxes:
            return
        if object_at_hand is not None and object_at_hand(quest_id) is False:
            return
        for track, at in list(self._spent.items()):
            if now-at > self.SPENT_TRACK_SECONDS:
                self._spent.pop(track, None)
        box = next((box for box in boxes if str(box.get("track_id")) not in self._spent), None)
        if box is None:
            return
        self.track_id = box.get("track_id")
        self.signature_id = (box.get("visual_signature") or {}).get("signature_id")
        self.quest_id, self.box = quest_id, box
        self.acquired_at = self.last_seen = now
        self.release_reason = None
        self._last_point = None

    def release(self, reason: str, now: float, *, spent: bool = False) -> None:
        if spent and self.track_id is not None:
            self._spent[str(self.track_id)] = now
        self.track_id = self.signature_id = self.quest_id = None
        self.box = self.acquired_at = self.last_seen = None
        self.release_reason = reason
        self._last_point = None

    # --- pointer -------------------------------------------------------------------

    def target_point(self, now: float, facing: float | None) -> tuple[float, float] | None:
        """The box's screen point now, corrected for the turn since it was seen."""
        box = self.box or {}
        x, y = number(box.get("x")), number(box.get("y"))
        if x is None or y is None:
            return None
        observed = number(box.get("observed_at", box.get("last_seen")))
        then = self._facing_at(observed)
        if facing is not None and then is not None:
            turn = (facing-then+math.pi) % math.tau - math.pi
            x += turn / self.HFOV_RADIANS
        if not 0. <= x <= 1.:
            return None                         # turned out of view: no edge clicks
        margin = self.EDGE_MARGIN
        return (min(1.-margin, max(margin, x)), min(1.-margin, max(margin, y)))

    def pointer_command(self, state: dict, now: float, pending_skill: str | None) -> Command | None:
        if (not self.active or (pending_skill is not None and pending_skill not in self.POINTER_SKILLS)
                or now-self._last_pointer_at < self.POINTER_INTERVAL_SECONDS
                or state.get("is_in_combat") or world_pointer_blocked(state)
                or live_pointer_point(state, self.track_id, now, candidate=self.box) is None):
            return None
        facing = number(state.get("orientation"))
        self.observe_facing(now, facing)
        point = self.target_point(now, facing)
        if point is None:
            return None
        cursor = state.get("cursor_position") or {}
        cx, cy = number(cursor.get("nx")), number(cursor.get("ny"))
        last = self._last_point
        if ((cx is not None and cy is not None
             and abs(cx-point[0])+abs(cy-point[1]) <= self.POINTER_MOVE_EPSILON)
                or (last is not None and abs(last[0]-point[0])+abs(last[1]-point[1])
                    <= self.POINTER_MOVE_EPSILON and now-self._last_pointer_at < 1.)):
            return None
        self._last_pointer_at, self._last_point = now, point
        return Command("POINTER", x=point[0], y=point[1], duration=.01)

    # --- planning ------------------------------------------------------------------

    def holds_mouse(self, proposal) -> bool:
        """Would this proposal take the mouse off the locked object?"""
        if not self.active:
            return False
        params = proposal.parameters
        if proposal.skill == "OPEN_MAP":
            return True
        if proposal.skill == "INSPECT":
            return params.get("track_id") != self.track_id
        if proposal.skill == "SEEK_VISUAL_CUE":
            return params.get("track_id") != self.track_id
        return False

    def snapshot(self) -> dict:
        return {"active": self.active, "track_id": self.track_id, "quest_id": self.quest_id,
                "acquired_at": self.acquired_at, "last_seen": self.last_seen,
                "release_reason": self.release_reason, "last_point": self._last_point}
