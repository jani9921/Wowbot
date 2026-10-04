from pathlib import Path
import json

from wowbot.client_session import new_session, write_session_state


def test_new_session_uses_unique_session_directory(tmp_path: Path):
    first = new_session(tmp_path / "runtime", "client-1", "CharA", "Realm")
    second = new_session(tmp_path / "runtime", "client-1", "CharB", "Realm")

    assert first.session_id != second.session_id
    assert first.state_path != second.state_path

    pointer = json.loads((tmp_path / "runtime" / "current_session.json").read_text())
    assert pointer["session_id"] == second.session_id
    assert pointer["character_name"] == "CharB"


def test_write_session_state_marks_fresh_session(tmp_path: Path):
    session = new_session(tmp_path / "runtime", "client-1", "CharA", None)
    path = session.state_path
    write_session_state(path, {"map_id": 1, "character_name": "CharA"}, session)

    state = json.loads(path.read_text())
    assert state["session_id"] == session.session_id
    assert state["state_fresh"] is True
    assert state["state_writer"] == "wowbot_session_bridge"
    assert state["character_name"] == "CharA"
