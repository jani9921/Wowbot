"""Shadow parity of the native quest log / inventory against the addon (REV4 P3).

The addon/pixel transport stays the authority until parity is *verified*
(handoff §2, P3_RETAINED_COLLECTIONS "consumer parity").  This compares, per
medium tick and without changing any consumer, what the native packet views
and the addon snapshot say, and journals a ``NATIVE_PARITY`` event whenever
the verdict changes, so a live run's log proves (or refutes) parity.

Only quest and item IDs and counts are recorded: no names, chat or other
personal data.  A missing or partial side is ``UNKNOWN``, never agreement.

* Quest log: the native slot membership must be COMPLETE and the addon quest
  list declared COMPLETE; then the two quest-ID sets either ``AGREE`` or
  ``DIFFER`` (with the IDs only one side has).
* Inventory: native stack counts are lower bounds and may include equipped or
  other non-bag items.  For an item both sides know, a native count above the
  addon count is a contradiction (``DIFFER``); items only the native side
  knows are listed, never judged.  Otherwise ``CONSISTENT``.
"""
from __future__ import annotations

from .collection_coverage import inventory_ready
from .models import number

LIST_LIMIT = 12
RECORD_INTERVAL_SECONDS = 2.


def _quest_ids(rows) -> set[int]:
    result = set()
    for row in rows or ():
        value = number((row or {}).get("quest_id")) if isinstance(row, dict) else None
        if value is not None and value == int(value) and value > 0:
            result.add(int(value))
    return result


def quest_parity(query, state: dict, now: float) -> dict:
    try:
        native = query.quest_log_slots(now)
    except (AttributeError, KeyError, TypeError, ValueError):
        return {"verdict": "UNKNOWN", "reason": "native_view_unavailable"}
    coverage = state.get("collection_coverage")
    addon_complete = isinstance(coverage, dict) and coverage.get("active_quests") == "COMPLETE"
    if native.get("membership") != "COMPLETE":
        return {"verdict": "UNKNOWN", "reason": "native_membership_" + str(native.get("membership")).lower()}
    if not addon_complete:
        return {"verdict": "UNKNOWN", "reason": "addon_questlog_incomplete"}
    native_ids = {int(row["fields"]["quest_id"]["value"]) for row in native.get("slots") or ()
                  if isinstance(((row.get("fields") or {}).get("quest_id") or {}).get("value"), int)
                  and row["fields"]["quest_id"]["value"] > 0}
    addon_ids = _quest_ids(state.get("active_quests"))
    only_native, only_addon = sorted(native_ids - addon_ids), sorted(addon_ids - native_ids)
    return {"verdict": "AGREE" if not (only_native or only_addon) else "DIFFER",
            "quests": len(native_ids & addon_ids),
            "only_native": only_native[:LIST_LIMIT], "only_addon": only_addon[:LIST_LIMIT]}


def inventory_parity(query, state: dict, now: float) -> dict:
    try:
        native = query.native_inventory(now)
    except (AttributeError, KeyError, TypeError, ValueError):
        return {"verdict": "UNKNOWN", "reason": "native_view_unavailable"}
    rows = native.get("items") or ()
    if not rows:
        return {"verdict": "UNKNOWN", "reason": "no_native_item_counts"}
    if not inventory_ready(state):
        return {"verdict": "UNKNOWN", "reason": "addon_inventory_incomplete"}
    lower: dict[int, int] = {}
    for row in rows:
        item, count = row.get("item_id"), row.get("stack_count")
        if type(item) is int and type(count) is int and count >= 0:
            lower[item] = lower.get(item, 0) + count
    addon: dict[int, int] = {}
    for row in (state.get("inventory") or {}).get("items") or ():
        item, count = number((row or {}).get("item_id")), number((row or {}).get("count"))
        if item is not None and item == int(item):
            addon[int(item)] = addon.get(int(item), 0) + int(count if count is not None else 1)
    shared = sorted(set(lower) & set(addon))
    exceeds = [[item, lower[item], addon[item]] for item in shared if lower[item] > addon[item]]
    return {"verdict": "DIFFER" if exceeds else "CONSISTENT", "shared_items": len(shared),
            "native_exceeds_addon": exceeds[:LIST_LIMIT],
            "only_native": sorted(set(lower) - set(addon))[:LIST_LIMIT],
            "only_addon": sorted(set(addon) - set(lower))[:LIST_LIMIT]}


class NativeParityMonitor:
    """Journals the parity verdict when it changes; never feeds a consumer."""

    def __init__(self) -> None:
        self.last: dict | None = None
        self.recorded_at: float | None = None
        self.counts: dict[str, int] = {}

    def assess(self, query, state: dict, now: float) -> dict:
        return {"questlog": quest_parity(query, state, now),
                "inventory": inventory_parity(query, state, now)}

    def observe(self, query, state: dict, now: float, record) -> dict | None:
        result = self.assess(query, state, now)
        for name, part in result.items():
            key = f"{name}:{part['verdict']}"
            self.counts[key] = self.counts.get(key, 0) + 1
        if result == self.last:
            return None
        if self.recorded_at is not None and 0 <= now-self.recorded_at < RECORD_INTERVAL_SECONDS:
            return None
        self.last, self.recorded_at = result, now
        payload = {**result, "counts": dict(self.counts)}
        record(now, "NATIVE_PARITY", payload)
        return payload
