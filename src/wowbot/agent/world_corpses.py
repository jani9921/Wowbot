"""WorldModel corpse ownership and loot bookkeeping (own kills, area loot, engaged units).

Split out of world.py (2026-10-05, module-size gate); unchanged.
"""
from __future__ import annotations
from .models import number
from .models import json_copy as deepcopy


class WorldCorpseMixin:
    """Methods of WorldModel (world.py); moved verbatim."""

    def mark_area_looted(self, at: float | None = None, *, window: float = 30.) -> None:
        """Retire own corpses killed within ``window`` s (Retail area loot)."""
        now = self.last_received if at is None else float(at)
        for guid, killed_at in list(self.owned_corpse_guids.items()):
            if killed_at is not None and 0 <= now-float(killed_at) <= window:
                self.mark_corpse_looted(guid, now)

    def note_loot_failure(self, guid: str | None, at: float | None = None,
                          *, limit: int = 2) -> None:
        guid = str(guid or "")
        if not guid:
            return
        failures = self.__dict__.setdefault("loot_failures", {})
        failures[guid] = failures.get(guid, 0) + 1
        if failures[guid] >= limit:
            self.mark_corpse_looted(guid, at)

    def mark_corpse_looted(self, guid: str | None, at: float | None = None) -> None:
        """Retire one confirmed corpse after authoritative loot progress."""
        guid = str(guid or "")
        if not guid:
            return
        observed_at = number(at)
        self.looted_corpse_guids[guid] = (self.last_received if observed_at is None else observed_at)
        self.owned_corpse_guids.pop(guid, None)
        self.corpse_anchors.pop(guid, None)
        if "confirmed_corpse_anchors" in self.state:
            self.state["confirmed_corpse_anchors"] = [
                anchor for anchor in self.state["confirmed_corpse_anchors"]
                if anchor.get("guid") != guid]
        self.state["owned_corpse_guids"] = list(self.owned_corpse_guids)

    def corpse_was_recently_looted(self, guid: str, now: float) -> bool:
        looted_at = self.looted_corpse_guids.get(guid)
        return looted_at is not None and 0 <= now-looted_at <= 300.

    def mark_combat_kill(self, guid: str | None, at: float | None = None) -> None:
        """Record exact-GUID loot ownership after verified local combat."""
        guid = str(guid or "")
        if not guid.startswith(("Creature-", "Vehicle-")):
            return
        observed_at = number(at)
        killed_at = self.last_received if observed_at is None else observed_at
        self.owned_corpse_guids[guid] = killed_at
        anchor = self.mouseover_screen_anchors.get(guid)
        boxed = self.last_target_boxes.get(guid)
        if (boxed and isinstance(boxed.get("bbox"), dict)
                and 0 <= killed_at-float(boxed.get("observed_at") or -1e9) <= 5.):
            anchor = {**(anchor or {}), **boxed, "anchor_source": "TARGET_TRACK_AT_DEATH"}
        if anchor and number(anchor.get("x")) is not None and number(anchor.get("y")) is not None:
            self.corpse_anchors[guid] = {
                **deepcopy(anchor), "guid": guid, "dead": True,
                "source": "OWN_COMBAT_CONFIRMED", "belief": "CONFIRMED",
                "ownership_confirmed": True, "ownership_source": "COMBAT_SUCCESS",
                "observed_at": killed_at,
            }
        if "confirmed_corpse_anchors" in self.state:
            self.state["confirmed_corpse_anchors"] = [
                deepcopy(item) for item in self.corpse_anchors.values()]
        self.state["owned_corpse_guids"] = list(self.owned_corpse_guids)

    def corpse_was_engaged(self, guid: str | None, now: float) -> bool:
        engaged_at = self.__dict__.get("combat_engaged", {}).get(str(guid or ""))
        return engaged_at is not None and 0 <= now-float(engaged_at) <= self.ENGAGED_CORPSE_SECONDS

    def corpse_is_owned(self, guid: str | None, now: float) -> bool:
        killed_at = self.owned_corpse_guids.get(str(guid or ""))
        return killed_at is not None and 0 <= now-killed_at <= 180.

    def corpse_is_combat_correlated(self, guid: str | None, now: float) -> bool:
        """Accept own-kill evidence already verified or still owned by COMBAT."""
        guid = str(guid or "")
        if self.corpse_is_owned(guid, now) or self.corpse_was_engaged(guid, now):
            return True
        active = self.runtime_context.get("active_skill") or {}
        if (str(active.get("skill") or "").upper() in {"COMBAT", "DEFEND"}
                and str(active.get("target_guid") or "") == guid):
            return True
        commitment = self.runtime_context.get("commitment") or {}
        if (commitment.get("kind") == "TARGET"
                and str(commitment.get("target_guid") or "") == guid
                and str(commitment.get("initial_skill") or "").upper()
                    in {"COMBAT", "DEFEND"}):
            return True
        # A full event page can arrive immediately after FAST already cleared
        # the dead target.  Preserve exact-GUID continuity from the preceding
        # combat observation; never infer ownership from proximity/name/dead.
        for observation in reversed(self.history):
            if observation is self.latest:
                continue
            if now-observation.received_at > 5.:
                break
            prior = observation.payload
            target = prior.get("target") or {}
            if (prior.get("is_in_combat") is True
                    and str(target.get("guid") or "") == guid):
                return True
        return False
