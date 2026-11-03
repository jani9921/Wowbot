"""WPP misreads quest_objectives.ConditionalAmount for 70448/70575 (2026-10-25).

All 98 quest_objectives updates of the imported dumps set it to text bytes
(0x20202020 "    ", 0x30303030 "0000").  The column is no longer merged and
the logged updates can be undone.
"""
import json
import sqlite3

from wowbot.agent.wpp_tdb_import import TdbUpdater, revert_column

SQL = """
INSERT INTO `quest_objectives` (`ID`, `QuestID`, `Type`, `ConditionalAmount`, `Description`, `VerifiedBuild`) VALUES
(394179, 55174, 1, 538976288, 'Cook the meat on the campfire', 70575);
"""


def tdb(tmp_path):
    path = tmp_path / "tdb.sqlite3"
    db = sqlite3.connect(path)
    db.executescript("""
        CREATE TABLE quest_objectives (ID INTEGER, QuestID INTEGER, Type INTEGER, ConditionalAmount INTEGER,
            Description TEXT, VerifiedBuild INTEGER);
        CREATE UNIQUE INDEX idx_quest_objectives_primary_0 ON quest_objectives(ID);
        INSERT INTO quest_objectives VALUES (394179, 55174, 1, 0, 'Cook the meat on the campfire', 70448);
        INSERT INTO quest_objectives VALUES (388448, 54951, 0, 0, 'First Aid Kit used on Bjorn Stouthands', 70448);
    """)
    db.commit()
    db.close()
    return path


def test_the_misparsed_column_is_never_merged(tmp_path):
    path = tdb(tmp_path)
    updater = TdbUpdater(path)
    summary = updater.apply_sql(SQL, "dump.pkt")
    updater.db.commit()
    row = updater.db.execute("SELECT ConditionalAmount, VerifiedBuild FROM quest_objectives WHERE ID=394179").fetchone()
    updater.close()
    assert row == (0, 70448) and summary["quest_objectives"] == {"unchanged": 1}


def test_logged_garbage_is_reverted_unless_changed_since(tmp_path):
    path = tdb(tmp_path)
    updater = TdbUpdater(path)
    db = updater.db
    for key, new in ((394179, 538976288), (388448, 1131570547)):     # what the old import did
        db.execute("UPDATE quest_objectives SET ConditionalAmount=?, VerifiedBuild=70575 WHERE ID=?", (new, key))
        updater._log("dump.pkt", "quest_objectives", "UPDATE", {"ID": key},
                     {"ConditionalAmount": 0, "VerifiedBuild": 70448},
                     {"ConditionalAmount": new, "VerifiedBuild": 70575}, 1.)
    db.execute("UPDATE quest_objectives SET ConditionalAmount=7 WHERE ID=388448")   # edited by hand since
    db.commit()
    updater.close()
    assert revert_column(path, "quest_objectives", "ConditionalAmount") == 1
    db = sqlite3.connect(path)
    assert db.execute("SELECT ConditionalAmount, VerifiedBuild FROM quest_objectives WHERE ID=394179").fetchone() == (0, 70448)
    assert db.execute("SELECT ConditionalAmount FROM quest_objectives WHERE ID=388448").fetchone() == (7,)
    (action, new), = db.execute("SELECT action, new FROM aipc_wpp_changes WHERE action='REVERT'").fetchall()
    assert json.loads(new) == {"ConditionalAmount": 0, "VerifiedBuild": 70448}
    assert revert_column(path, "quest_objectives", "ConditionalAmount") == 0        # idempotent
