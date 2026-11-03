"""Bounded, read-only receipts of actual addon QUEST_TURNED_IN events.

Quest-log disappearance, objective completion and a closed dialog are never
receipts. Sequence numbers belong to the addon transport/character session.
"""
from __future__ import annotations

import math


def turn_in_receipts(state: dict) -> list[dict]:
    rows = state.get("quest_turn_in_receipts")
    if not isinstance(rows, list):
        return []
    sampled = state.get("monotonic_time")
    if sampled is not None and (isinstance(sampled, bool) or not isinstance(sampled, (int, float))
                                or not math.isfinite(sampled)):
        return []
    result = []
    for row in rows[-8:]:
        if not isinstance(row, dict):
            continue
        qid, seq, at = row.get("quest_id"), row.get("sequence"), row.get("at")
        if (type(qid) is not int or qid <= 0 or type(seq) is not int or seq <= 0
                or isinstance(at, bool) or not isinstance(at, (int, float))
                or not math.isfinite(at) or at < 0):
            continue
        if sampled is not None and at > sampled:
            continue
        result.append({"quest_id": qid, "sequence": seq, "at": at})
    return result


def fresh_turn_in_receipt(before: dict, after: dict, quest_id) -> dict | None:
    if quest_id is None:
        return None
    # A relog/character switch cannot confirm an earlier click. The transport
    # normally always supplies session_id; unclocked offline fixtures may omit it.
    for key in ("session_id", "character_guid", "transport_session"):
        if before.get(key) != after.get(key):
            return None
    # Any receipt already present before the click is old evidence, including
    # one whose malformed/future clock becomes plausible on a later frame.
    baseline_rows = turn_in_receipts({**before, "monotonic_time": None})
    baseline = max([0, *(row["sequence"] for row in baseline_rows)])
    sequence = before.get("event_sequence")
    if type(sequence) is int and sequence >= 0:
        baseline = max(baseline, sequence)
    started, sampled = before.get("monotonic_time"), after.get("monotonic_time")
    if any(value is not None and (isinstance(value, bool) or not isinstance(value, (int, float))
                                  or not math.isfinite(value)) for value in (started, sampled)):
        return None
    for row in turn_in_receipts(after):
        if str(row["quest_id"]) != str(quest_id) or row["sequence"] <= baseline:
            continue
        if isinstance(started, (int, float)) and row["at"] < started:
            continue
        if isinstance(sampled, (int, float)) and row["at"] > sampled:
            continue
        return row
    return None
