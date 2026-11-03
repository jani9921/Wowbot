"""WoW runs Lua 5.1: at most 60 upvalues per function, 200 locals per chunk.

Live 2026-11-02 15:48 (addon 0.9.83): FrameXML.log "function at line 2635
has more than 60 upvalues" -- the whole AIPlayerControllerExport.lua did not
load and the game showed nothing of AIPC.  The lupa harness tests compile
with Lua 5.5 (255 upvalues) and never saw it.  Every shipped Lua file must
compile under Lua 5.1."""
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FILES = sorted((ROOT / "addon").glob("AIPlayerControllerExport*/*.lua"))


@pytest.mark.parametrize("path", FILES, ids=lambda p: f"{p.parent.name}/{p.name}")
def test_every_addon_file_compiles_under_lua_5_1(path):
    lua51 = pytest.importorskip("lupa.lua51")
    runtime = lua51.LuaRuntime()
    check = runtime.eval("function(s, name) local fn, err = loadstring(s, name); return err or 'ok' end")
    assert check(path.read_text(encoding="utf-8"), path.name) == "ok"
