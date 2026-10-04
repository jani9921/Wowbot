"""Per-user memory profile and export-only start (user 2026-10-03).

"Nem processre kellene ... a memory-t hanem felhasználóra, vagy karakterre,
meg a bindings cache nélkül is kéne tudjon csatlakozni, hogy utána lehessen
exportálni egy újat (szűz PC)."
"""
import sqlite3

import pytest

from wowbot.agent.bindings import BindingError, NoBindingsCache
from wowbot.agent.executor import RecordingExecutor
from wowbot.agent.profile_store import profile_directory
from wowbot.agent.runtime import AgentRuntime
from test_agent_runtime import Sensor


def test_pid_folders_share_one_user_profile_and_migrate_once(tmp_path, monkeypatch):
    monkeypatch.setenv("AIPC_PROFILE", "tester")
    monkeypatch.delenv("AIPC_PROFILE_DIR", raising=False)
    old = tmp_path / "agent" / "pid-111"
    old.mkdir(parents=True)
    with sqlite3.connect(old / "agent_memory.sqlite3") as con:
        con.execute("create table journal (id integer primary key, kind text)")
        con.execute("insert into journal (kind) values ('LEARNED')")
    (tmp_path / "agent" / "quest_relevant_npcs.json").write_text('{"1": {}}', encoding="utf-8")
    first = profile_directory(tmp_path / "agent" / "pid-222")
    assert first == tmp_path / "agent" / "profiles" / "tester"
    with sqlite3.connect(first / "agent_memory.sqlite3") as con:
        assert con.execute("select kind from journal").fetchall() == [("LEARNED",)]
    assert (first / "quest_relevant_npcs.json").exists()
    assert profile_directory(tmp_path / "agent" / "pid-333") == first      # same profile
    assert profile_directory(tmp_path / "custom") == tmp_path / "custom"   # tools/tests


def test_export_only_bindings_refuse_every_key():
    bindings = NoBindingsCache()
    assert not bindings.contains("MOVEFORWARD") and bindings.unchanged()
    with pytest.raises(BindingError):
        bindings.resolve("MOVEFORWARD")
    assert bindings.preflight("QUEST")["ready"] is False


def test_runtime_connects_without_a_cache_but_never_arms(tmp_path):
    runtime = AgentRuntime(42, None, tmp_path / "output", sensor=Sensor(),
                           executor=RecordingExecutor(), vision=False)
    try:
        runtime.agent.set_goal("Questelj", 1.)
        with pytest.raises(ValueError):
            runtime.mode("FULL_AI")
        assert runtime.agent.mode.value == "MANUAL"
    finally:
        runtime.close()
