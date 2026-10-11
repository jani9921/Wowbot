"""The TDB MySQL dump -> SQLite converter (tools/convert_tdb_mysql_to_sqlite.py).

The TDB is not in the repository (655 MB); users build it from the official
TrinityCore dump with this converter (docs/TDB_SETUP.md).  The SQL is parsed,
never executed.
"""
from pathlib import Path
import sqlite3
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import convert_tdb_mysql_to_sqlite as converter  # noqa: E402

DUMP = """-- MySQL dump 8.0
DROP TABLE IF EXISTS `creature_template`;
CREATE TABLE `creature_template` (
  `entry` int unsigned NOT NULL DEFAULT '0',
  `name` char(100) NOT NULL DEFAULT '',
  `speed` float NOT NULL DEFAULT '1',
  PRIMARY KEY (`entry`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
INSERT INTO `creature_template` VALUES (156891,'Bjorn Stouthands',1),(162943,'Hjalmar\\'s ghost; DROP TABLE x',1.25),(7,NULL,0);
CREATE TABLE `creature` (
  `guid` bigint unsigned NOT NULL,
  `id` int unsigned NOT NULL,
  `position_x` float NOT NULL,
  KEY `idx_id` (`id`)
) ENGINE=InnoDB;
INSERT INTO `creature` VALUES (18446744073709551615,156891,89.684);
"""


def test_dump_is_converted_without_executing_sql(tmp_path):
    source = tmp_path / "world.sql"
    source.write_text(DUMP, encoding="utf-8")
    destination = tmp_path / "world.sqlite3"
    converter.convert(source, destination, overwrite=False)
    db = sqlite3.connect(destination)
    rows = db.execute("SELECT entry, name, speed FROM creature_template ORDER BY entry").fetchall()
    assert rows == [(7, None, 0), (156891, "Bjorn Stouthands", 1), (162943, "Hjalmar's ghost; DROP TABLE x", 1.25)]
    # An unsigned 64-bit value beyond SQLite INTEGER is kept exactly as text.
    assert db.execute("SELECT guid, id FROM creature").fetchone() == ("18446744073709551615", 156891)
    meta = dict(db.execute("SELECT key, value FROM _tdb_import_metadata"))
    assert meta["table_count"] == "2" and meta["row_count"] == "4"
    assert {name for (name,) in db.execute("SELECT name FROM sqlite_master WHERE type='index'")}
    db.close()
