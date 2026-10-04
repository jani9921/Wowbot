"""Conservative M1 main-campaign continuation selection."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class NextQuestResolution:
    quest_id: str | None = None
    source: str = "NONE"
    reason: str = "no_campaign_candidate"
    candidate_ids: tuple[str, ...] = ()


class NextQuestResolver:
    """Resolve a next campaign quest without taking UI or input ownership.

    Campaign continuation is intentionally narrower than generic quest
    selection: a user explicitly requested MAIN_CAMPAIGN, and current addon
    telemetry exposes exactly one active quest marked as campaign.  The
    resolver does not convert gossip order, visual markers, or an arbitrary
    active side quest into a campaign fact.
    """

    def resolve(self, records: Iterable[object], *, main_campaign: bool) -> NextQuestResolution:
        if not main_campaign:
            return NextQuestResolution(reason="main_campaign_not_requested")
        candidates = tuple(sorted(
            str(record.quest_id) for record in records
            if getattr(record, "current_state", None) == "ACTIVE"
            and isinstance(getattr(record, "raw", None), dict)
            and getattr(record, "raw").get("is_campaign") is True
        ))
        if len(candidates) == 1:
            return NextQuestResolution(candidates[0], "ADDON_CAMPAIGN_FLAG",
                                       "single_active_campaign", candidates)
        if len(candidates) > 1:
            return NextQuestResolution(source="ADDON_CAMPAIGN_FLAG",
                                       reason="ambiguous_active_campaign", candidate_ids=candidates)
        return NextQuestResolution(reason="no_active_campaign", candidate_ids=candidates)
