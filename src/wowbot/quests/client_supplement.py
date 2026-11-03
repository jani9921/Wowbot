"""Read-only ItemEffect/shape references. Static knowledge never authorizes input."""
from __future__ import annotations

from contextlib import closing
from functools import lru_cache
import json
import math
from pathlib import Path
import sqlite3


def default_supplement_path():
    return Path(__file__).resolve().parents[3] / "data" / "client_supplement.sqlite3"


# TrinityCore SharedDefines Targets. Only understood selectors are promoted;
# the complete raw selectors/restrictions remain in every profile.
_UNIT = {6, 21, 25, 35, 45, 53, 57, 61, 63, 64, 65, 66, 67, 68, 69, 70, 71, 74, 75, 132}
_SELF = {1, 18, 22, 62, 125}
_GROUND = {87, 89, 138}
# 38/40/46: UNIT/GAMEOBJECT/DEST_NEARBY_ENTRY -- automatic selection by the
# spell's conditions.  Live 2026-11-02 (26257 It's Alive!, Wake Harvest Golem
# = 25 + 46): unknown, the item read UNKNOWN and was never used on the golem.
_AREA = {7, 8, 15, 16, 20, 30, 31, 33, 34, 38, 40, 46, 51, 52, 56}


def target_profile(effects, restrictions):
    targets = {row[key] for row in effects for key in ("target_a", "target_b") if row[key]}
    modes = set()
    if targets & _UNIT:
        modes.add("UNIT")
    if targets & _GROUND:
        modes.add("GROUND")
    if targets & {23}:
        modes.add("GAMEOBJECT")
    if targets & {26}:
        modes.add("ITEM_OR_GAMEOBJECT")
    unknown = targets - _UNIT - _SELF - _GROUND - _AREA - {23, 26}
    if unknown or not targets:
        mode = "UNKNOWN"
    elif len(modes) > 1:
        mode = "MIXED"
    elif modes:
        mode = next(iter(modes))
    elif targets <= _SELF:
        mode = "SELF"
    else:
        mode = "AREA"  # automatic area selection is not necessarily self cast
    # An explicit destination supplied by the caster is not a unit click.
    masks = {r["target_mask"] for r in restrictions}
    if any(mask and mask & 0x40 for mask in masks):
        mode = "MIXED" if mode in {"UNIT", "GAMEOBJECT", "ITEM_OR_GAMEOBJECT"} else "GROUND"
    if any(mask and mask & 0x10 for mask in masks) and mode == "SELF":
        mode = "ITEM_OR_GAMEOBJECT"
    policy = ("HOSTILE" if targets & {6, 53} else
              "FRIENDLY" if targets & {21, 35, 45, 57, 61, 132} else "ANY")
    if targets & {6, 53} and targets & {21, 35, 45, 57, 61, 132}:
        mode = "MIXED"
    return {"target_mode": mode, "target_relation": policy, "implicit_targets": sorted(targets),
            "target_restrictions": restrictions}


class ClientSupplement:
    @staticmethod
    def power_type(identifier):
        from wowbot.character_resources import resource_reference
        return resource_reference(identifier)

    def __init__(self, path=None):
        self.path = Path(path or default_supplement_path()).resolve()

    def _query(self, kind, identifier):
        try:
            stamp = self.path.stat()
        except OSError:
            return {"status": "MISSING"}
        return json.loads(_query(str(self.path), stamp.st_mtime_ns, stamp.st_size, kind, identifier))

    def item(self, item_id):
        if type(item_id) is not int or item_id <= 0:
            return {}
        return self._query("item", item_id)

    def record(self, table, key):
        return self._query("record", (str(table), int(key)))

    def diagnostics(self):
        return self._query("diagnostics", 0)

    def area_trigger(self, trigger_id):
        return self._query("area", int(trigger_id))

    def conversation_line(self, line_id):
        return self.record("ConversationLine", line_id)


def _record(db, table, key):
    row = db.execute("SELECT record_json FROM db2_rows WHERE table_name=? AND id=?", (table, key)).fetchone()
    return json.loads(row[0]) if row else {}


def _effects(db, spell):
    return [dict(r) for r in db.execute("SELECT * FROM spell_effects WHERE spell_id=? AND difficulty_id=0",
                                       (spell,))]


def _use_profile(db, effect):
    spell = effect["spell_id"]
    rows = _effects(db, spell)
    restrictions = [dict(r) for r in db.execute(
        "SELECT * FROM spell_targets WHERE spell_id=? AND difficulty_id=0", (spell,))]
    result = {**effect, **target_profile(rows, restrictions), "difficulty_id": 0}
    name = db.execute("SELECT name FROM spell_names WHERE id=?", (spell,)).fetchone()
    result["spell_name"] = name[0] if name else None
    result["ranges"] = [_record(db, "SpellRange", r[0]) for r in db.execute(
        "SELECT DISTINCT range_id FROM spell_misc WHERE spell_id=? AND difficulty_id=0", (spell,))]
    # SPELL_ATTR2_CAN_TARGET_DEAD (Attributes[2] & 0x1): the use is meant for a
    # corpse ("use the item on a dead X").  Unknown stays False (live unit only).
    misc = [_record(db, "SpellMisc", r[0]) for r in db.execute(
        "SELECT id FROM spell_misc WHERE spell_id=? AND difficulty_id=0", (spell,))]
    attributes = [m.get("Attributes") for m in misc if isinstance(m.get("Attributes"), list)]
    result["can_target_dead"] = bool(attributes) and all(
        len(a) > 2 and type(a[2]) is int and bool(a[2] & 0x1) for a in attributes)
    result["status"] = ("MISSING_SPELL_EFFECT" if not rows else
                        "CONDITIONAL" if effect["condition_id"] or effect["specialization_id"] else "RESOLVED")
    result["credit_links"] = []
    # A summoned actor can be a quest's boarding/enabling credit without an
    # explicit KILL_CREDIT effect. Keep this a relation, never earned credit.
    result["summoned_creatures"] = []
    for row in rows:
        raw = _record(db, "SpellEffect", row["id"])
        index = raw.get("EffectIndex")
        if (row["effect"] == 28 and row["misc1"] > 0
                and type(index) is int and 0 <= index < 32
                and 46 in (row["target_a"], row["target_b"])):
            result["summoned_creatures"].append({"entry": row["misc1"], "effect_mask": 1 << index})
    result["triggered_spells"] = []
    cones = []
    queue, visited, truncated = [(spell, [spell])], set(), False
    while queue and len(visited) < 128:
        current, chain = queue.pop(0)
        if current in visited:
            continue
        visited.add(current)
        result["triggered_spells"].append({"spell_id": current, "spell_chain": chain})
        for row in _effects(db, current):
            if 60 in (row["target_a"], row["target_b"]):
                raw = _record(db, "SpellEffect", row["id"])
                radii = [_record(db, "SpellRadius", key) for key in raw.get("EffectRadiusIndex", []) if key]
                limits = [r.get("Radius") for r in radii]
                targets = [_record(db, "SpellTargetRestrictions", r[0]) for r in db.execute(
                    "SELECT id FROM spell_targets WHERE spell_id=? AND difficulty_id=0", (current,))]
                degrees = [r.get("ConeDegrees") for r in targets]
                valid = (len(limits) == len(degrees) == 1
                         and type(limits[0]) in {int, float} and math.isfinite(limits[0]) and limits[0] > 0
                         and type(degrees[0]) in {int, float} and math.isfinite(degrees[0]) and 0 < degrees[0] <= 180
                         and not radii[0].get("RadiusPerLevel")
                         and {row["target_a"], row["target_b"]} <= {0, 60})
                cones.append({"mode": "FORWARD_CONE", "status": "RESOLVED" if valid else "MISSING_GEOMETRY",
                              "spell_id": current, "effect_id": row["id"], "spell_chain": chain,
                              "effect_index": raw.get("EffectIndex"),
                              "radius": limits[0] if valid else None,
                              "cone_degrees": degrees[0] if valid else None})
            if row["effect"] in {90, 134} and row["misc1"] > 0:
                result["credit_links"].append({"kind": "CREATURE_CREDIT", "id": row["misc1"],
                    "spell_chain": chain, "effect_id": row["id"], "conditional": len(chain) > 1})
            if row["item_type"] > 0 and row["effect"] in {24, 157}:
                result["credit_links"].append({"kind": "ITEM", "id": row["item_type"],
                    "spell_chain": chain, "effect_id": row["id"], "conditional": len(chain) > 1})
            if row["trigger_spell"] > 0 and len(chain) < 8:
                queue.append((row["trigger_spell"], chain+[row["trigger_spell"]]))
            elif row["trigger_spell"] > 0 and row["trigger_spell"] not in visited:
                truncated = True
    result["credit_search_truncated"] = truncated or bool(queue)
    if cones:
        result["delivery"] = (cones[0] if len(cones) == 1 and not result["credit_search_truncated"]
                              and result["target_mode"] == "SELF" else
                              {"mode": "FORWARD_CONE", "status": "AMBIGUOUS"})
        durations = [_record(db, "SpellDuration", _record(db, "SpellMisc", r[0]).get("DurationIndex", 0))
                     for r in db.execute("SELECT id FROM spell_misc WHERE spell_id=? AND difficulty_id=0", (spell,))]
        result["delivery"]["duration_ms"] = durations[0].get("Duration") if len(durations) == 1 else None
        # The execution adapter understands a self-applied periodic emitter
        # with one dummy entry-cone child. Other effect/target families stay
        # explicit, rather than inheriting this item's activation semantics.
        shape = result["delivery"]
        children = _effects(db, shape.get("spell_id", 0))
        duration = shape.get("duration_ms")
        if (shape.get("status") == "RESOLVED"
                and (len(rows) != 1 or rows[0]["effect"] != 6 or rows[0]["aura"] != 23
                     or {rows[0]["target_a"], rows[0]["target_b"]} != {0, 1}
                     or len(children) != 1 or children[0]["effect"] != 3
                     or children[0]["trigger_spell"] != 0
                     or shape["spell_chain"] != [spell, rows[0]["trigger_spell"]]
                     or type(shape.get("effect_index")) is not int or not 0 <= shape["effect_index"] < 32
                     or type(duration) not in {int, float} or not math.isfinite(duration)
                     or not 0 < duration <= 10000)):
            shape["status"] = "UNSUPPORTED_EFFECT_FAMILY"
    return result


@lru_cache(maxsize=512)
def _query(path, modified, size, kind, identifier):
    try:
        with closing(sqlite3.connect(Path(path).as_uri()+"?mode=ro", uri=True)) as db:
            db.row_factory = sqlite3.Row
            if db.execute("PRAGMA user_version").fetchone()[0] != 1:
                return json.dumps({"status": "UNSUPPORTED_SCHEMA"})
            if kind == "record":
                value = _record(db, *identifier)
            elif kind == "diagnostics":
                value = {"status": "READY", "read_only": True, "path": path,
                         "tables": [dict(r) for r in db.execute("SELECT * FROM source_files")],
                         "metadata": {r["key"]: json.loads(r["value"]) for r in db.execute("SELECT * FROM metadata")}}
            elif kind == "area":
                value = _record(db, "AreaTrigger", identifier)
                # Keep type/shape ID as data. Unknown shape semantics cannot
                # become a radius or a guessed navigation destination.
                if value:
                    value = {"status": "REFERENCE_ONLY", "trigger": value, "source": "CLIENT_DB2"}
            elif kind == "item":
                item = db.execute("SELECT * FROM items WHERE id=?", (identifier,)).fetchone()
                effects = [dict(r) for r in db.execute("""SELECT e.*,l.id AS link_id FROM item_effect_links l
                    LEFT JOIN item_effects e ON e.id=l.effect_id WHERE l.item_id=? ORDER BY e.slot,e.id""",
                                                      (identifier,))]
                uses = [_use_profile(db, e) for e in effects if e["trigger_type"] == 0 and e["spell_id"]]
                value = {"item_id": identifier, "name": item["name"] if item else None,
                         "description": item["description"] if item else None, "effects": effects, "uses": uses,
                         "status": "RESOLVED" if uses else "NO_ON_USE_EFFECT",
                         "source": "CLIENT_DB2_ITEM_EFFECT", "confirmed": False}
                if any(e["id"] is None for e in effects):
                    value["status"] = "MISSING_ITEM_EFFECT"
            else:
                value = {}
            return json.dumps(value)
    except (OSError, sqlite3.Error, ValueError, KeyError, TypeError):
        return json.dumps({"status": "INVALID"})
