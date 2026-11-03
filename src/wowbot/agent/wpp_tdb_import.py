"""Update the TrinityCore TDB itself from Ymir dumps through WowPacketParser.

User 2026-10-25: "the original TDB, not the learned one -- everything should
be updated in it", from the Ymir ``.pkt`` dumps, started by a GUI button,
with a report of how far it is.  TrinityCore's own WowPacketParser (built
from source in ``native/WowPacketParser``) turns each dump into TDB SQL
(templates, spawns, addons, texts, quest POIs, gossip, vendors ...).  That
SQL is written for a server's DELETE+INSERT import; here every row is merged
instead, so the TDB keeps what a sniff cannot know (ScriptName, AIName ...):

* an existing row (same primary key): only the columns the sniff gives
  and that differ are updated (``VerifiedBuild`` follows);
* a missing row: inserted;
* a sniffed spawn (``@CGUID+n`` / ``@OGUID+n``): inserted only where the TDB
  has no spawn of that entry on that map within ``SPAWN_RADIUS`` (a roaming
  unit's create point is anywhere on its path), under a reserved GUID range;
  its addon / spawn-tracking rows follow the new GUID;
* a value WPP does not know (``UNKNOWN``) is no value; rows with other
  unresolved variables (``@GROUP_ID``, custom area triggers) are skipped.

Every change is logged (``aipc_wpp_changes``: old and new values), every
dump is imported once (``aipc_wpp_dumps``), and a copy of the untouched TDB
is kept beside it before the first write.
"""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import time

ROOT = Path(__file__).resolve().parents[3]
WPP_EXE = ROOT / "native" / "WowPacketParser" / "WowPacketParser" / "bin" / "Release" / "WowPacketParser.exe"
# Midnight target, SQL only, the world tables on; copied beside the exe before
# a run so a rebuilt WowPacketParser keeps the project's settings.
WPP_CONFIG = ROOT / "config" / "wpp" / "WowPacketParser.dll.config"
SPAWN_RADIUS = {"creature": 20., "gameobject": 2.}
SPAWN_VARS = {"CGUID": "creature", "OGUID": "gameobject"}
GUID_BASE = 9_000_000_000_000
# Columns WPP reads wrongly for these builds, never merged.  2026-10-25: all
# 98 quest_objectives updates of the 70448/70575 dumps set ConditionalAmount
# to text bytes (0x20202020 "    ", 0x30303030 "0000", 1131570547 "sedC").
UNRELIABLE_COLUMNS = {"quest_objectives": frozenset({"ConditionalAmount"})}
SETTLED_SECONDS = 30.
WPP_TIMEOUT_SECONDS = 900.


class Var:
    """``@NAME+offset`` in WPP SQL."""
    __slots__ = ("name", "offset")

    def __init__(self, name: str, offset: int | None):
        self.name, self.offset = name, offset

    def __repr__(self) -> str:
        return f"@{self.name}+{self.offset}"


UNKNOWN = object()


def split_statements(text: str):
    """Statements of a MySQL script, comments dropped, strings kept intact."""
    current, i, n = [], 0, len(text)
    quote = None
    while i < n:
        ch = text[i]
        if quote:
            current.append(ch)
            if ch == "\\" and i+1 < n:
                current.append(text[i+1])
                i += 2
                continue
            if ch == quote:
                quote = None
            i += 1
            continue
        if ch in "'\"`":
            quote = ch if ch != "`" else "`"
            current.append(ch)
            i += 1
            continue
        if ch == "-" and text.startswith("--", i) or ch == "#":
            end = text.find("\n", i)
            i = n if end < 0 else end
            continue
        if ch == ";":
            statement = "".join(current).strip()
            if statement:
                yield statement
            current = []
            i += 1
            continue
        current.append(ch)
        i += 1
    statement = "".join(current).strip()
    if statement:
        yield statement


_INSERT = re.compile(r"^INSERT\s+INTO\s+`(?P<table>\w+)`\s*\((?P<columns>[^)]*)\)\s*VALUES\s*(?P<values>.*)$",
                     re.IGNORECASE | re.DOTALL)
_VAR = re.compile(r"^@(\w+)(?:\+(\d*))?$")


def _value(token: str):
    token = token.strip()
    if token.upper() == "NULL":
        return None
    if token.upper() == "UNKNOWN":
        return UNKNOWN
    match = _VAR.match(token)
    if match:
        return Var(match.group(1), int(match.group(2)) if match.group(2) else None)
    if token.lower().startswith("0x"):
        try:
            return int(token, 16)
        except ValueError:
            return UNKNOWN
    try:
        return int(token)
    except ValueError:
        pass
    try:
        return float(token)
    except ValueError:
        return UNKNOWN


def _tuples(text: str):
    """Rows of a VALUES list: ``(a, 'b', NULL), (...)``."""
    i, n = 0, len(text)
    while i < n:
        start = text.find("(", i)
        if start < 0:
            return
        i, row, token, quote, string = start+1, [], [], False, None
        while i < n:
            ch = text[i]
            if quote:
                if ch == "\\" and i+1 < n:
                    nxt = text[i+1]
                    token.append({"n": "\n", "r": "\r", "t": "\t", "0": "\0"}.get(nxt, nxt))
                    i += 2
                    continue
                if ch == "'":
                    if i+1 < n and text[i+1] == "'":
                        token.append("'")
                        i += 2
                        continue
                    quote = False
                    string = "".join(token)
                    token = []
                    i += 1
                    continue
                token.append(ch)
                i += 1
                continue
            if ch == "'":
                quote, token = True, []
                i += 1
                continue
            if ch in ",)":
                row.append(string if string is not None else _value("".join(token)))
                token, string = [], None
                i += 1
                if ch == ")":
                    break
                continue
            token.append(ch)
            i += 1
        yield row


def parse_insert(statement: str):
    match = _INSERT.match(statement.strip())
    if not match:
        return None
    columns = [column.strip().strip("`") for column in match.group("columns").split(",")]
    rows = [dict(zip(columns, values)) for values in _tuples(match.group("values"))
            if len(values) == len(columns)]
    return match.group("table"), columns, rows


def _same(old, new) -> bool:
    if old is None or new is None:
        return old is new
    try:
        a, b = float(old), float(new)
        return math.isclose(a, b, rel_tol=1e-6, abs_tol=1e-4)
    except (TypeError, ValueError):
        return str(old) == str(new)


class TdbUpdater:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.db = sqlite3.connect(str(self.path), timeout=30.)
        self.db.execute("PRAGMA busy_timeout=30000")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS aipc_wpp_dumps (name TEXT PRIMARY KEY, size INTEGER,
                imported_at REAL, build TEXT, summary TEXT);
            CREATE TABLE IF NOT EXISTS aipc_wpp_changes (id INTEGER PRIMARY KEY AUTOINCREMENT,
                dump TEXT, tbl TEXT, action TEXT, key TEXT, old TEXT, new TEXT, at REAL);
            CREATE TABLE IF NOT EXISTS aipc_wpp_spawns (tbl TEXT, guid TEXT, entry INTEGER, map INTEGER,
                dump TEXT, at REAL, PRIMARY KEY (tbl, guid));
        """)
        self._columns: dict[str, set[str] | None] = {}
        self._keys: dict[str, list[str] | None] = {}

    def close(self) -> None:
        self.db.close()

    def columns(self, table: str) -> set[str] | None:
        if table not in self._columns:
            names = {row[1] for row in self.db.execute(f"PRAGMA table_info(`{table}`)")}
            self._columns[table] = names or None
        return self._columns[table]

    def primary_key(self, table: str) -> list[str] | None:
        if table not in self._keys:
            key = None
            for row in self.db.execute(f"PRAGMA index_list(`{table}`)"):
                if "primary" in str(row[1]):
                    key = [info[2] for info in self.db.execute(f"PRAGMA index_info('{row[1]}')")]
            self._keys[table] = key
        return self._keys[table]

    def imported(self, name: str, size: int) -> bool:
        row = self.db.execute("SELECT size FROM aipc_wpp_dumps WHERE name=?", (name,)).fetchone()
        return row is not None and int(row[0] or 0) == int(size)

    def mark(self, name: str, size: int, build: str | None, summary: dict) -> None:
        self.db.execute("INSERT OR REPLACE INTO aipc_wpp_dumps VALUES (?,?,?,?,?)",
                        (name, int(size), time.time(), build, json.dumps(summary)))
        self.db.commit()

    # -- spawns ---------------------------------------------------------------
    def _next_guid(self, table: str) -> int:
        row = self.db.execute(f"SELECT MAX(CAST(guid AS INTEGER)) FROM `{table}` "
                              f"WHERE CAST(guid AS INTEGER) >= ?", (GUID_BASE,)).fetchone()
        return max(GUID_BASE, int(row[0] or 0)+1) if row[0] is not None else GUID_BASE

    def _covered(self, table: str, row: dict) -> bool:
        x, y = row.get("position_x"), row.get("position_y")
        if not isinstance(x, (int, float)) or not isinstance(y, (int, float)):
            return True                             # no usable position: never invent one
        radius = SPAWN_RADIUS[table]
        hit = self.db.execute(
            f"SELECT 1 FROM `{table}` WHERE id=? AND map=? AND position_x BETWEEN ? AND ? "
            f"AND position_y BETWEEN ? AND ? AND ((position_x-?)*(position_x-?)+(position_y-?)*(position_y-?)) <= ? LIMIT 1",
            (row.get("id"), row.get("map"), x-radius, x+radius, y-radius, y+radius, x, x, y, y, radius*radius)).fetchone()
        return hit is not None

    # -- rows -----------------------------------------------------------------
    def apply_sql(self, text: str, dump: str) -> dict:
        summary: dict[str, dict[str, int]] = {}
        new_ids: dict[tuple[str, int], str | None] = {}
        next_guid: dict[str, int] = {}
        now = time.time()

        def count(table, what):
            summary.setdefault(table, {}).setdefault(what, 0)
            summary[table][what] += 1

        statements = [parse_insert(statement) for statement in split_statements(text)]
        # Spawns first, so their addon/tracking rows can follow the new GUIDs.
        statements.sort(key=lambda item: 0 if item and item[0] in SPAWN_RADIUS else 1)
        for parsed in statements:
            if parsed is None:
                continue
            table, _columns, rows = parsed
            existing = self.columns(table)
            if not existing:
                count(table, "table_missing")
                continue
            key = self.primary_key(table)
            for row in rows:
                if table in SPAWN_RADIUS and isinstance(row.get("guid"), Var):
                    var = row["guid"]
                    if (SPAWN_VARS.get(var.name) != table or var.offset is None
                            or not isinstance(row.get("id"), int) or not isinstance(row.get("map"), int)):
                        # e.g. a spawn on a transport: map UNKNOWN to WPP
                        count(table, "skipped_unresolved")
                        continue
                    if self._covered(table, row):
                        new_ids[(var.name, var.offset)] = None
                        count(table, "covered")
                        continue
                    guid = next_guid.get(table) or self._next_guid(table)
                    next_guid[table] = guid+1
                    new_ids[(var.name, var.offset)] = str(guid)
                    values = {column: value for column, value in row.items()
                              if column in existing and value is not UNKNOWN and not isinstance(value, Var)}
                    values["guid"] = str(guid)
                    if not isinstance(row.get("PhaseId"), int):
                        values["PhaseId"] = 0          # WPP lists several phases as text
                    self._insert(table, values)
                    self.db.execute("INSERT OR REPLACE INTO aipc_wpp_spawns VALUES (?,?,?,?,?,?)",
                                    (table, str(guid), row.get("id"), row.get("map"), dump, now))
                    self._log(dump, table, "INSERT", {"guid": str(guid)}, None, values, now)
                    count(table, "inserted")
                    continue
                resolved, skip = {}, False
                for column, value in row.items():
                    if isinstance(value, Var):
                        target = new_ids.get((value.name, value.offset)) if value.offset is not None else None
                        if value.name in SPAWN_VARS and (value.name, value.offset) in new_ids:
                            if target is None:
                                skip = True            # its spawn was already in the TDB
                                break
                            resolved[column] = target
                            continue
                        skip = True
                        break
                    resolved[column] = value
                if skip:
                    count(table, "skipped_unresolved")
                    continue
                self._merge(table, key, existing, resolved, dump, now, count)
        self.db.commit()
        return summary

    def _merge(self, table, key, existing, row, dump, now, count) -> None:
        unreliable = UNRELIABLE_COLUMNS.get(table, frozenset())
        values = {column: value for column, value in row.items()
                  if column in existing and value is not UNKNOWN and column not in unreliable}
        if not key or any(values.get(column) is None for column in key):
            count(table, "skipped_no_key")
            return
        where = " AND ".join(f"`{column}`=?" for column in key)
        params = [values[column] for column in key]
        params = [self._sqlite(value) for value in params]
        current = self.db.execute(f"SELECT * FROM `{table}` WHERE {where}", params).fetchone()
        if current is None:
            self._insert(table, values)
            self._log(dump, table, "INSERT", {c: values[c] for c in key}, None, values, now)
            count(table, "inserted")
            return
        names = [description[0] for description in self.db.execute(f"SELECT * FROM `{table}` LIMIT 0").description]
        old = dict(zip(names, current))
        changed = {column: value for column, value in values.items()
                   if column not in key and column != "VerifiedBuild" and value is not None
                   and not _same(old.get(column), value)}
        if not changed:
            count(table, "unchanged")
            return
        if "VerifiedBuild" in values and "VerifiedBuild" in existing:
            changed["VerifiedBuild"] = values["VerifiedBuild"]
        assignments = ", ".join(f"`{column}`=?" for column in changed)
        self.db.execute(f"UPDATE `{table}` SET {assignments} WHERE {where}",
                        [*(self._sqlite(value) for value in changed.values()), *params])
        self._log(dump, table, "UPDATE", {c: values[c] for c in key},
                  {column: old.get(column) for column in changed}, changed, now)
        count(table, "updated")

    @staticmethod
    def _sqlite(value):
        """64-bit unsigned flags exceed SQLite INTEGER: keep them as text (as the TDB does)."""
        if isinstance(value, int) and not -2**63 <= value < 2**63:
            return str(value)
        return value

    def _insert(self, table: str, values: dict) -> None:
        values = {column: self._sqlite(value) for column, value in values.items()}
        columns = list(values)
        self.db.execute(f"INSERT INTO `{table}` ({', '.join(f'`{c}`' for c in columns)}) "
                        f"VALUES ({', '.join('?' for _ in columns)})", [values[c] for c in columns])

    def _log(self, dump, table, action, key, old, new, now) -> None:
        self.db.execute("INSERT INTO aipc_wpp_changes (dump, tbl, action, key, old, new, at) VALUES (?,?,?,?,?,?,?)",
                        (dump, table, action, json.dumps(key, default=str),
                         None if old is None else json.dumps(old, default=str),
                         json.dumps(new, default=str), now))


def revert_column(tdb: Path, table: str, column: str) -> int:
    """Undo every logged WPP update of ``table.column`` (newest first) whose
    value is still the imported one; each undo is logged as REVERT.  Returns
    how many rows were restored."""
    updater = TdbUpdater(tdb)
    try:
        key_columns = updater.primary_key(table) or []
        restored, now = 0, time.time()
        rows = updater.db.execute(
            "SELECT id, dump, key, old, new FROM aipc_wpp_changes WHERE tbl=? AND action='UPDATE' "
            "ORDER BY id DESC", (table,)).fetchall()
        for _id, dump, key_text, old_text, new_text in rows:
            new, old, key = json.loads(new_text), json.loads(old_text or "{}"), json.loads(key_text)
            if column not in new or set(key) != set(key_columns):
                continue
            where = " AND ".join(f"`{name}`=?" for name in key_columns)
            params = [key[name] for name in key_columns]
            current = updater.db.execute(f"SELECT `{column}`, VerifiedBuild FROM `{table}` WHERE {where}",
                                         params).fetchone()
            if current is None or not _same(current[0], new[column]):
                continue                       # changed since: leave it
            undo = {column: old.get(column)}
            if set(new) <= {column, "VerifiedBuild"} and "VerifiedBuild" in old:
                undo["VerifiedBuild"] = old["VerifiedBuild"]
            assignments = ", ".join(f"`{name}`=?" for name in undo)
            updater.db.execute(f"UPDATE `{table}` SET {assignments} WHERE {where}", [*undo.values(), *params])
            updater._log(dump, table, "REVERT", key, {name: (current[0] if name == column else current[1])
                                                       for name in undo}, undo, now)
            restored += 1
        updater.db.commit()
        return restored
    finally:
        updater.close()


# User 2026-10-25: "write how many new things it put in -- 50 monsters, 60 quest
# objectives ...".  Table -> what a person calls it (Hungarian GUI).
TABLE_NAMES = {
    "creature": "lény-spawn", "gameobject": "tárgy-spawn",
    "creature_template": "lény-adat", "creature_template_difficulty": "lény-nehézség",
    "creature_addon": "lény-kiegészítő", "creature_template_addon": "lény-kiegészítő",
    "creature_equip_template": "lény-felszerelés", "creature_model_info": "lény-modell",
    "creature_template_model": "lény-modell", "creature_text": "lény-szöveg",
    "creature_queststarter": "questadó", "creature_questender": "quest-leadó",
    "gameobject_queststarter": "questadó", "gameobject_questender": "quest-leadó",
    "creature_quest_currency": "quest-valuta",
    "gameobject_template": "tárgy-adat", "gameobject_addon": "tárgy-kiegészítő",
    "gameobject_template_addon": "tárgy-kiegészítő", "gameobject_questitem": "tárgy quest-iteme",
    "quest_template": "quest", "quest_objectives": "quest-cél",
    "quest_poi": "quest-POI", "quest_poi_points": "quest-POI",
    "quest_details": "quest-szöveg", "quest_offer_reward": "quest-szöveg",
    "quest_request_items": "quest-szöveg", "quest_reward_display_spell": "quest-jutalom",
    "quest_treasure_pickers": "quest-jutalom", "quest_visual_effect": "quest-effekt",
    "gossip_menu": "gossip", "gossip_menu_option": "gossip", "creature_template_gossip": "gossip",
    "npc_text": "NPC-szöveg", "npc_vendor": "vendor-áru", "npc_spellclick_spells": "spellclick",
    "npc_trainer": "tréner", "trainer": "tréner",
    "conversation_actors": "beszélgetés", "conversation_line_template": "beszélgetés",
    "conversation_template": "beszélgetés", "scene_template": "jelenet",
    "spawn_tracking": "spawn-követés", "spawn_tracking_quest_objective": "spawn-követés",
    "spawn_tracking_state": "spawn-követés", "spawn_tracking_template": "spawn-követés",
    "areatrigger": "areatrigger", "areatrigger_template": "areatrigger",
    "areatrigger_create_properties": "areatrigger", "page_text": "lap-szöveg",
    "points_of_interest": "térkép-pont", "vehicle_template_accessory": "jármű-utas",
    "creature_questitem": "lény quest-iteme", "creature_template_spell": "lény-varázslat",
    "quest_offer_reward_conditional": "quest-szöveg",
}


def human_summary(tables: dict) -> list[str]:
    """``["lény-spawn +120", "quest-cél +5 / frissítve 12", ...]``, biggest first."""
    totals: dict[str, list[int]] = {}
    for table, counts in (tables or {}).items():
        name = TABLE_NAMES.get(table, table)
        entry = totals.setdefault(name, [0, 0])
        entry[0] += int((counts or {}).get("inserted", 0))
        entry[1] += int((counts or {}).get("updated", 0))
    rows = sorted(((name, new, changed) for name, (new, changed) in totals.items() if new or changed),
                  key=lambda row: -(row[1]+row[2]))
    return [f"{name} +{new}" + (f" / frissítve {changed}" if changed else "") if new
            else f"{name} frissítve {changed}" for name, new, changed in rows]


def recycle(path: Path) -> bool:
    """Move a file to the Windows Recycle Bin (recoverable; never a hard delete).

    User 2026-10-25: delete the dumps once imported.  A permanent delete is not
    done here; emptying the bin stays the user's decision.
    """
    import ctypes
    from ctypes import wintypes

    class SHFILEOPSTRUCTW(ctypes.Structure):
        _fields_ = [("hwnd", wintypes.HWND), ("wFunc", wintypes.UINT), ("pFrom", wintypes.LPCWSTR),
                    ("pTo", wintypes.LPCWSTR), ("fFlags", ctypes.c_uint16), ("fAnyOperationsAborted", wintypes.BOOL),
                    ("hNameMappings", ctypes.c_void_p), ("lpszProgressTitle", wintypes.LPCWSTR)]

    FO_DELETE, FOF_SILENT, FOF_NOCONFIRMATION, FOF_ALLOWUNDO, FOF_NOERRORUI = 3, 0x4, 0x10, 0x40, 0x400
    if os.name != "nt" or not Path(path).is_file():
        return False
    operation = SHFILEOPSTRUCTW(None, FO_DELETE, str(Path(path).resolve()) + "\0", None,
                                FOF_ALLOWUNDO | FOF_NOCONFIRMATION | FOF_SILENT | FOF_NOERRORUI,
                                False, None, None)
    result = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(operation))
    return result == 0 and not operation.fAnyOperationsAborted and not Path(path).exists()


def backup(tdb: Path) -> Path:
    """One copy of the TDB as it was before the first import."""
    copy = tdb.with_name(tdb.stem + ".before-wpp-import" + tdb.suffix)
    if not copy.exists():
        shutil.copy2(tdb, copy)
    return copy


def run_wpp(dump: Path, work: Path, exe: Path = WPP_EXE) -> Path:
    """WowPacketParser on a copy of one dump; returns its SQL file."""
    work.mkdir(parents=True, exist_ok=True)
    config = Path(exe).with_name("WowPacketParser.dll.config")
    if WPP_CONFIG.is_file() and (not config.is_file() or config.read_bytes() != WPP_CONFIG.read_bytes()):
        shutil.copy2(WPP_CONFIG, config)
    copy = work / dump.name
    shutil.copy2(dump, copy)
    before = set(work.glob("*.sql"))
    finished = subprocess.run([str(exe), str(copy)], cwd=str(work), capture_output=True,
                              timeout=WPP_TIMEOUT_SECONDS,
                              creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    copy.unlink(missing_ok=True)
    made = sorted(set(work.glob("*.sql")) - before, key=lambda path: path.stat().st_mtime)
    if not made:
        tail = (finished.stdout or b"")[-600:].decode("utf-8", "replace").strip().replace(chr(13), "")
        if finished.returncode == 0 and "error" not in tail.lower() and "exception" not in tail.lower():
            return None                       # parsed, nothing for the world database
        raise RuntimeError(f"WowPacketParser exit {finished.returncode}, no SQL: {tail[-300:]}")
    return made[-1]


def import_dumps(dumps: Path, tdb: Path, *, work: Path, progress: Path | None = None,
                 settled_seconds: float = SETTLED_SECONDS, exe: Path = WPP_EXE,
                 recycle_when=None) -> dict:
    """Every finished, not yet imported dump into the TDB; progress as JSON.

    ``recycle_when(path)``: a dump imported here for which it returns True
    (e.g. the learned TDB has it too) goes to the Recycle Bin afterwards.
    """
    started = time.time()
    files = sorted(path for path in Path(dumps).glob("*.pkt")
                   if time.time()-path.stat().st_mtime >= settled_seconds and path.stat().st_size > 4096)
    state = {"state": "running", "started_at": started, "total": len(files), "done": 0,
             "current": None, "tables": {}, "errors": [], "tdb": str(tdb), "recycled": 0}

    def report(**update):
        state.update(update, elapsed=round(time.time()-started, 1))
        if progress is not None:
            progress.parent.mkdir(parents=True, exist_ok=True)
            tmp = progress.with_suffix(".tmp")
            tmp.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
            os.replace(tmp, progress)

    if not Path(exe).is_file():
        report(state="error", errors=[f"WowPacketParser missing: {exe}"])
        return state
    if files:
        state["backup"] = str(backup(tdb))   # before the updater adds its own tables
    updater = TdbUpdater(tdb)
    try:
        pending = [path for path in files if not updater.imported(path.name, path.stat().st_size)]
        report(total=len(files), skipped=len(files)-len(pending))
        for index, path in enumerate(pending, start=1):
            report(current=path.name, done=state["skipped"]+index-1)
            try:
                sql = run_wpp(path, work, exe)
                if sql is None:
                    updater.mark(path.name, path.stat().st_size, None, {})
                    report(done=state["skipped"]+index)
                    continue
                text = sql.read_text(encoding="utf-8", errors="replace")
                build = (re.search(r"Detected build:\s*(\S+)", text) or [None, None])[1]
                summary = updater.apply_sql(text, path.name)
                updater.mark(path.name, path.stat().st_size, build, summary)
                sql.unlink(missing_ok=True)
                for table, counts in summary.items():
                    total = state["tables"].setdefault(table, {})
                    for what, value in counts.items():
                        total[what] = total.get(what, 0)+value
            except Exception as error:            # one bad dump must not stop the rest
                state["errors"].append(f"{path.name}: {type(error).__name__}: {error}")
            report(done=state["skipped"]+index)
        if recycle_when is not None:
            # A header-only dump (a capture that never saw the game) holds
            # nothing to import; it leaves with the rest.
            for path in Path(dumps).glob("*.pkt"):
                if (path.exists() and path.stat().st_size <= 4096
                        and time.time()-path.stat().st_mtime >= settled_seconds and recycle(path)):
                    state["recycled"] += 1
            for path in files:
                if (path.exists() and updater.imported(path.name, path.stat().st_size)
                        and recycle_when(path) and recycle(path)):
                    state["recycled"] += 1
        state["summary"] = human_summary(state["tables"])
        report(state="done", current=None, done=len(files), finished_at=time.time())
        if progress is not None:
            lines = [f"TDB-frissítés kész: {len(files)} dump, {len(state['errors'])} hiba, "
                     f"{state['recycled']} dump a Lomtárban, {state.get('elapsed', 0):.0f} s",
                     *state["summary"], *state["errors"]]
            progress.with_name("tdb_import_report.txt").write_text("\n".join(lines)+"\n", encoding="utf-8")
    finally:
        updater.close()
    return state
