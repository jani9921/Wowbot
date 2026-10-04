"""Perf fix: canonical() skips the recursive _json_safe rebuild for the
common (all-finite) case but must produce identical output either way."""
import math

from wowbot.agent.models import canonical


def test_canonical_matches_plain_json_dumps_for_ordinary_values():
    value = {"b": 1, "a": [1, 2.5, "x", None, True], "nested": {"z": 1, "y": 2}}
    assert canonical(value) == '{"a":[1,2.5,"x",null,true],"b":1,"nested":{"y":2,"z":1}}'


def test_canonical_sanitizes_non_finite_floats_to_null():
    value = {"a": float("inf"), "b": float("-inf"), "c": float("nan"), "d": 1.5}
    assert canonical(value) == '{"a":null,"b":null,"c":null,"d":1.5}'


def test_canonical_sanitizes_non_finite_floats_inside_nested_lists_and_dicts():
    value = {"items": [{"x": float("nan")}, {"x": 2.0}], "y": [float("inf"), 3]}
    assert canonical(value) == '{"items":[{"x":null},{"x":2.0}],"y":[null,3]}'


def test_canonical_is_deterministic_regardless_of_key_insertion_order():
    a = {"b": 1, "a": 2}
    b = {"a": 2, "b": 1}
    assert canonical(a) == canonical(b)


def test_canonical_handles_top_level_non_finite_float():
    assert canonical(float("nan")) == "null"
    assert canonical(float("inf")) == "null"


def test_canonical_round_trips_a_realistic_evidence_context():
    context = {"session_id": "s1", "map_id": 1609, "surface": None,
              "position": {"x": .5, "y": math.inf}}
    assert canonical(context) == canonical({
        "session_id": "s1", "map_id": 1609, "surface": None,
        "position": {"x": .5, "y": None}})
