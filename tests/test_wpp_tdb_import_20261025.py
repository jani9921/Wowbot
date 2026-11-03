"""Merge WowPacketParser SQL into the TDB (user 2026-10-25: "everything should
be updated in it", the original TDB, from the Ymir dumps)."""
import sqlite3

from wowbot.agent.wpp_tdb_import import GUID_BASE, TdbUpdater, UNKNOWN, Var, parse_insert, split_statements

SQL = r"""
SET @CGUID := SET_VALUE_MANUALLY_HERE;
DELETE FROM `creature_template` WHERE `entry` IN (1, 2);
INSERT INTO `creature_template` (`entry`, `faction`, `npcflag`, `RangeAttackTime`, `unit_flags2`) VALUES
(1, 190, 3, UNKNOWN, 0x800), -- 1
(2, 35, 0, 2000, 0x0); -- 2 ; with a semicolon in a comment
INSERT INTO `creature` (`guid`, `id`, `map`, `PhaseId`, `position_x`, `position_y`, `position_z`, `VerifiedBuild`) VALUES
(@CGUID+0, 1, 2444, '19846 - 19847', 100, 100, 5, 70448),
(@CGUID+1, 1, 2444, 0, 500, 500, 5, 70448);
INSERT INTO `creature_addon` (`guid`, `auras`) VALUES
(@CGUID+0, '364118'),
(@CGUID+1, '376861');
INSERT INTO `creature_text` (`CreatureID`, `GroupID`, `ID`, `Text`) VALUES
(1, @GROUP_ID+0, @ID+, 'It\'s mine; all of it!');
"""


def tdb(tmp_path):
    path = tmp_path / "tdb.sqlite3"
    db = sqlite3.connect(path)
    db.executescript("""
        CREATE TABLE creature_template (entry INTEGER, name TEXT, faction INTEGER, npcflag TEXT,
            RangeAttackTime INTEGER, unit_flags2 INTEGER, ScriptName TEXT);
        CREATE UNIQUE INDEX idx_creature_template_primary_0 ON creature_template(entry);
        CREATE TABLE creature (guid TEXT, id INTEGER, map INTEGER, PhaseId INTEGER, position_x REAL,
            position_y REAL, position_z REAL, VerifiedBuild INTEGER);
        CREATE UNIQUE INDEX idx_creature_primary_0 ON creature(guid);
        CREATE TABLE creature_addon (guid TEXT, auras TEXT);
        CREATE UNIQUE INDEX idx_creature_addon_primary_0 ON creature_addon(guid);
        CREATE TABLE creature_text (CreatureID INTEGER, GroupID INTEGER, ID INTEGER, Text TEXT);
        INSERT INTO creature_template VALUES (1, 'Old Name', 35, '0', 2000, 0, 'npc_scripted');
        INSERT INTO creature VALUES ('5', 1, 2444, 0, 495, 505, 5, 46658);
    """)
    db.commit()
    db.close()
    return path


def test_statements_values_and_variables_parse():
    statements = list(split_statements(SQL))
    assert not any(statement.startswith("--") for statement in statements)
    table, columns, rows = parse_insert(statements[2])
    assert table == "creature_template" and columns[:3] == ["entry", "faction", "npcflag"]
    assert rows[0]["RangeAttackTime"] is UNKNOWN and rows[0]["unit_flags2"] == 0x800
    text = parse_insert(statements[-1])[2][0]
    assert text["Text"] == "It's mine; all of it!" and isinstance(text["GroupID"], Var)


def test_rows_merge_without_losing_tdb_only_columns(tmp_path):
    path = tdb(tmp_path)
    updater = TdbUpdater(path)
    summary = updater.apply_sql(SQL, "dump.pkt")
    db = updater.db
    # Existing template: only the differing sniffed columns change; ScriptName stays.
    assert db.execute("SELECT faction, npcflag, unit_flags2, RangeAttackTime, ScriptName, name "
                      "FROM creature_template WHERE entry=1").fetchone() == (190, "3", 2048, 2000, "npc_scripted", "Old Name")
    assert summary["creature_template"] == {"updated": 1, "inserted": 1}
    # Spawns: one near TDB guid 5 (covered), one new under the reserved range.
    assert summary["creature"] == {"inserted": 1, "covered": 1}
    (guid,) = db.execute("SELECT guid FROM creature WHERE CAST(guid AS INTEGER) >= ?", (GUID_BASE,)).fetchone()
    assert db.execute("SELECT PhaseId FROM creature WHERE guid=?", (guid,)).fetchone() == (0,)
    # The new spawn's addon follows its GUID; the covered spawn's addon is skipped.
    assert db.execute("SELECT guid, auras FROM creature_addon").fetchall() == [(guid, "364118")]
    assert summary["creature_text"] == {"skipped_unresolved": 1}
    old, new = db.execute("SELECT old, new FROM aipc_wpp_changes WHERE tbl='creature_template' AND action='UPDATE'").fetchone()
    assert '"faction": 35' in old and '"faction": 190' in new
    updater.mark("dump.pkt", 123, "V12_1_5_70448", summary)
    assert updater.imported("dump.pkt", 123) and not updater.imported("dump.pkt", 124)
    updater.close()


def test_a_spawn_with_an_unknown_map_is_skipped_not_an_error(tmp_path):
    """Live 2026-10-25: a transport spawn had `map` UNKNOWN; binding it failed the dump."""
    updater = TdbUpdater(tdb(tmp_path))
    summary = updater.apply_sql(
        "INSERT INTO `creature` (`guid`, `id`, `map`, `position_x`, `position_y`) VALUES "
        "(@CGUID+0, 7, UNKNOWN, 1, 1);", "dump.pkt")
    assert summary["creature"] == {"skipped_unresolved": 1}
    updater.close()


def test_human_summary_names_what_went_in():
    from wowbot.agent.wpp_tdb_import import human_summary
    lines = human_summary({"creature": {"inserted": 50}, "quest_objectives": {"inserted": 60, "updated": 3},
                           "gossip_menu": {"unchanged": 9}})
    assert lines == ["quest-cél +60 / frissítve 3", "lény-spawn +50"]
