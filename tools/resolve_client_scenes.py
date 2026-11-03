"""Refresh derived scene links from existing client DB2 and existing read-only TDB.

Only the project-owned client catalog is copied for atomic publication. The
configured TDB is never copied or modified; no extraction/input is started.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sqlite3
import sys
from uuid import uuid4

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tools.build_client_catalog import _link_quests, sha256
from wowbot.quests.scene_resolver import index_relations


def resolve_catalog(source, output, world, associations=None):
    source, output, world = Path(source).resolve(), Path(output).resolve(), Path(world).resolve()
    if output.exists() or source==output:
        raise FileExistsError(output)
    temporary = output.with_name(output.name+'.partial-'+uuid4().hex)
    digest = sha256(world)
    original = sqlite3.connect(source.as_uri()+'?mode=ro',uri=True)
    original.execute('PRAGMA query_only=ON')
    db = None
    try:
        if original.execute("SELECT COUNT(*) FROM spell_effects").fetchone()[0] == 0:
            raise ValueError('SpellEffect must be imported before resolving scenes')
        output.parent.mkdir(parents=True,exist_ok=True)
        with sqlite3.connect(temporary) as db:
            original.backup(db)
            for table in ('spell_scene_edges','quest_scene_candidates','quest_scene_resolution','quest_scene_seeds','scene_path_candidates'):
                db.execute('DROP TABLE IF EXISTS "'+table+'"')
            db.execute('DELETE FROM quest_routes')
            db.execute("DELETE FROM metadata WHERE key='quest_association_sha256'")
            summary = index_relations(db,world)
            if associations is not None:
                _link_quests(db,associations,world)
            db.execute("INSERT OR REPLACE INTO metadata VALUES ('world_reference_sha256',?)",(json.dumps(digest),))
            db.execute("INSERT OR REPLACE INTO metadata VALUES ('reviewed_scene_exceptions_enabled',?)",(json.dumps(associations is not None),))
            db.execute("INSERT OR REPLACE INTO metadata VALUES ('schema_version','3')")
            if db.execute('PRAGMA integrity_check').fetchone()[0]!='ok' or sha256(world)!=digest:
                raise ValueError('Catalog integrity or original TDB changed during resolution')
        db.close()  # Windows cannot rename/delete a SQLite file while it is open.
        db = None
        if output.exists():
            raise FileExistsError(output)
        temporary.rename(output)
        return summary
    finally:
        if db is not None:
            db.close()
        original.close()
        temporary.unlink(missing_ok=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--catalog',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--world-reference',type=Path,required=True)
    parser.add_argument('--associations',type=Path,help='Optional reviewed exceptions, not the primary resolver')
    args=parser.parse_args()
    print(json.dumps(resolve_catalog(args.catalog,args.output,args.world_reference,args.associations)))
