"""Hostile creature spawns from TDB as route danger.

User 2026-10-20 ("csináld meg mind"), after PixelBuddy's path service, which
routes around elites, rares and dense mob clusters.  Here a spawn is a
threat when its creature's faction template attacks the player's side
(FactionTemplate.db2, TrinityCore IsHostileTo), it can be attacked by
players (no NON_ATTACKABLE / IMMUNE_TO_PC / UNINTERACTIBLE flag), it serves
no one (npcflag 0) and it is not trivial or a "minus" swarm mob.  Elites,
rares and clusters of CLUSTER_MIN normal threats within CLUSTER_YARDS are
avoided whenever a trip is not for combat; a single normal mob only when the
trip avoids combat.  Objective creatures are never threats (we go to them).

TDB spawns include phased ones the player never sees, so a single normal
spawn has low confidence, and TDB lacks many Dragon Isles spawns (2026-10-20:
none near the Waking Shores camp).  Creatures the server shows (Ymir
``packet_entities``, alive) are threats by their TDB template the same way;
a live unit replaces TDB spawns of its creature within LIVE_REPLACES_YARDS.
Data only: no input, no movement decision.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
import math
import os
from pathlib import Path
import sqlite3

ALLIANCE_RACES = frozenset({"human", "dwarf", "nightelf", "gnome", "draenei", "worgen", "voidelf",
                            "lightforgeddraenei", "darkirondwarf", "kultiran", "mechagnome"})
HORDE_RACES = frozenset({"orc", "scourge", "undead", "tauren", "troll", "bloodelf", "goblin", "nightborne",
                         "highmountaintauren", "magharorc", "zandalaritroll", "vulpera"})
ALLIANCE_TEMPLATE, HORDE_TEMPLATE = 1, 2          # Human / Orc player templates
UNIT_UNTOUCHABLE = 0x2 | 0x100 | 0x2000000        # NON_ATTACKABLE, IMMUNE_TO_PC, UNINTERACTIBLE
ELITE, RARE, TRIVIAL = frozenset({1, 2, 3}), frozenset({4}), frozenset({5, 6})
CELL_YARDS = 64.
CLUSTER_YARDS = 15.
CLUSTER_MIN = 3
LIVE_REPLACES_YARDS = 30.
SEVERE_KINDS = frozenset({"ELITE_SPAWN", "RARE_SPAWN", "HOSTILE_CLUSTER"})
# kind: (radius beyond the wander distance, cost, confidence)
DANGER = {"ELITE_SPAWN": (20., 8., .8), "RARE_SPAWN": (15., 5., .6),
          "HOSTILE_CLUSTER": (10., 6., .7), "HOSTILE_SPAWN": (10., 3., .5)}


@dataclass(frozen=True)
class SpawnThreat:
    npc_id: int
    x: float
    y: float
    z: float
    wander: float
    classification: int
    source: str = 'TDB_SPAWN'


def side_template(race) -> int | None:
    token = str(race or "").replace(" ", "").replace("_", "").casefold()
    return (ALLIANCE_TEMPLATE if token in ALLIANCE_RACES
            else HORDE_TEMPLATE if token in HORDE_RACES else None)


def _int(value) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


class SpawnThreats:
    # The learned TDB grows during a session (PacketSpawnLearner).
    LEARNED_RELOAD_SECONDS = 300.

    def __init__(self, reference_path: str | Path, factions, *, learned_path: str | Path | None = None,
                 clock=None) -> None:
        self.reference_path = Path(reference_path)
        self.factions = factions
        self.learned_path = Path(learned_path) if learned_path else None
        import time
        self._clock = clock or time.monotonic
        self._grids: dict[tuple, dict[tuple[int, int], list[SpawnThreat]]] = {}
        self._loaded_at: dict[tuple, float] = {}
        self._templates: dict[int, tuple | None] = {}

    @classmethod
    def from_environment(cls, learned_path=None) -> SpawnThreats | None:
        """The configured TDB (plus the learned one) and the client's
        FactionTemplate.db2, or None."""
        from wowbot.agent.reference_catalog import default_reference_path
        from wowbot.world_geometry.faction_templates import Db2FormatError, FactionTemplates
        configured = os.getenv("WOWBOT_WORLD_DATA_PATH", "").strip()
        root = Path(configured) if configured else Path(r"C:\Program Files (x86)\World of Warcraft\_retail_")
        if root.name.lower() in {"maps", "vmaps", "mmaps"}:
            root = root.parent
        try:
            reference = default_reference_path()
            if not reference.is_file():
                return None
            return cls(reference, FactionTemplates.load(root / "dbc" / "enUS" / "FactionTemplate.db2"),
                       learned_path=learned_path)
        except (OSError, Db2FormatError, ValueError):
            return None

    def _grid(self, map_id: int, side: int | None) -> dict[tuple[int, int], list[SpawnThreat]]:
        key = (int(map_id), side)
        stale = (self.learned_path is not None and key in self._loaded_at
                 and self._clock() - self._loaded_at[key] >= self.LEARNED_RELOAD_SECONDS)
        if key not in self._grids or stale:
            grid: dict[tuple[int, int], list[SpawnThreat]] = defaultdict(list)
            with sqlite3.connect(f"file:{self.reference_path.as_posix()}?mode=ro", uri=True) as db:
                rows = db.execute(
                    "SELECT c.id, c.position_x, c.position_y, c.position_z, c.wander_distance,"
                    " c.unit_flags, c.npcflag, ct.faction, ct.Classification, ct.unit_flags, ct.npcflag"
                    " FROM creature c JOIN creature_template ct ON ct.entry = c.id WHERE c.map = ?",
                    (int(map_id),)).fetchall()
            for (npc, x, y, z, wander, spawn_flags, spawn_npcflag, faction, rank,
                 template_flags, template_npcflag) in rows:
                rank = _int(rank)
                if (rank in TRIVIAL or (_int(spawn_flags) | _int(template_flags)) & UNIT_UNTOUCHABLE
                        or _int(spawn_npcflag) or _int(template_npcflag)
                        or not self.factions.hostile_to_player(_int(faction), side)):
                    continue
                threat = SpawnThreat(int(npc), float(x), float(y), float(z or 0.),
                                     float(wander or 0.), rank)
                grid[(math.floor(threat.x/CELL_YARDS), math.floor(threat.y/CELL_YARDS))].append(threat)
            for threat in self._learned(int(map_id), side):
                cell = (math.floor(threat.x/CELL_YARDS), math.floor(threat.y/CELL_YARDS))
                if not any(other.npc_id == threat.npc_id
                           and math.hypot(other.x-threat.x, other.y-threat.y) <= LIVE_REPLACES_YARDS
                           for near in _neighbours(cell) for other in grid.get(near, ())):
                    grid[cell].append(threat)
            self._grids[key] = dict(grid)
            self._loaded_at[key] = self._clock()
        return self._grids[key]

    def _learned(self, map_id: int, side: int | None) -> list[SpawnThreat]:
        """Learned creature rows (tdb_learned.sqlite3) that are threats by their TDB template."""
        if self.learned_path is None or not self.learned_path.is_file():
            return []
        try:
            with sqlite3.connect(f"file:{self.learned_path.as_posix()}?mode=ro", uri=True) as db:
                rows = db.execute("SELECT id, position_x, position_y, position_z FROM creature"
                                  " WHERE map = ? AND id > 0", (map_id,)).fetchall()
        except sqlite3.Error:
            return []
        return self.live_threats(rows, (0., 0.), (0., 0.), math.inf, side=side)

    def _template(self, npc_id: int) -> tuple | None:
        """(faction, Classification, unit_flags, npcflag) of one creature entry."""
        if npc_id not in self._templates:
            with sqlite3.connect(f"file:{self.reference_path.as_posix()}?mode=ro", uri=True) as db:
                row = db.execute("SELECT faction, Classification, unit_flags, npcflag"
                                 " FROM creature_template WHERE entry = ?", (int(npc_id),)).fetchone()
            self._templates[npc_id] = tuple(_int(value) for value in row) if row else None
        return self._templates[npc_id]

    def live_threats(self, units, start, end, margin: float, *, side: int | None = None,
                     exempt_npc_ids=frozenset()) -> list[SpawnThreat]:
        """Hostile live units ((npc_id, x, y, z) tuples) near the segment."""
        exempt = {int(npc) for npc in exempt_npc_ids}
        result = []
        for npc, x, y, z in units:
            template = self._template(int(npc)) if int(npc) not in exempt else None
            if (template is None or template[1] in TRIVIAL or template[2] & UNIT_UNTOUCHABLE
                    or template[3] or not self.factions.hostile_to_player(template[0], side)
                    or _segment_distance(start, end, x, y) > margin):
                continue
            result.append(SpawnThreat(int(npc), float(x), float(y), float(z), 0., template[1], 'PACKET_ENTITY'))
        return result

    def near_segment(self, map_id: int, start: tuple[float, float], end: tuple[float, float],
                     margin: float, *, side: int | None = None,
                     exempt_npc_ids=frozenset()) -> list[SpawnThreat]:
        grid = self._grid(map_id, side)
        exempt = {int(npc) for npc in exempt_npc_ids}
        x0, x1 = sorted((start[0], end[0]))
        y0, y1 = sorted((start[1], end[1]))
        cells = ((cx, cy) for cx in range(math.floor((x0-margin)/CELL_YARDS), math.floor((x1+margin)/CELL_YARDS)+1)
                 for cy in range(math.floor((y0-margin)/CELL_YARDS), math.floor((y1+margin)/CELL_YARDS)+1))
        return [threat for cell in cells for threat in grid.get(cell, ())
                if threat.npc_id not in exempt
                and _segment_distance(start, end, threat.x, threat.y) <= margin]

    def dangers(self, map_id: int, start: tuple[float, float], end: tuple[float, float], *,
                margin: float, race=None, include_single: bool = False,
                exempt_npc_ids=frozenset(), live_units=()) -> list[dict]:
        """DangerMap entries: elites, rares, clusters (and single mobs on request)."""
        side = side_template(race)
        live = self.live_threats(live_units, start, end, margin, side=side, exempt_npc_ids=exempt_npc_ids)
        threats = live + [spawn for spawn in self.near_segment(map_id, start, end, margin, side=side,
                                                               exempt_npc_ids=exempt_npc_ids)
                          if not any(unit.npc_id == spawn.npc_id
                                     and math.hypot(unit.x-spawn.x, unit.y-spawn.y) <= LIVE_REPLACES_YARDS
                                     for unit in live)]
        result: list[dict] = []
        normal = []
        for threat in threats:
            kind = ("ELITE_SPAWN" if threat.classification in ELITE
                    else "RARE_SPAWN" if threat.classification in RARE else None)
            if kind is None:
                normal.append(threat)
            else:
                result.append(_entry(kind, threat.npc_id, threat.x, threat.y, threat.wander,
                                     z=threat.z, world_map_id=map_id, source=threat.source))
        clustered: set[int] = set()
        for index, threat in enumerate(normal):
            if index in clustered:
                continue
            members = [k for k, other in enumerate(normal) if k not in clustered
                       and math.hypot(other.x-threat.x, other.y-threat.y) <= CLUSTER_YARDS
                       and abs(other.z-threat.z) <= 6.]
            if len(members) < CLUSTER_MIN:
                continue
            clustered.update(members)
            cx = sum(normal[k].x for k in members) / len(members)
            cy = sum(normal[k].y for k in members) / len(members)
            spread = max(math.hypot(normal[k].x-cx, normal[k].y-cy) + normal[k].wander for k in members)
            sources = {normal[k].source for k in members}
            result.append(_entry("HOSTILE_CLUSTER", threat.npc_id, cx, cy, spread,
                                 z=sum(normal[k].z for k in members)/len(members), world_map_id=map_id,
                                 source=next(iter(sources)) if len(sources) == 1 else 'MIXED_SOURCE'))
        if include_single:
            result.extend(_entry("HOSTILE_SPAWN", threat.npc_id, threat.x, threat.y, threat.wander,
                                 z=threat.z, world_map_id=map_id, source=threat.source)
                          for k, threat in enumerate(normal) if k not in clustered)
        return result


def _neighbours(cell: tuple[int, int]):
    return ((cell[0]+dx, cell[1]+dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1))


def _entry(kind: str, npc_id: int, x: float, y: float, extra: float, *, z=None, world_map_id=None, source='TDB_SPAWN') -> dict:
    radius, cost, confidence = DANGER[kind]
    return {"danger_id": f"tdb:{kind}:{npc_id}:{round(x)}:{round(y)}", "kind": kind,
            "x": x, "y": y, "radius": radius + extra, "cost": cost, "confidence": confidence,
            "source": source, "entity_id": f"npc:{npc_id}", 'z': z, 'world_map_id': world_map_id}


def _segment_distance(start, end, x: float, y: float) -> float:
    dx, dy = end[0]-start[0], end[1]-start[1]
    length_sq = dx*dx + dy*dy
    t = 0. if length_sq <= 1e-12 else max(0., min(1., ((x-start[0])*dx + (y-start[1])*dy) / length_sq))
    return math.hypot(x-(start[0]+t*dx), y-(start[1]+t*dy))
