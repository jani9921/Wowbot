"""What the agent learned about the creatures of each quest (user 2026-10-05).

Retail tells no quest-giver or quest-ender for a unit (live-verified), and
the "!" map pins of ``C_QuestLine`` carry no NPC.  What the agent *does*
observe is kept here, per user profile and across sessions:

* GIVER  -- the unit of the quest's QUEST_DETAIL dialog (addon ``giver_guid``),
  at the API "!" pin it was offered at;
* ENDER  -- the unit of the QUEST_COMPLETE dialog (addon ``ender_guid``);
* OBJECTIVE -- a creature whose tooltip named one of the quest's open
  objectives, or the unit selected when an objective counter rose;
* VEHICLE -- the unit the player boarded while the quest was open (Giant
  Boar);
* LOOK   -- up to four appearance embeddings per creature type from hovers;
* PROGRESS -- how each objective counter rose: the skill / binding / own
  spell, on foot or in a vehicle, on which creature, and where (running
  centre and radius of the spots), e.g. "8x Trample from the boar on
  Monstrous Cadavers around (x, y)";
* ABILITY -- the learned effect of a vehicle ability (forward dash, hit),
  formerly lost with every restart.

In WoW every NPC and mob is a "Creature" (GUID type), hence the name.  Only
live observations are stored: no reference database (TDB stays a last
resort).  A remembered role says whom to look for; the hover/target GUID of
the live unit stays the identity authority.  The appearance embedding does
not identify a creature reliably (Zombie Servant vs Monstrous Cadaver 0.985,
two Jaina samples 0.50), so looks only *order* mouseover probes.

Size (measured 2026-10-05): one character's playthrough (3 000 quests, 2 000
creature types with looks) ~1.9 MB; the worst case of 200 000 quests each with
giver, ender, objective creature and a progress row plus 20 000 creatures
with four looks ~90 MB.  Writes happen only when a fact is new or changed
(dialogs, a counter rise, a type's first hover per minute), never per frame.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
import sqlite3
import struct
import threading
import time

ROLES = ("GIVER", "ENDER", "OBJECTIVE", "VEHICLE")
LOOKS_PER_CREATURE = 4
SAME_LOOK = .98            # cosine above which a new sample only refreshes an old one
LOOK_REFRESH_SECONDS = 60.


def npc_id_from_guid(guid) -> int | None:
    """Creature-0-3113-2175-63341-156801-0000C115E3 -> 156801."""
    parts = str(guid or "").split("-")
    if len(parts) >= 7 and parts[0] in {"Creature", "Vehicle"}:
        try:
            return int(parts[5])
        except ValueError:
            return None
    return None


def _pack(vector) -> bytes:
    """An appearance embedding as float16 (37 values -> 74 bytes)."""
    return struct.pack(f"<{len(vector)}e", *vector)


def _unpack(blob) -> list[float]:
    if isinstance(blob, str):                      # never written so, but tolerate JSON
        return [float(value) for value in json.loads(blob)]
    return list(struct.unpack(f"<{len(blob)//2}e", blob))


def _cosine(a, b) -> float:
    if not a or not b or len(a) != len(b):
        return 0.
    return float(sum(x*y for x, y in zip(a, b)))


class QuestCreatureMemory:
    def __init__(self, path: Path | None = None) -> None:
        self.path = Path(path) if path else None
        self._lock = threading.Lock()
        self._db = sqlite3.connect(str(self.path) if self.path else ":memory:",
                                   check_same_thread=False)
        with self._db:
            self._db.executescript("""
                CREATE TABLE IF NOT EXISTS quest_creature (
                    quest_id INTEGER NOT NULL, role TEXT NOT NULL, npc_id INTEGER,
                    name TEXT NOT NULL, instance_id INTEGER, x REAL, y REAL,
                    seen_at REAL, source TEXT,
                    PRIMARY KEY (quest_id, role, name)) WITHOUT ROWID;
                CREATE TABLE IF NOT EXISTS creature_look (
                    npc_id INTEGER NOT NULL, slot INTEGER NOT NULL, name TEXT,
                    map_id INTEGER, embedding BLOB NOT NULL, seen_at REAL,
                    PRIMARY KEY (npc_id, slot)) WITHOUT ROWID;
                CREATE INDEX IF NOT EXISTS idx_creature_look_map ON creature_look(map_id);
                CREATE TABLE IF NOT EXISTS quest_progress (
                    quest_id INTEGER NOT NULL, objective INTEGER NOT NULL, method TEXT NOT NULL,
                    description TEXT, skill TEXT, binding TEXT, spell_id INTEGER,
                    in_vehicle INTEGER, target_npc_id INTEGER, target_name TEXT,
                    map_id INTEGER, instance_id INTEGER, count INTEGER NOT NULL DEFAULT 0,
                    x REAL, y REAL, radius REAL, first_seen REAL, last_seen REAL,
                    PRIMARY KEY (quest_id, objective, method)) WITHOUT ROWID;
                CREATE TABLE IF NOT EXISTS ability_effect (
                    spell_id INTEGER PRIMARY KEY, name TEXT, effect TEXT NOT NULL, updated_at REAL);
            """)
        self._roles: dict[int, dict[str, list[dict]]] = {}
        self._progress: dict[int, list[dict]] = {}
        self._looks_by_map: dict[object, dict[int, list[list[float]]]] = {}
        self._look_seen: dict[int, float] = {}

    # ----------------------------------------------------------------- learn
    def record_role(self, quest_id, role: str, *, name: str | None, npc_id=None,
                    position: dict | None = None, source: str = "", at: float | None = None) -> bool:
        """Remember a quest's GIVER/ENDER/OBJECTIVE; True when it was new or moved."""
        try:
            quest = int(quest_id)
        except (TypeError, ValueError):
            return False
        name = str(name or "").strip()
        if role not in ROLES or not name:
            return False
        npc = int(npc_id) if isinstance(npc_id, (int, float)) or str(npc_id or "").isdigit() else None
        position = position or {}
        x, y = position.get("x"), position.get("y")
        x = float(x) if isinstance(x, (int, float)) else None
        y = float(y) if isinstance(y, (int, float)) else None
        instance = position.get("instance_id")
        instance = int(instance) if isinstance(instance, (int, float)) or str(instance or "").isdigit() else None
        current = next((row for row in self.roles(quest).get(role, ()) if row["name"] == name), None)
        if current is not None and current.get("npc_id") == (npc or current.get("npc_id")) and (
                x is None or (current.get("x") is not None
                              and math.hypot(current["x"]-x, current["y"]-y) < 5.)):
            return False
        row = {"quest_id": quest, "role": role, "npc_id": npc if npc is not None else (current or {}).get("npc_id"),
               "name": name, "instance_id": instance if x is not None else (current or {}).get("instance_id"),
               "x": x if x is not None else (current or {}).get("x"),
               "y": y if y is not None else (current or {}).get("y"),
               "seen_at": at if at is not None else time.time(), "source": source}
        with self._lock, self._db:
            self._db.execute(
                "INSERT OR REPLACE INTO quest_creature(quest_id,role,npc_id,name,instance_id,x,y,seen_at,source)"
                " VALUES (:quest_id,:role,:npc_id,:name,:instance_id,:x,:y,:seen_at,:source)", row)
        self._roles.pop(quest, None)
        return True

    def record_look(self, npc_id, embedding, *, name: str | None = None, map_id=None,
                    at: float | None = None) -> bool:
        """Keep up to four appearance samples of a creature type."""
        if not isinstance(npc_id, (int, float)) or not embedding:
            return False
        npc = int(npc_id)
        at = time.monotonic() if at is None else at
        if at - self._look_seen.get(npc, -math.inf) < LOOK_REFRESH_SECONDS:
            return False
        self._look_seen[npc] = at
        vector = [float(value) for value in embedding]
        with self._lock:
            rows = self._db.execute("SELECT slot, embedding FROM creature_look WHERE npc_id=? ORDER BY slot",
                                    (npc,)).fetchall()
        samples = [(slot, _unpack(blob)) for slot, blob in rows]
        same = next((slot for slot, sample in samples if _cosine(sample, vector) >= SAME_LOOK), None)
        if same is not None:
            slot = same
        elif len(samples) < LOOKS_PER_CREATURE:
            slot = len(samples)
        else:
            with self._lock:
                slot = self._db.execute("SELECT slot FROM creature_look WHERE npc_id=? ORDER BY seen_at LIMIT 1",
                                        (npc,)).fetchone()[0]
        with self._lock, self._db:
            self._db.execute(
                "INSERT OR REPLACE INTO creature_look(npc_id,slot,name,map_id,embedding,seen_at) VALUES (?,?,?,?,?,?)",
                (npc, slot, name, map_id, _pack(vector), at))
        self._looks_by_map.clear()
        return True

    def record_progress(self, quest_id, objective: int, *, description: str = "",
                        skill: str | None = None, binding: str | None = None, spell_id=None,
                        in_vehicle: bool = False, target_npc_id=None, target_name: str | None = None,
                        map_id=None, position: dict | None = None, steps: int = 1,
                        at: float | None = None) -> dict | None:
        """One objective counter rise and what caused it; returns the merged row."""
        try:
            quest, index = int(quest_id), int(objective)
        except (TypeError, ValueError):
            return None
        spell = int(spell_id) if isinstance(spell_id, (int, float)) else None
        npc = int(target_npc_id) if isinstance(target_npc_id, (int, float)) else None
        method = "|".join((str(skill or "?"), "VEHICLE" if in_vehicle else "FOOT",
                           f"spell:{spell}" if spell is not None else str(binding or ""),
                           str(npc if npc is not None else (target_name or ""))))
        position = position or {}
        x, y = position.get("x"), position.get("y")
        x = float(x) if isinstance(x, (int, float)) else None
        y = float(y) if isinstance(y, (int, float)) else None
        at = time.time() if at is None else at
        with self._lock:
            old = self._db.execute(
                "SELECT count,x,y,radius,first_seen FROM quest_progress WHERE quest_id=? AND objective=? AND method=?",
                (quest, index, method)).fetchone()
        count, ox, oy, radius, first = old if old else (0, None, None, 0., at)
        steps = max(1, int(steps))
        if x is not None and ox is not None:
            radius = max(float(radius or 0.), math.hypot(x-ox, y-oy))
            ox, oy = (ox*count + x*steps)/(count+steps), (oy*count + y*steps)/(count+steps)
        elif x is not None:
            ox, oy = x, y
        row = {"quest_id": quest, "objective": index, "method": method, "description": description,
               "skill": skill, "binding": binding, "spell_id": spell, "in_vehicle": 1 if in_vehicle else 0,
               "target_npc_id": npc, "target_name": target_name, "map_id": map_id,
               "instance_id": position.get("instance_id"), "count": count+steps,
               "x": ox, "y": oy, "radius": round(float(radius or 0.), 1),
               "first_seen": first, "last_seen": at}
        with self._lock, self._db:
            self._db.execute(
                "INSERT OR REPLACE INTO quest_progress(quest_id,objective,method,description,skill,binding,"
                "spell_id,in_vehicle,target_npc_id,target_name,map_id,instance_id,count,x,y,radius,"
                "first_seen,last_seen) VALUES (:quest_id,:objective,:method,:description,:skill,:binding,"
                ":spell_id,:in_vehicle,:target_npc_id,:target_name,:map_id,:instance_id,:count,:x,:y,"
                ":radius,:first_seen,:last_seen)", row)
        self._progress.pop(quest, None)
        return row

    def progress(self, quest_id) -> list[dict]:
        """How this quest's objectives advanced before, most used method first."""
        try:
            quest = int(quest_id)
        except (TypeError, ValueError):
            return []
        cached = self._progress.get(quest)
        if cached is None:
            with self._lock:
                cursor = self._db.execute(
                    "SELECT * FROM quest_progress WHERE quest_id=? ORDER BY objective, count DESC", (quest,))
                names = [column[0] for column in cursor.description]
                cached = [dict(zip(names, row)) for row in cursor.fetchall()]
            if len(self._progress) > 4096:
                self._progress.clear()
            self._progress[quest] = cached
        return cached

    def save_ability_effects(self, effects: dict, names: dict | None = None,
                             at: float | None = None) -> int:
        """Persist learned vehicle ability effects that changed; returns rows written."""
        written = 0
        with self._lock:
            stored = dict(self._db.execute("SELECT spell_id, effect FROM ability_effect").fetchall())
        for key, effect in (effects or {}).items():
            if not str(key).lstrip("-").isdigit() or not isinstance(effect, dict):
                continue
            text = json.dumps(effect, sort_keys=True)
            if stored.get(int(key)) == text:
                continue
            with self._lock, self._db:
                self._db.execute("INSERT OR REPLACE INTO ability_effect(spell_id,name,effect,updated_at)"
                                 " VALUES (?,?,?,?)", (int(key), (names or {}).get(str(key)), text,
                                                      at if at is not None else time.time()))
            written += 1
        return written

    def ability_effects(self) -> dict[str, dict]:
        with self._lock:
            rows = self._db.execute("SELECT spell_id, effect FROM ability_effect").fetchall()
        return {str(spell): json.loads(text) for spell, text in rows}

    # ----------------------------------------------------------------- query
    def roles(self, quest_id) -> dict[str, list[dict]]:
        try:
            quest = int(quest_id)
        except (TypeError, ValueError):
            return {}
        cached = self._roles.get(quest)
        if cached is None:
            with self._lock:
                rows = self._db.execute(
                    "SELECT role,npc_id,name,instance_id,x,y,seen_at,source FROM quest_creature"
                    " WHERE quest_id=? ORDER BY seen_at DESC", (quest,)).fetchall()
            cached = {}
            for role, npc, name, instance, x, y, seen, source in rows:
                cached.setdefault(role, []).append({"npc_id": npc, "name": name, "instance_id": instance,
                                                    "x": x, "y": y, "seen_at": seen, "source": source})
            if len(self._roles) > 4096:
                self._roles.clear()
            self._roles[quest] = cached
        return cached

    def looks(self, map_id) -> dict[int, list[list[float]]]:
        """Appearance samples of the creature types seen on this map."""
        cached = self._looks_by_map.get(map_id)
        if cached is None:
            with self._lock:
                rows = self._db.execute("SELECT npc_id, embedding FROM creature_look WHERE map_id IS ?",
                                        (map_id,)).fetchall()
            cached = {}
            for npc, blob in rows:
                cached.setdefault(int(npc), []).append(_unpack(blob))
            self._looks_by_map[map_id] = cached
        return cached

    def snapshot(self) -> dict:
        with self._lock:
            counts = dict(self._db.execute("SELECT role, COUNT(*) FROM quest_creature GROUP BY role").fetchall())
            looks = self._db.execute("SELECT COUNT(DISTINCT npc_id) FROM creature_look").fetchone()[0]
            progress = self._db.execute("SELECT COUNT(*), COALESCE(SUM(count), 0) FROM quest_progress").fetchone()
            abilities = self._db.execute("SELECT COUNT(*) FROM ability_effect").fetchone()[0]
        return {"roles": counts, "creatures_with_looks": looks,
                "progress_methods": progress[0], "progress_steps": progress[1],
                "ability_effects": abilities}

    def close(self) -> None:
        with self._lock:
            self._db.close()


def memory_for(model) -> QuestCreatureMemory:
    memory = model.__dict__.get("quest_creature_memory")
    if memory is None:
        memory = model.__dict__["quest_creature_memory"] = QuestCreatureMemory()
    return memory


def _matches(row: dict, npc_id, name) -> bool:
    if npc_id is not None and row.get("npc_id") is not None:
        return int(row["npc_id"]) == int(npc_id)
    return bool(name) and str(row.get("name") or "").casefold() == str(name).casefold()


def remembered_creature(state: dict, guid, *, name: str | None = None, roles=None,
                        pin_givers: bool = False) -> dict | None:
    """The projected memory row this unit matches (``state["quest_creatures"]``).

    ``pin_givers``: the remembered givers of the API "!" pins next to the
    player; otherwise the creatures the current quests want (``roles``).
    """
    creatures = state.get("quest_creatures") or {}
    rows = creatures.get("pin_givers" if pin_givers else "wanted") or ()
    mouse = state.get("mouseover") or {}
    if name is None and str(mouse.get("guid") or "") == str(guid or ""):
        name = mouse.get("name")
    npc_id = npc_id_from_guid(guid)
    for row in rows:
        if roles is not None and row.get("role") not in roles:
            continue
        if _matches(row, npc_id, name):
            return row
    return None
