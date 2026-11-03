"""Import provenance and atomic publication, with tiny static files only."""
import importlib.util
import json
from pathlib import Path
import sqlite3
import struct

import pytest

spec = importlib.util.spec_from_file_location("client_catalog_builder", Path(__file__).parents[1]/"tools/build_client_catalog.py")
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


def inputs(tmp_path):
    source, decoded, definitions = (tmp_path/name for name in ("db2", "decoded", "definitions"))
    for directory in (source, decoded, definitions):
        directory.mkdir()
    raw = bytearray(204)
    raw[:4] = b"WDC5"
    raw[8:12] = b"TEST"
    struct.pack_into("<I", raw, 136, 1)
    struct.pack_into("<I", raw, 156, 0x112233)
    file = source/"QuestV2.db2"
    file.write_bytes(raw)
    definition = definitions/"QuestV2.dbd"
    definition.write_text("tiny fixture", encoding="utf-8")
    metadata = {"type": "table", "name": "QuestV2", "row_count": 1, "layout_hash": "00112233",
                "source_sha256": builder.sha256(file), "definition_sha256": builder.sha256(definition)}
    export = decoded/"QuestV2.jsonl"
    export.write_text(json.dumps(metadata)+"\n"+json.dumps({"type":"row", "id":42,"values":{"ID":42}})+"\n", encoding="utf-8")
    associations = tmp_path/"associations.json"
    associations.write_text(json.dumps({"bindings":[]}), encoding="utf-8")
    world = tmp_path/"original_world.sqlite3"
    with sqlite3.connect(world) as db:
        db.execute("CREATE TABLE original_tdb_marker(value TEXT)")
        db.execute("INSERT INTO original_tdb_marker VALUES ('keep original')")
    return (source, [decoded], definitions, "fixture-revision", associations, world), export


def test_build_is_db2_only_and_keeps_existing_world_file_unchanged(tmp_path):
    arguments, _ = inputs(tmp_path)
    before = arguments[-1].read_bytes()
    output = tmp_path/"client.sqlite3"
    builder.build(output, *arguments)
    with sqlite3.connect(output) as db:
        assert db.execute("SELECT quest_id FROM quest_links").fetchall() == [(42,)]
        assert db.execute("SELECT name FROM sqlite_master WHERE name='original_tdb_marker'").fetchall() == []
        assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert arguments[-1].read_bytes() == before
    assert not list(tmp_path.glob("*.partial-*"))
    with pytest.raises(FileExistsError):
        builder.build(output, *arguments)


def test_wrong_export_hash_cannot_publish_a_partial_catalog(tmp_path):
    arguments, export = inputs(tmp_path)
    lines = export.read_text().splitlines()
    metadata = json.loads(lines[0])
    metadata["source_sha256"] = "0"*64
    export.write_text(json.dumps(metadata)+"\n"+lines[1]+"\n", encoding="utf-8")
    output = tmp_path/"invalid.sqlite3"
    with pytest.raises(ValueError, match="provenance mismatch"):
        builder.build(output, *arguments)
    assert not output.exists() and not list(tmp_path.glob("*.partial-*"))


def test_automatic_import_does_not_require_a_manual_quest_scene_manifest(tmp_path):
    arguments, _ = inputs(tmp_path)
    arguments = (*arguments[:4], None, arguments[-1])
    output = tmp_path/"without-exceptions.sqlite3"
    builder.build(output, *arguments)
    with sqlite3.connect(output) as db:
        assert db.execute("SELECT value FROM metadata WHERE key='reviewed_scene_exceptions_enabled'").fetchone()[0] == 'false'
        assert db.execute("SELECT COUNT(*) FROM quest_scene_candidates").fetchone()[0] == 0
