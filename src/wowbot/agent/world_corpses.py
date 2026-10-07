"""WorldModel corpse ownership and loot bookkeeping (own kills, area loot, engaged units).

Split out of world.py (2026-10-05, module-size gate); unchanged.
"""
from __future__ import annotations
from .models import number
from .models import json_copy as deepcopy


def _world_point(value) -> tuple | None:
    if not isinstance(value, dict):
        return None
    x, y = number(value.get("x")), number(value.get("y"))
    instance = value.get("instance_id")
    if x is None or y is None or instance is None:
        return None
    return float(x), float(y), number(value.get("z")), str(instance)


class WorldCorpseMixin:
    """Methods of WorldModel (world.py); moved verbatim."""

    # Retail area loot covers corpses around the opened one, not every recent
    # kill.  Conservative bounds; one storey of Z separates cave floors.
    AREA_LOOT_RADIUS_YARDS = 20.
    AREA_LOOT_MAX_DZ_YARDS = 6.

    def _kill_position(self, guid: str) -> tuple | None:
        """Best world-space estimate of where an own kill happened."""
        target = self.state.get("target") or {}
        if str(target.get("guid") or "") == guid:
            point = _world_point(target.get("world_position"))
            if point is not None:
                return point
        return _world_point(self.state.get("player_world_position"))

    def _same_loot_area(self, origin: tuple | None, other: tuple | None) -> bool:
        if origin is None or other is None or origin[3] != other[3]:
            return False
        if ((origin[0]-other[0])**2 + (origin[1]-other[1])**2) ** .5 > self.AREA_LOOT_RADIUS_YARDS:
            return False
        return (origin[2] is None or other[2] is None
                or abs(origin[2]-other[2]) <= self.AREA_LOOT_MAX_DZ_YARDS)

    def mark_area_looted(self, at: float | None = None, *, window: float = 30.,
                         origin_guid: str | None = None) -> None:
        """Retire own corpses that Retail area loot covered with the opened one.

        Issue #91: retiring every kill of the last ``window`` s dropped far
        away (or other-floor) corpses that were never looted.  Only kills
        near the opened corpse, on its floor and instance, are retired; a
        corpse with unknown position stays pending (its own bounded loot
        failures retire it).
        """
        now = self.last_received if at is None else float(at)
        positions = self.__dict__.get("kill_positions", {})
        origin = positions.get(str(origin_guid or "")) or _world_point(
            self.state.get("player_world_position"))
        for guid, killed_at in list(self.owned_corpse_guids.items()):
            if (killed_at is not None and 0 <= now-float(killed_at) <= window
                    and self._same_loot_area(origin, positions.get(guid))):
                self.mark_corpse_looted(guid, now)

    # A unit's lootable flag can lag its death by a moment; only a "nothing
    # to loot" that holds this long after the death was first seen counts.
    EMPTY_CORPSE_AFTER_DEATH_SECONDS = 1.

    def note_corpse_lootability(self, now: float | None) -> None:
        """Remember corpses the addon (CanLootUnit) reports empty.

        Live 2026-10-07 12:06: killed Barrow Spiderlings (no loot) were
        ``lootable=false`` while selected, but LOOT ran after the target was
        cleared, so the empty report was gone and every spiderling cost two
        ``corpse_not_found`` attempts (back and forth after each fight).
        """
        if now is None:
            return
        seen = self.__dict__.setdefault("dead_seen_at", {})
        empty = self.__dict__.setdefault("empty_corpse_guids", {})
        source = self.__dict__.get("addon_state") or self.state       # newest FAST units
        for unit in (source.get("target"), source.get("mouseover")):
            if not isinstance(unit, dict) or unit.get("dead", unit.get("is_dead")) is not True:
                continue
            guid = str(unit.get("guid") or "")
            if not guid.startswith(("Creature-", "Vehicle-")):
                continue
            first = seen.setdefault(guid, float(now))
            if unit.get("lootable") is False and now-first >= self.EMPTY_CORPSE_AFTER_DEATH_SECONDS:
                empty[guid] = float(now)
                if guid in self.owned_corpse_guids or guid in self.corpse_anchors:
                    self.mark_corpse_looted(guid, now)
            elif unit.get("lootable") is True:
                empty.pop(guid, None)
        if len(seen) > 512:
            for guid in sorted(seen, key=seen.get)[:256]:
                seen.pop(guid, None)

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
        position = self._kill_position(guid)
        if position is not None:
            self.__dict__.setdefault("kill_positions", {})[guid] = position
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
        if guid in (self.__dict__.get("empty_corpse_guids") or {}):
            self.mark_corpse_looted(guid, killed_at)      # already reported empty

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
