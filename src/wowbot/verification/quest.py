"""Pure quest-credit verification, deliberately separate from skill success."""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from wowbot.runtime import VerificationResult


class QuestProgressStatus(StrEnum):
    NO_CHANGE = "NO_CHANGE"
    QUEST_STARTED = "QUEST_STARTED"
    QUEST_PROGRESSING = "QUEST_PROGRESSING"
    PROGRESSED = "PROGRESSED"
    OBJECTIVE_COMPLETE = "OBJECTIVE_COMPLETE"
    STAGE_CHANGED = "STAGE_CHANGED"
    READY_TURNIN = "READY_TURNIN"
    QUEST_COMPLETE = "QUEST_COMPLETE"


@dataclass(frozen=True, slots=True)
class QuestProgressAssessment:
    status: QuestProgressStatus
    evidence: tuple[str, ...]
    quest_ids: tuple[str, ...] = ()
    objective_ids: tuple[str, ...] = ()

    @property
    def changed(self) -> bool:
        return self.status is not QuestProgressStatus.NO_CHANGE


class QuestProgressVerifier:
    """Compare normalized quest projections without changing the quest plan."""

    def __init__(self) -> None:
        self._baseline: dict | None = None
        self._baseline_quest_ids: tuple[object, ...] = ()
        self._baseline_objective_ids: tuple[object, ...] = ()
        self.last_assessment = QuestProgressAssessment(QuestProgressStatus.NO_CHANGE, ())

    def capture_baseline(self, state: dict, *, quest_ids=(), objective_ids=()) -> dict:
        """Capture an immutable-enough verifier baseline, never live state."""
        import copy
        self._baseline = copy.deepcopy(state)
        self._baseline_quest_ids = tuple(quest_ids)
        self._baseline_objective_ids = tuple(objective_ids)
        return copy.deepcopy(self._baseline)

    def compare(self, current: dict) -> QuestProgressAssessment:
        if self._baseline is None:
            self.last_assessment = QuestProgressAssessment(QuestProgressStatus.NO_CHANGE, ())
        else:
            self.last_assessment = self.assess(
                self._baseline,
                current,
                quest_ids=self._baseline_quest_ids,
                objective_ids=self._baseline_objective_ids,
            )
        return self.last_assessment

    def evaluate(self, before: dict, after: dict, *, quest_ids=(), objective_ids=()) -> VerificationResult:
        assessment = self.assess(before, after, quest_ids=quest_ids, objective_ids=objective_ids)
        self.last_assessment = assessment
        return VerificationResult(
            assessment.changed,
            .98 if assessment.changed else .0,
            None,
            assessment.evidence,
        )

    def assess(self, before: dict, after: dict, *, quest_ids=(), objective_ids=()) -> QuestProgressAssessment:
        wanted_quests = {str(value) for value in quest_ids if value is not None}
        wanted_objectives = {str(value) for value in objective_ids if value is not None}
        old = self._index(before.get("active_quests") or ())
        new = self._index(after.get("active_quests") or ())
        evidence = []
        statuses: list[QuestProgressStatus] = []
        changed_quests: set[str] = set()
        changed_objectives: set[str] = set()
        events = after.get("events") or ()
        event_types = {
            (str(event.get("event_type") or "").upper(),
             str((event.get("payload") or {}).get("quest_id")))
            for event in events if isinstance(event, dict)
            and isinstance(event.get("payload") or {}, dict)
            and event not in (before.get("events") or ())
        }
        old_accepted = {str(value) for value in before.get("accepted_quest_ids") or ()}
        new_accepted = {str(value) for value in after.get("accepted_quest_ids") or ()}
        for quest_id in sorted(wanted_quests):
            if quest_id not in old and quest_id in new:
                evidence.append(f"quest_active:{quest_id}")
                statuses.append(QuestProgressStatus.QUEST_STARTED)
                changed_quests.add(quest_id)
            if quest_id in new and new[quest_id]["complete"] and not old.get(quest_id, {}).get("complete"):
                evidence.append(f"quest_complete:{quest_id}")
                statuses.append(QuestProgressStatus.READY_TURNIN)
                changed_quests.add(quest_id)
            if (quest_id in old and quest_id in new
                    and old[quest_id].get("stage") is not None
                    and new[quest_id].get("stage") is not None
                    and old[quest_id].get("stage") != new[quest_id].get("stage")):
                evidence.append(f"stage_changed:{quest_id}")
                statuses.append(QuestProgressStatus.STAGE_CHANGED)
                changed_quests.add(quest_id)
            if quest_id in new_accepted-old_accepted or ("QUEST_ACCEPTED", quest_id) in event_types:
                evidence.append(f"quest_accepted:{quest_id}")
                statuses.append(QuestProgressStatus.QUEST_STARTED)
                changed_quests.add(quest_id)
            if ("QUEST_TURNED_IN", quest_id) in event_types:
                evidence.append(f"quest_turned_in:{quest_id}")
                statuses.append(QuestProgressStatus.QUEST_COMPLETE)
                changed_quests.add(quest_id)
        for objective_id in sorted(wanted_objectives):
            quest_id, separator, raw_objective_id = objective_id.partition(":")
            if not separator:
                # Issue #102: a quest-local id ("o") names no quest; it is
                # resolvable only against exactly one supplied quest id.
                if len(wanted_quests) != 1:
                    continue
                quest_id, raw_objective_id = next(iter(wanted_quests)), objective_id
            if wanted_quests and quest_id not in wanted_quests:
                continue
            # Producers legitimately use either a quest-local objective id
            # (``kill``) or the canonical globally scoped id
            # (``101:kill``).  QuestModel normalizes to the latter, while some
            # Retail addon payloads retain the former.  Verification must
            # compare the same objective across both representations without
            # weakening the requirement for an authoritative state change.
            before_objectives = old.get(quest_id, {}).get("objectives", {})
            after_objectives = new.get(quest_id, {}).get("objectives", {})
            lookup_keys = tuple(dict.fromkeys((objective_id, raw_objective_id)))
            before_row = next((before_objectives[key] for key in lookup_keys
                               if key in before_objectives), None)
            after_row = next((after_objectives[key] for key in lookup_keys
                              if key in after_objectives), None)
            if after_row and before_row and after_row != before_row:
                completed = bool(after_row[2]) or (
                    isinstance(after_row[0], (int, float))
                    and isinstance(after_row[1], (int, float))
                    and after_row[1] > 0 and after_row[0] >= after_row[1]
                )
                count_increased = (
                    before_row is not None
                    and isinstance(before_row[0], (int, float))
                    and isinstance(after_row[0], (int, float))
                    and after_row[0] > before_row[0]
                    and before_row[1] == after_row[1]
                )
                completion_changed = after_row[2] is True and before_row[2] is False
                if not count_increased and not completion_changed:
                    continue
                evidence.append(f"objective_changed:{objective_id}")
                statuses.append(
                    QuestProgressStatus.OBJECTIVE_COMPLETE if completed else
                    QuestProgressStatus.QUEST_PROGRESSING if count_increased else
                    QuestProgressStatus.PROGRESSED
                )
                changed_quests.add(quest_id)
                changed_objectives.add(objective_id)

        precedence = (
            QuestProgressStatus.QUEST_COMPLETE,
            QuestProgressStatus.READY_TURNIN,
            QuestProgressStatus.STAGE_CHANGED,
            QuestProgressStatus.OBJECTIVE_COMPLETE,
            QuestProgressStatus.QUEST_STARTED,
            QuestProgressStatus.QUEST_PROGRESSING,
            QuestProgressStatus.PROGRESSED,
        )
        status = next((candidate for candidate in precedence if candidate in statuses),
                      QuestProgressStatus.NO_CHANGE)
        return QuestProgressAssessment(
            status,
            tuple(evidence),
            tuple(sorted(changed_quests)),
            tuple(sorted(changed_objectives)),
        )

    def credit_increased(self) -> bool:
        return self.last_assessment.changed

    def quest_started(self) -> bool:
        return self.last_assessment.status is QuestProgressStatus.QUEST_STARTED

    def quest_progressing(self) -> bool:
        return self.last_assessment.status is QuestProgressStatus.QUEST_PROGRESSING

    def objective_completed(self) -> bool:
        return self.last_assessment.status is QuestProgressStatus.OBJECTIVE_COMPLETE

    def stage_changed(self) -> bool:
        return self.last_assessment.status is QuestProgressStatus.STAGE_CHANGED

    def ready_for_turnin(self) -> bool:
        return self.last_assessment.status is QuestProgressStatus.READY_TURNIN

    def quest_completed(self) -> bool:
        return self.last_assessment.status is QuestProgressStatus.QUEST_COMPLETE

    @staticmethod
    def _index(quests) -> dict[str, dict]:
        result = {}
        for quest in quests:
            if not isinstance(quest, dict) or quest.get("quest_id") is None:
                continue
            quest_id = str(quest["quest_id"])
            objectives = {}
            for index, objective in enumerate(quest.get("objectives") or ()):
                if not isinstance(objective, dict):
                    continue
                oid = str(objective.get("objective_id") or index)
                objectives[oid] = (objective.get("current", objective.get("current_count")),
                                   objective.get("required", objective.get("required_count")),
                                   bool(objective.get("is_complete")))
            result[quest_id] = {
                "complete": bool(quest.get("is_complete")),
                "stage": quest.get("stage", quest.get("stage_index")),
                "objectives": objectives,
            }
        return result
