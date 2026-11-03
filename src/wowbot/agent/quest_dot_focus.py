"""Short-lived identity for a quest objective dot, not another planner.

Minimap detections have no stable marker ID.  A disappearing dot often just
means the player arrow covers it; choosing the next nearest visible dot on
that frame sent the agent back and forth across Hrun's pit.  This helper
keeps one WorldModel-level location hypothesis until progress, a verified
context change, or a bounded local search supplies a replan gate.
"""
from __future__ import annotations

from dataclasses import dataclass
import math


@dataclass
class DotFocus:
    quest_id: str
    x: float
    y: float
    instance_id: object
    map_id: object
    progress: tuple
    selected_at: float
    last_seen: float
    search_started: float | None = None
    last_search_proposed: float | None = None


class QuestDotFocus:
    MATCH_YARDS = 14.
    BLIND_SECONDS = 20.
    LOCAL_SEARCH_SECONDS = 30.
    SEARCH_RETRY_SECONDS = 8.
    # Dot memory (user 2026-10-10): every dot seen is kept for a while, so a
    # turned camera or a dot beyond the minimap edge is not forgotten.
    REMEMBER_SECONDS = 180.
    REMEMBER_MERGE_YARDS = 8.
    ARROW_COVER_YARDS = 10.
    CONSUMED_YARDS = 12.

    def __init__(self) -> None:
        self.focus: DotFocus | None = None
        self.exhausted: list[tuple[str, float, float]] = []
        self.context: tuple | None = None
        self.progress_by_quest: dict[str, tuple | None] = {}
        self.remembered: list[list] = []         # [quest_id, x, y, last_seen]

    def _remember(self, dots, *, x: float, y: float, now: float, view: float | None) -> None:
        for dx, dy, qid in dots:
            row = next((row for row in self.remembered if row[0] == str(qid)
                        and math.hypot(row[1]-dx, row[2]-dy) <= self.REMEMBER_MERGE_YARDS), None)
            if row is None:
                self.remembered.append([str(qid), dx, dy, now])
            else:
                row[1], row[2], row[3] = .7*row[1]+.3*dx, .7*row[2]+.3*dy, now
        kept = []
        for row in self.remembered:
            if now - row[3] > self.REMEMBER_SECONDS:
                continue
            distance = math.hypot(row[1]-x, row[2]-y)
            visible = any(str(qid) == row[0] and math.hypot(dx-row[1], dy-row[2]) <= self.MATCH_YARDS
                          for dx, dy, qid in dots)
            if (not visible and view and self.ARROW_COVER_YARDS < distance < .9*view
                    and now - row[3] > 1.5):
                # Inside the minimap view, not under the player arrow, yet no
                # dot any more: the object was used or the unit is gone.
                continue
            kept.append(row)
        self.remembered = kept[-48:]

    @staticmethod
    def _progress(state: dict, quest_id: str) -> tuple | None:
        for quest in state.get("active_quests") or ():
            if not isinstance(quest, dict) or str(quest.get("quest_id")) != quest_id:
                continue
            if quest.get("is_complete") is True:
                return None
            return tuple((item.get("objective_id"), item.get("type"), item.get("description"),
                          item.get("current", item.get("current_count")),
                          item.get("required", item.get("required_count")), item.get("is_complete"))
                         for item in quest.get("objectives") or () if isinstance(item, dict))
        return None

    def _retire(self) -> None:
        focus = self.focus
        if focus is not None:
            self.exhausted.append((focus.quest_id, focus.x, focus.y))
            self.exhausted = self.exhausted[-24:]
        self.focus = None

    def select(self, state: dict, dots: list[tuple[float, float, str]], *,
               x: float, y: float, now: float, preferred_quest: str | None = None,
               view_radius: float | None = None) -> DotFocus | None:
        position = state.get("player_world_position") or {}
        context = (state.get("session_id"), state.get("map_id"), position.get("instance_id"))
        if self.context != context:
            self.focus, self.exhausted, self.context = None, [], context
            self.progress_by_quest.clear()
            self.remembered = []
        for quest in state.get("active_quests") or ():
            if not isinstance(quest, dict) or quest.get("quest_id") is None:
                continue
            qid = str(quest["quest_id"])
            progress = self._progress(state, qid)
            if qid in self.progress_by_quest and self.progress_by_quest[qid] != progress:
                self.exhausted = [row for row in self.exhausted if row[0] != qid]
                # The credited place is used up: forget its remembered dot.
                self.remembered = [row for row in self.remembered if not (
                    row[0] == qid and math.hypot(row[1]-x, row[2]-y) <= self.CONSUMED_YARDS)]
                if self.focus is not None and self.focus.quest_id == qid:
                    self.focus = None
            self.progress_by_quest[qid] = progress
        self._remember(dots, x=x, y=y, now=now, view=view_radius)
        if not dots:
            dots = [(row[1], row[2], row[0]) for row in self.remembered]
        current = self.focus
        if current is not None and (self._progress(state, current.quest_id) != current.progress
                                    or (preferred_quest is not None and current.quest_id != preferred_quest)):
            # Quest credit/objective change is an explicit new-goal gate.
            self.focus, self.exhausted = None, []
            current = None
        if current is not None:
            matches = [(math.hypot(dx-current.x, dy-current.y), dx, dy)
                       for dx, dy, qid in dots if qid == current.quest_id
                       and math.hypot(dx-current.x, dy-current.y) <= self.MATCH_YARDS]
            if matches:
                _, dx, dy = min(matches)
                # The minimap dot has several yards of quantisation jitter.
                current.x = .7*current.x + .3*dx
                current.y = .7*current.y + .3*dy
                current.last_seen = now
            distance = math.hypot(current.x-x, current.y-y)
            if current.search_started is not None:
                if now-current.search_started >= self.LOCAL_SEARCH_SECONDS:
                    self._retire()
                else:
                    return current
            elif now-current.last_seen <= self.BLIND_SECONDS or distance <= self.MATCH_YARDS:
                # An occluded dot remains the current target even if another
                # visible dot is nearer on this one frame.
                return current
            else:
                self._retire()
        available = [(math.hypot(dx-x, dy-y), dx, dy, str(qid))
                     for dx, dy, qid in dots
                     if (preferred_quest is None or str(qid) == preferred_quest)
                     and self._progress(state, str(qid)) is not None
                     and not any(str(qid) == old_id and math.hypot(dx-ox, dy-oy) <= self.MATCH_YARDS
                                 for old_id, ox, oy in self.exhausted)]
        if not available:
            return None
        _, dx, dy, qid = min(available)
        self.focus = DotFocus(qid, dx, dy, position.get("instance_id"), state.get("map_id"),
                              self._progress(state, qid), now, now)
        return self.focus

    def forget_other_floor(self, quest_id: str, x: float, y: float) -> bool:
        """The dot at (x, y) now carries a floor arrow: it is not on our floor.

        Live 2026-10-14 20:31-20:33 (Hrun's pit, 5th cocoon): the focused
        yellow dot showed a down arrow once the route had climbed the spiral
        above it; its "same floor" local search repeated and held the floor
        walk back.  Drop the focus and the remembered dot there (seen yellow
        again from its own floor, it is remembered anew).
        """
        focus = self.focus
        dropped = bool(focus is not None and focus.quest_id == str(quest_id)
                       and math.hypot(focus.x-x, focus.y-y) <= self.MATCH_YARDS)
        if dropped:
            self.focus = None
        self.remembered = [row for row in self.remembered if not (
            row[0] == str(quest_id) and math.hypot(row[1]-x, row[2]-y) <= self.MATCH_YARDS)]
        return dropped

    def live_quest_ids(self, now: float) -> set[str]:
        """Quests with a yellow objective dot still to visit: the current
        focus, or a remembered dot not searched out yet."""
        live = {self.focus.quest_id} if self.focus is not None else set()
        for qid, x, y, seen in self.remembered:
            if now - seen > self.REMEMBER_SECONDS:
                continue
            if not any(qid == old_id and math.hypot(x-ox, y-oy) <= self.MATCH_YARDS
                       for old_id, ox, oy in self.exhausted):
                live.add(qid)
        return live

    def arrived(self, now: float) -> None:
        if self.focus is not None and self.focus.search_started is None:
            self.focus.search_started = now

    def permit_local_search(self, now: float) -> bool:
        focus = self.focus
        if focus is None or focus.search_started is None:
            return False
        if (focus.last_search_proposed is not None
                and now-focus.last_search_proposed < self.SEARCH_RETRY_SECONDS):
            return False
        focus.last_search_proposed = now
        return True

    def snapshot(self) -> dict:
        focus = self.focus
        return {"quest_id": focus.quest_id, "x": focus.x, "y": focus.y,
                "selected_at": focus.selected_at, "last_seen": focus.last_seen,
                "search_started": focus.search_started,
                "last_search_proposed": focus.last_search_proposed,
                "exhausted": len(self.exhausted)} if focus is not None else {"exhausted": len(self.exhausted)}
