"""Shared logical contracts must not supply missing authority or transport trust."""
from dataclasses import FrozenInstanceError
import json
import struct

import pytest

from test_packet_agent_bridge import addon, bridge, deliver
from test_packet_codecs import decoded
from test_packet_quest_credit_projection_20261025 import credit
from wowbot.context_contracts import ContextState, SessionContext, context_matches
from wowbot.agent.models import Observation
from wowbot.packetio.context import addon_context, addon_context_status, evaluate_addon_context
from wowbot.packetio.ipc import canonical, envelope


def test_logical_context_is_immutable_and_detached_from_legacy_dictionaries():
    wire = {**addon_context(addon(), 77), "runtime_id": "runtime", "context_id": "nonce"}
    context = SessionContext.from_mapping(wire)
    wire["character_guid"] = "other"
    exported = context.as_dict()
    exported["phase"] = "other"
    assert context.identity.character_guid == addon()["character_guid"]
    assert context.world.phase == "world"
    assert set(context.as_dict()) == {"selected_pid", "session_id", "character_guid", "game_build",
                                      "map_id", "instance_id", "phase"}
    assert json.loads(json.dumps(context.as_dict())) == context.as_dict()
    with pytest.raises(FrozenInstanceError):
        context.world.phase = "other"
    with pytest.raises(FrozenInstanceError):
        context.identity.selected_pid = 78


@pytest.mark.parametrize("field,value", [
    ("selected_pid", True), ("selected_pid", 0), ("selected_pid", "77"),
    ("session_id", []), ("session_id", 7), ("session_id", "  "),
    ("character_guid", {}), ("game_build", True), ("game_build", "69587"),
    ("instance_id", -1), ("instance_id", True), ("instance_id", "2175"),
    ("map_id", False), ("map_id", "1409"),
    ("phase", []), ("phase", {}), ("phase", True), ("phase", 1.5),
])
def test_malformed_identity_or_world_fields_never_match_even_themselves(field, value):
    bad = {**addon_context(addon(), 77), field: value}
    assert SessionContext.from_mapping(bad) is None
    assert not context_matches(bad, bad)


def test_unknown_phase_and_zero_world_map_remain_explicit():
    fields = {**addon_context(addon(), 77), "phase": None, "instance_id": 0, "map_id": 0}
    context = SessionContext.from_mapping(fields)
    assert context.world.phase is None and context.world.instance_id == context.world.ui_map_id == 0
    assert not context_matches(fields, {**fields, "phase": 0})
    scope = context.entity_scope()
    assert "map_id" not in scope and scope["phase"] is None
    assert SessionContext.from_mapping(scope).entity_scope() == scope
    assert not context_matches(None, None)


@pytest.mark.parametrize("change", [{"selected_pid": 78}, {"session_id": "next"},
    {"character_guid": "other"}, {"game_build": 70448}, {"instance_id": 2444}, {"phase": "other"}])
def test_entity_scope_never_crosses_an_identity_or_world_boundary(change):
    original = addon_context(addon(), 77)
    assert not context_matches(original, {**original, **change}, include_ui_map=False)
    assert not context_matches(original, {**original, **change})


def test_only_the_ui_map_can_change_inside_the_same_entity_scope():
    original = addon_context(addon(), 77)
    changed = {**original, "map_id": 84}
    assert context_matches(original, changed, include_ui_map=False)
    assert not context_matches(original, changed)


@pytest.mark.parametrize("change,state,reason,missing", [
    ({"map_id": None}, ContextState.PENDING, "waiting_for_addon_context", ("map_id",)),
    ({"player_world_position": {}}, ContextState.PENDING, "waiting_for_addon_context", ("player_world_position.instance_id",)),
    ({"loading": True}, ContextState.PENDING, "waiting_for_addon_context", ()),
    ({"player_present": False}, ContextState.PENDING, "waiting_for_addon_context", ()),
    ({"game_build": None}, ContextState.PENDING, "waiting_for_addon_context", ("game_build",)),
    ({"game_build": "69588"}, ContextState.MISMATCH, "unsupported_game_build", ()),
    ({"game_build": "invalid"}, ContextState.MISMATCH, "invalid_addon_context", ()),
    ({"phase": []}, ContextState.MISMATCH, "invalid_addon_context", ()),
    ({"map_id": True}, ContextState.MISMATCH, "invalid_addon_context", ()),
    ({"character_guid": 9}, ContextState.MISMATCH, "invalid_addon_context", ()),
    ({"player_world_position": [2175]}, ContextState.MISMATCH, "invalid_addon_context", ()),
])
def test_addon_facade_distinguishes_missing_context_from_malformed_context(change, state, reason, missing):
    payload = addon(**change)
    evaluation = evaluate_addon_context(payload)
    assert evaluation.state is state and evaluation.reason == reason
    assert evaluation.missing_fields == missing
    assert addon_context_status(payload) == reason
    assert addon_context(payload, 77) is None


def test_context_binds_only_the_explicit_valid_pid_and_preserves_unknown_phase():
    evaluation = evaluate_addon_context(addon(phase=None))
    assert evaluation.state is ContextState.VALID
    for pid in (None, True, 0, -1, "77"):
        assert evaluation.bind(pid) is None
    assert evaluation.bind(77).world.phase is None
    assert evaluation.bind(77).identity.selected_pid == 77


def test_runtime_uses_the_shared_context_without_churning_the_endpoint(bridge):
    typed = bridge.adapter.session_context
    wire = dict(bridge.adapter.context)
    assert typed.as_dict() == bridge.adapter.signature == addon_context(addon(), 77)
    assert bridge.adapter.observations(None, bridge.world, 10.) == ()
    assert bridge.adapter.session_context == typed and bridge.adapter.context == wire
    assert bridge.adapter.diagnostics()["context_state"] == "VALID"
    assert bridge.adapter.diagnostics()["missing_context_fields"] == []


def test_malformed_new_context_closes_the_old_packet_context(bridge):
    assert bridge.adapter.observations(addon(phase=[]), bridge.world, 10.) == ()
    assert bridge.adapter.session_context is None and bridge.adapter.context is None
    status = bridge.adapter.diagnostics()
    assert status["context_state"] == "MISMATCH" and status["status"] == "invalid_addon_context"
    endpoint = json.loads(bridge.path.read_text())
    assert endpoint["status"] == "inactive" and endpoint["context"] is None


def test_pending_context_diagnostics_name_the_missing_field(bridge):
    bridge.adapter.observations(addon(character_guid=None), bridge.world, 10.)
    status = bridge.adapter.diagnostics()
    assert status["context_state"] == "PENDING"
    assert status["missing_context_fields"] == ["character_guid"]


def test_equal_logical_identity_does_not_replace_the_authenticated_ipc_nonce(bridge):
    old = json.loads(bridge.path.read_text())
    bridge.adapter.observations(addon(loading=True), bridge.world, 10.)
    bridge.adapter.observations(None, bridge.world, 10.)
    new = json.loads(bridge.path.read_text())
    assert context_matches(old["context"], new["context"])
    assert old["context"]["context_id"] != new["context"]["context_id"]
    assert not bridge.inbox.ingest_datagram(canonical(envelope(decoded()[-1].to_dict(), old)))


def test_phase_transition_invalidates_credit_without_refreshing_addon_liveness(bridge):
    deliver(bridge, credit(3))
    assert bridge.world.state["packet_quest_credits"]["55639"]["182800"]["sampled_at"] == 10.
    assert bridge.world.last_received == 9.
    bridge.world.ingest(Observation.create(addon(frame_id="phase:credit", phase="other"), 10.1))
    assert not bridge.world.state.get("packet_quest_credits")
    bridge.world.ingest(Observation.create(addon(frame_id="phase:back"), 10.2))
    assert not bridge.world.state.get("packet_quest_credits")


@pytest.mark.parametrize("change", [{"phase": "other"}, {"player_world_position": {}}],
                         ids=["phase", "missing-world-context"])
def test_phase_transition_invalidates_server_map_even_without_any_entity(bridge, change):
    position = {**addon()["player_world_position"], "instance_id": 2444}
    state = addon(frame_id="cosmetic:world", player_world_position=position)
    bridge.world.ingest(Observation.create(state, 9.1))
    bridge.adapter.observations(None, bridge.world, 10.)
    body = struct.pack("<iffffiiI", 2534, 1., 2., 3., 1.5, -1, 2, 7)
    deliver(bridge, decoded("SMSG_NEW_WORLD", body)[-1])
    assert bridge.world.state["packet_server_map"]["map_id"] == 2534
    bridge.world.ingest(Observation.create({**state, "frame_id": "phase:new", **change}, 10.1))
    assert not bridge.world.state.get("packet_server_map")
    bridge.world.ingest(Observation.create({**state, "frame_id": "phase:back"}, 10.2))
    assert not bridge.world.state.get("packet_server_map")


def test_new_entity_scope_does_not_mix_the_previous_phases_map_samples():
    from types import SimpleNamespace
    from test_cosmetic_map_entities_20261027 import CONTEXT, NECKSNAPPER, with_map
    from wowbot.agent.world_packet_reducer import _remember_entity

    model = SimpleNamespace()
    _remember_entity(model, "ENTITY_CREATED", NECKSNAPPER, 10., CONTEXT)
    body = {**NECKSNAPPER, "entity_guid": with_map(NECKSNAPPER["entity_guid"], 2444)}
    _remember_entity(model, "ENTITY_CREATED", body, 11., {**CONTEXT, "phase": "next"})
    assert list(model._entity_raw_maps) == [(2444, 11.)]
    assert len(model._packet_entities) == 1
