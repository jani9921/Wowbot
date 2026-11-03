"""Live 2026-10-31 08:00 (Fargodeep Mine): a micro map belongs to its zone.

The agent waited in the mine (UI map 39) for "more data": every quest POI and
TDB location is given on the zone map Elwynn Forest (37), and each filter
demanded the player's UI map to equal it.  Normalized map coordinates keep
their strict per-UI-map checks; only world-yard data compares by zone."""
from pathlib import Path
import sqlite3
from types import SimpleNamespace

import pytest

from test_reference_support_20261008 import memory, raw_db, state  # noqa: F401  (pytest fixtures)
from wowbot.agent.tdb_locations import objective_region
from wowbot.agent.ui_zones import ZoneResolver, same_zone

UIMAPS = {39: {"ParentUiMapID": 37, "Type": 5}, 37: {"ParentUiMapID": 13, "Type": 3},
          52: {"ParentUiMapID": 13, "Type": 3}, 13: {"ParentUiMapID": 947, "Type": 2}}
CATALOG = Path(__file__).resolve().parents[1] / "data" / "client_reference.sqlite3"


class Catalog:
    def record(self, table, key):
        return UIMAPS.get(key, {}) if table == "UiMap" else {}


def test_same_zone_merges_only_sub_maps_of_one_zone():
    zones = ZoneResolver(Catalog())
    assert same_zone(39, 37, zones) and same_zone(37, 39, zones) and same_zone(37, 37, zones)
    assert not same_zone(37, 52, zones) and not same_zone(39, 52, zones) and not same_zone(39, None, zones)
    assert not same_zone(1409, 2022, ZoneResolver(Catalog()))       # unknown maps stay themselves


@pytest.mark.skipif(not CATALOG.is_file(), reason="client DB2 catalog not present")
def test_inside_the_mine_the_elwynn_poi_is_a_local_search_region(memory, raw_db):
    with sqlite3.connect(raw_db) as db:
        db.execute("UPDATE quest_poi SET UiMapID=37 WHERE QuestID=7")
    s = {**state(), "map_id": 39}
    s["reference_knowledge"] = memory.knowledge.snapshot(s, 1)
    assert s["reference_knowledge"]["quests"]["7"]["pois"]                # projected inside the mine
    region = objective_region(s, 7, SimpleNamespace(objective_id="7:0"))
    assert region is not None and region["x"] == 20 and region["y"] == 30
    other = {**state(), "map_id": 52}                                    # Westfall: another zone
    other["reference_knowledge"] = memory.knowledge.snapshot(other, 2)
    assert objective_region(other, 7, SimpleNamespace(objective_id="7:0")) is None
