from copy import deepcopy
import pytest
from wowbot.agent.binding_inventory import create_controller_cache
from wowbot.agent.bindings import BindingsCache, BindingError


def report():
    return {"complete": True, "source": "ADDON_GET_BINDING", "pid": 42,
            "session_id": "s", "character_guid": "p", "received_at": 10.,
            "count_expected": 4, "pages_expected": 1, "pages_received": 1,
            "bindings": [{"action": a, "primary": k, "secondary": second} for a, k, second in
                         [("MOVEFORWARD", "W", "UP"), ("JUMP", "SPACE", ""),
                          ("TARGETNEARESTENEMY", "TAB", ""), ("ACTIONBUTTON2", "", "")]]}


def generate(data, path, **overrides):
    args = {"pid": 42, "session_id": "s", "character_guid": "p", "now": 11.}
    return create_controller_cache(data, path, **{**args, **overrides})


def test_separate_cache_exact_keys_no_guessed_unbound_and_no_overwrite(tmp_path):
    original = tmp_path / "bindings-cache.wtf"
    original.write_text('bind "Q" "STRAFELEFT"')
    data = report()
    data["selected_cache"] = str(original)
    snapshot = deepcopy(data)
    first, second = generate(data, tmp_path), generate(data, tmp_path)
    assert first != second and first.is_file() and first.with_suffix(".json").is_file()
    cache = BindingsCache(first)
    assert cache.actions["MOVEFORWARD"] == ["W", "UP"]
    assert cache.resolve("JUMP") == "SPACE" and cache.resolve("TARGETNEARESTENEMY") == "TAB"
    assert not cache.contains("ACTIONBUTTON2")
    assert original.read_text() == 'bind "Q" "STRAFELEFT"' and data == snapshot


@pytest.mark.parametrize("changes", [{"complete": False}, {"pid": 43}, {"session_id": "old"},
    {"character_guid": "other"}, {"received_at": -50}, {"received_at": 100},
    {"count_expected": 5}, {"pages_received": 0}, {"source": "guessed"}])
def test_rejects_partial_stale_wrong_identity_without_creating_files(tmp_path, changes):
    with pytest.raises(BindingError): generate({**report(), **changes}, tmp_path)
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("bad", ["W\nbind X Y", 'W"', "W\\", "W\x00"])
def test_rejects_wtf_injection(tmp_path, bad):
    data = report()
    data["bindings"][0]["primary"] = bad
    with pytest.raises(BindingError): generate(data, tmp_path)


def test_rejects_conflicting_key_assignments(tmp_path):
    data = report()
    data["bindings"][1]["primary"] = "w"
    with pytest.raises(BindingError, match="binding"): generate(data, tmp_path)


def test_context_conflict_resolved_only_by_consistent_client_evidence(tmp_path):
    data = report()
    data["bindings"][0].update(action="ACTIONBUTTON1", primary="1", secondary="", normal_primary_action="ACTIONBUTTON1")
    data["bindings"][1].update(action="HOUSING_TOGGLEBASICDECORMODE", primary="1", normal_primary_action="ACTIONBUTTON1")
    result = BindingsCache(generate(data, tmp_path))
    assert result.resolve("ACTIONBUTTON1") == "1"
    assert not result.contains("HOUSING_TOGGLEBASICDECORMODE")
    data["bindings"][1]["normal_primary_action"] = "HOUSING_TOGGLEBASICDECORMODE"
    with pytest.raises(BindingError): generate(data, tmp_path)
