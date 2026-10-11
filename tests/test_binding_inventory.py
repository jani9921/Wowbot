import json
from pathlib import Path
from wowbot.agent.binding_inventory import BindingInventory
from wowbot.agent.bindings import BindingsCache
from test_agent_transport import lua_runtime, ADDON


def test_lua_catalog_category_not_key_unbound_saved_and_invalidated():
    lua = lua_runtime()
    lua.execute('''
        function GetNumBindings() return 2 end
        function GetBinding(i)
            if i==1 then return "MOVEFORWARD", "MOVEMENT", "W", "UP" end
            return "ACTIONBUTTON2", "ACTIONBAR", nil, nil
        end
        function GetCurrentBindingSet() return 2 end
        function UnitGUID() return "Player-1" end
    ''')
    lua.execute((ADDON / "Bindings.lua").read_text(encoding="utf-8"), "AIPC", lua.globals().ns)
    page = json.loads(lua.eval('ns.EncodeJSON(ns.BindingCatalogPage())'))
    assert page["rows"][0] == {"action": "MOVEFORWARD", "category": "MOVEMENT", "primary": "W", "secondary": "UP", "normal_primary_action": "", "normal_secondary_action": ""}
    assert page["rows"][1]["primary"] == ""
    assert lua.eval('AIPlayerControllerExportDB.binding_catalog.rows[1].action') == "MOVEFORWARD"
    lua.execute('ns.InvalidateBindings()')
    assert lua.eval('ns.BindingCatalogPage().revision') == 2
    lua.execute('''
        Enum={BindingContext={None=0}}
        function GetBindingAction(key, overrides, context)
            assert(overrides==false and context==0)
            return "MOVEFORWARD"
        end
        ns.InvalidateBindings()
    ''')
    assert lua.eval('ns.BindingCatalogPage().rows[1].normal_primary_action') == "MOVEFORWARD"
    lua.execute('function GetBinding(i) return {secret=true}, "cat", "W" end; ns.InvalidateBindings()')
    assert lua.eval('ns.BindingCatalogPage().status') == "unavailable"


def test_inventory_out_of_order_revision_and_no_cache_mutation(tmp_path):
    path = tmp_path / "bindings-cache.wtf"
    path.write_text('bind "Z" "MOVEFORWARD"')
    original = path.read_bytes()
    inventory = BindingInventory(tmp_path, BindingsCache(path), 42)
    def row(action): return {"action": action, "category": "cat", "primary": "W", "secondary": ""}
    def feed(index, rows, revision=1, now=1):
        inventory.ingest({"session_id": "s", "character_guid": "p", "binding_catalog_page": {
            "status": "ok", "revision": revision, "page": index, "pages": 2, "count": 17, "rows": rows},
            "actionbar": [{"slot": 1, "kind": "spell", "id": 42, "name": "Test", "action": "ACTIONBUTTON1", "binding_primary": "1"}]}, now)
    feed(1, [row("MOVEFORWARD")])
    assert not inventory.status["complete"]
    feed(0, [row(f"A{i}") for i in range(16)], now=2)
    report = json.loads(inventory.path.read_text())
    assert report["complete"] and len(report["bindings"]) == 17
    assert report["actionbar"][0]["id"] == 42
    assert not report["authoritative_for_input"] and report["differences"]
    assert path.read_bytes() == original
    feed(0, [row(f"B{i}") for i in range(16)], revision=2, now=3)
    assert not inventory.status["complete"]
    assert len(json.loads(inventory.path.read_text())["bindings"]) == 16


def test_live_validation_uses_controls_and_waits_for_unseen_catalog_rows(tmp_path):
    path = tmp_path / "bindings-cache.wtf"
    path.write_text('bind "W" "MOVEFORWARD"\nbind "Q" "TURNLEFT"\nbind "1" "ACTIONBUTTON1"\n')
    inventory = BindingInventory(tmp_path, BindingsCache(path), 42)
    inventory.ingest({
        "session_id": "s", "character_guid": "p",
        "control_bindings": {
            "MOVEFORWARD": {"primary": "W", "secondary": ""},
            "TURNLEFT": {"primary": "Q", "secondary": ""},
        },
        "binding_catalog_page": {"status": "ok", "revision": 1, "binding_set": 1,
                                 "page": 0, "pages": 2, "count": 17,
                                 "rows": [{"action": f"A{i}", "category": "cat",
                                           "primary": "", "secondary": ""}
                                          for i in range(16)]},
        "actionbar": [],
    }, 1)
    check = inventory.validate_actions(["MOVEFORWARD", "TURNLEFT", "ACTIONBUTTON1"])
    assert check["mismatches"] == []
    assert check["unverified"] == ["ACTIONBUTTON1"]
    assert check["ready"] is False


def test_live_validation_reports_exact_client_cache_mismatch(tmp_path):
    path = tmp_path / "bindings-cache.wtf"
    path.write_text('bind "A" "TURNLEFT"\n')
    inventory = BindingInventory(tmp_path, BindingsCache(path), 42)
    inventory.ingest({
        "control_bindings": {"TURNLEFT": {"primary": "Q", "secondary": ""}},
        "binding_catalog_page": {"status": "ok", "revision": 1, "binding_set": 1,
                                 "page": 0, "pages": 1, "count": 1,
                                 "rows": [{"action": "TURNLEFT", "category": "cat",
                                           "primary": "Q", "secondary": ""}]},
        "actionbar": [],
    }, 1)
    check = inventory.validate_actions(["TURNLEFT"])
    assert check["unverified"] == []
    assert check["mismatches"] == [{"action": "TURNLEFT", "client": ["Q"],
                                     "selected_cache": ["A"]}]
    assert check["ready"] is False


def test_known_live_control_mismatch_blocks_before_catalog_arrives(tmp_path):
    # Issue #77: no catalog page yet, but control_bindings already contradict
    # the selected cache; validate_actions must not report ready.
    path = tmp_path / "bindings-cache.wtf"
    path.write_text('bind "W" "MOVEFORWARD"\nbind "S" "MOVEBACKWARD"')
    inventory = BindingInventory(tmp_path, BindingsCache(path), 42)
    inventory.ingest({"control_bindings": {"MOVEFORWARD": {"primary": "Q", "secondary": ""}}}, 1)
    result = inventory.validate_actions(["MOVEFORWARD", "MOVEBACKWARD"])
    assert result["supported"] is False and result["ready"] is False
    assert result["mismatches"] == [{"action": "MOVEFORWARD", "client": ["Q"], "selected_cache": ["W"]}]
    inventory.ingest({"control_bindings": {"MOVEFORWARD": {"primary": "W", "secondary": ""}}}, 2)
    assert inventory.validate_actions(["MOVEFORWARD", "MOVEBACKWARD"])["ready"] is True
