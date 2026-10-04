"""Pure M2.9 invalid-target recovery evidence policy."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from wowbot.agent.models import number
from wowbot.runtime import world_entity_id


@dataclass(frozen=True, slots=True)
class TargetRecoveryDecision:
    kind: str
    intended_guid: str | None
    anchor: dict[str, Any] | None = None
    alternate_guid: str | None = None
    evidence: tuple[str, ...] = ()


class InvalidTargetRecoveryPolicy:
    """Reacquire exact identity or return an advisory local alternative.

    It emits no input and never changes the committed target.  An alternate
    is therefore only a planner hint after the current COMBAT attempt fails.
    """

    MAX_ANCHOR_AGE = 1.5

    def assess(self, state: dict[str, Any], intended_guid: str | None, *,
               quest_ids: Iterable[Any] = ()) -> TargetRecoveryDecision:
        expected = world_entity_id(intended_guid)
        if expected is None:
            return TargetRecoveryDecision("UNAVAILABLE", None,
                                          evidence=("missing_intended_guid",))
        candidates = tuple(self._candidates(state))
        exact = next((row for row in candidates
                      if world_entity_id(row.get("guid")) == expected
                      and self._eligible(row, quest_ids, exact=True)), None)
        anchor = self._fresh_anchor(state, str(expected), exact)
        if exact is not None and anchor is not None:
            return TargetRecoveryDecision(
                "REACQUIRE_INTENDED", str(expected), anchor=anchor,
                evidence=("exact_guid_alive", "hostile_targetable",
                          "fresh_confirmed_screen_anchor"))

        alternatives = [row for row in candidates
                        if world_entity_id(row.get("guid")) not in {None, expected}
                        and self._eligible(row, quest_ids, exact=False)]
        alternatives.sort(key=self._alternate_score, reverse=True)
        if alternatives:
            guid = world_entity_id(alternatives[0].get("guid"))
            return TargetRecoveryDecision(
                "SEARCH_LOCAL_CANDIDATE", str(expected),
                alternate_guid=str(guid) if guid else None,
                evidence=("intended_target_unavailable",
                          "quest_relevant_local_candidate"))
        return TargetRecoveryDecision(
            "UNAVAILABLE", str(expected),
            evidence=("intended_target_unavailable", "no_safe_local_candidate"))

    def _fresh_anchor(self, state: Mapping[str, Any], guid: str,
                      candidate: Mapping[str, Any] | None) -> dict[str, Any] | None:
        anchors = state.get("confirmed_mouseover_anchors") or {}
        anchor = ((candidate or {}).get("screen_position")
                  or (anchors.get(guid) if isinstance(anchors, Mapping) else None))
        if not isinstance(anchor, Mapping):
            return None
        x, y = number(anchor.get("x")), number(anchor.get("y"))
        sampled, now = number(anchor.get("sample_time")), number(state.get("monotonic_time"))
        if (x is None or y is None or not 0.02 < x < .98 or not 0.02 < y < .98
                or sampled is None or now is None or not 0. <= now-sampled <= self.MAX_ANCHOR_AGE):
            return None
        return {**dict(anchor), "x": x, "y": y}

    @staticmethod
    def _eligible(row: Mapping[str, Any], quest_ids: Iterable[Any], *, exact: bool) -> bool:
        if row.get("dead", row.get("is_dead")) is True:
            return False
        if row.get("attackable", row.get("is_attackable")) is not True:
            return False
        if row.get("targetable", row.get("can_target", True)) is False:
            return False
        lifecycle = str(row.get("lifecycle") or row.get("track_state") or "").upper()
        if lifecycle in {"LOST", "TERMINATED", "REJECTED"}:
            return False
        wanted = {str(value) for value in quest_ids if value is not None}
        observed = {str(value) for value in row.get("quest_ids") or ()}
        if not exact and wanted and not (row.get("quest_relevant") is True or wanted & observed):
            return False
        if exact and row.get("quest_relevant") is False:
            return False
        return True

    @staticmethod
    def _alternate_score(row: Mapping[str, Any]) -> tuple[float, float, float]:
        anchor = row.get("screen_position") or {}
        x = number(anchor.get("x"))
        center = 1. - abs((x if x is not None else .5)-.5)*2.
        return (1. if row.get("quest_relevant") is True else 0.,
                number(row.get("threat")) or 0., center)

    @staticmethod
    def _candidates(state: Mapping[str, Any]):
        seen: set[str] = set()
        sources = [state.get("target"), state.get("mouseover")]
        entities = state.get("entities") or ()
        sources.extend(entities.values() if isinstance(entities, Mapping) else entities)
        sources.extend(state.get("nearby_attackable_entities") or ())
        for row in sources:
            if not isinstance(row, Mapping):
                continue
            guid = world_entity_id(row.get("guid"))
            if guid is None or str(guid) in seen:
                continue
            seen.add(str(guid))
            yield row
