"""Interaction-range evidence shared by planning and outcome bookkeeping.

Retail 12 exports no NPC world position or distance, and a far INTERACTTARGET
often fails silently.  A successful visual approach (INTERACTION_READY) to the
GUID is therefore the only positive range evidence for friendly NPCs.
"""
from __future__ import annotations

APPROACH_RANGE_EVIDENCE_SECONDS = 30.


def recently_verified_in_range(quest, guid, now: float | None) -> bool:
    """A successful visual approach to ``guid`` within the evidence window."""
    verified_at = (getattr(quest, "approach_verified_at", None) or {}).get(str(guid or ""))
    return (verified_at is not None and now is not None
            and 0 <= now-verified_at <= APPROACH_RANGE_EVIDENCE_SECONDS)
