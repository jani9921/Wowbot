"""UI-map zones from the client DB2 UiMap parent chain (REV4, 2026-10-31).

A micro or dungeon UI map belongs to its zone: Fargodeep Mine (39, Type 5)
is part of Elwynn Forest (37).  Live 2026-10-31 08:00 the agent waited in the
mine for "more data" because every quest POI and TDB location is given on the
zone map 37 and each filter demanded the player's UI map to equal it; the
same quest started once the user walked out.  World coordinates and the
world instance are checked separately by every caller; this only says
whether two UI maps are the same zone.  Without a catalog a UI map is its own
zone, so nothing is merged by guess.
"""
from __future__ import annotations

from .models import number

ZONE_SUBMAP_TYPES = frozenset({4, 5})          # UiMap Type: dungeon, micro


class ZoneResolver:
    def __init__(self, catalog=None) -> None:
        self._catalog = catalog
        self._zones: dict[int, int | None] = {}

    def _client(self):
        if self._catalog is None:
            from wowbot.quests.client_catalog import ClientCatalog
            self._catalog = ClientCatalog()
        return self._catalog

    def zone(self, ui_map) -> int | None:
        value = number(ui_map)
        if value is None or value != int(value) or value <= 0:
            return None
        ui_map = int(value)
        if ui_map not in self._zones:
            self._zones[ui_map] = self._resolve(ui_map)
        return self._zones[ui_map]

    def _resolve(self, ui_map: int) -> int | None:
        current, seen = ui_map, set()
        try:
            while current not in seen:
                seen.add(current)
                record = self._client().record("UiMap", current) or {}
                if not record:
                    return current
                parent = record.get("ParentUiMapID")
                if record.get("Type") not in ZONE_SUBMAP_TYPES or type(parent) is not int or parent <= 0:
                    return current
                current = parent
        except Exception:                  # no catalog: the UI map is its own zone
            return ui_map
        return current


_DEFAULT = ZoneResolver()


def same_zone(left, right, zones: ZoneResolver | None = None) -> bool:
    """Equal UI maps, or two known UI maps of the same zone."""
    if left == right:
        return True
    if left is None or right is None:
        return False
    zones = zones or _DEFAULT
    zone = zones.zone(left)
    return zone is not None and zone == zones.zone(right)


def location_on_map(location: dict, ui_map, zones: ZoneResolver | None = None) -> bool:
    """World-yard points compare by zone; normalized map points need the exact UI map."""
    value = (location or {}).get("map_id")
    if (location or {}).get("coordinate_space") == "WORLD_YARDS":
        return same_zone(value, ui_map, zones)
    return value == ui_map
