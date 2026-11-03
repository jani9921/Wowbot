"""The "I don't know, I'm telling you" endpoint (REV4 P8.4, QUEST_PLAYBOOKS).

When nothing works for an objective, the agent must say so instead of an
endless generic WAIT.  The typed dead-ends already exist as WAIT proposals
(the probe ladder's exhaustion, an unsupported item targeting, a failed
escort); this ledger names them once per objective in the journal
(``OBJECTIVE_NEEDS_USER``) and in the status, with the reason.  It never
proposes or blocks anything.
"""
from __future__ import annotations

DEAD_ENDS = {
    "objective_probes_exhausted": "Ismeretlen kredit-forrás: minden helyi próbát elvégeztem",
    "UNSUPPORTED_ITEM_MECHANIC": "A quest item célzási módjához nincs végrehajtási út",
    "escort_quest_failed": "Elbukott kísérés: újrafelvétel kell",
}
FORGET_SECONDS = 900.


def _dead_end(proposal) -> str | None:
    if proposal.skill != "WAIT":
        return None
    params = proposal.parameters
    for key in (params.get("reason"), params.get("purpose")):
        if key in DEAD_ENDS:
            return key
    return None


class NeedsUserLedger:
    def __init__(self) -> None:
        self.entries: dict[str, dict] = {}
        self.reported: set[str] = set()

    def observe(self, proposals, now: float) -> None:
        for proposal in proposals:
            reason = _dead_end(proposal)
            if reason is None:
                continue
            params = proposal.parameters
            quests = [str(q) for q in [params.get("quest_id"), *(params.get("quest_ids") or ())] if q is not None]
            objective = str(params.get("objective_id") or "")
            key = f"{','.join(sorted(set(quests)))}:{objective}:{reason}"
            entry = self.entries.setdefault(key, {"quest_ids": sorted(set(quests)), "objective_id": objective,
                                                  "reason": reason, "text": DEAD_ENDS[reason], "first_at": now})
            entry["last_at"] = now
        for key, entry in list(self.entries.items()):
            if now-entry["last_at"] > FORGET_SECONDS:
                del self.entries[key]
                self.reported.discard(key)

    def report(self, now: float, record) -> None:
        for key, entry in self.entries.items():
            if key not in self.reported:
                self.reported.add(key)
                record(now, "OBJECTIVE_NEEDS_USER", dict(entry))

    def snapshot(self) -> list[dict]:
        return [dict(entry) for entry in self.entries.values()]
