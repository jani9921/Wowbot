"""Contract compatibility, bounded provenance and actual packet sample times."""
from dataclasses import FrozenInstanceError, replace
import json
import math

import pytest

from test_evidence_lineage_20261029 import claim, evidence
from test_packet_agent_bridge import bridge, deliver
from test_packet_codecs import decoded
from wowbot.agent.models import Observation
from wowbot.agent.world import Evidence as WorldEvidence, WorldModel
from wowbot.agent.world_models import Evidence as LegacyEvidence
from wowbot.evidence_contracts import (
    Evidence, EvidenceCompleteness, EvidenceDirection, EvidenceValidity, SourceLineage,
)


def test_existing_evidence_imports_are_the_common_contract_and_keep_positional_arguments():
    assert Evidence is WorldEvidence is LegacyEvidence
    value = evidence()
    assert value.at == value.received_at == value.observed_at == 10.
    assert value.expires == value.expires_at == 12.
    assert value.completeness is EvidenceCompleteness.UNKNOWN
    assert value.session_context is None


@pytest.mark.parametrize("now,status", [(9., "FUTURE"), (10., "VALID"), (12., "VALID"),
    (12.001, "EXPIRED"), (math.nan, "INVALID"), (math.inf, "INVALID"), (True, "INVALID")])
def test_time_status_never_treats_future_or_nonfinite_as_fresh(now, status):
    value = evidence()
    assert value.validity(now).value == status
    assert value.is_fresh(now) is (status == "VALID")
    if status != "VALID":
        assert value.effective_confidence(now) == 0.


def test_sample_and_receipt_are_separate_and_invalid_windows_stay_invalid():
    value = evidence(at=2., sampled_at_monotonic=1., expires=3.)
    assert value.age_ms(2.) == 1000
    assert value.validity(1.5) is EvidenceValidity.FUTURE
    assert value.is_fresh(2.)
    assert evidence(expires=9.).validity(5.) is EvidenceValidity.INVALID
    assert evidence(sampled_at_monotonic=11.).validity(11.) is EvidenceValidity.INVALID


@pytest.mark.parametrize("sample", ["nan", math.nan, math.inf, True, None, 11.])
def test_bad_declared_sample_time_does_not_silently_become_receipt_time(sample):
    world = WorldModel()
    claim(world, "bad-clock", at=10., provenance={"observed_at_monotonic": sample})
    assert world.belief("claim", 10.)["value"] is None


def test_different_claims_of_one_observation_have_different_evidence_ids():
    assert evidence(kind="health").evidence_id != evidence(kind="target").evidence_id


def test_lineage_and_evidence_are_immutable_but_values_are_independent_json_copies():
    lineage = SourceLineage(parent_observation_ids=("parent",), root_observation_ids=("root",))
    value = evidence(value_json='{"items":[1]}', lineage=lineage)
    decoded_value = value.value
    decoded_value["items"].append(2)
    assert value.value == {"items": [1]}
    with pytest.raises(FrozenInstanceError):
        lineage.root_observation_ids = ("other",)
    with pytest.raises(ValueError):
        SourceLineage(root_observation_ids=["mutable"])
    with pytest.raises(ValueError):
        replace(value, lineage={"mutable": True})


@pytest.mark.parametrize("declared,expected", [(None, "UNKNOWN"), ("PARTIAL", "PARTIAL"),
    ("COMPLETE", "COMPLETE"), (True, "UNKNOWN"), ("invalid", "UNKNOWN")])
def test_empty_lists_do_not_invent_completeness(declared, expected):
    world = WorldModel()
    claim(world, "empty", [], provenance={} if declared is None else {"completeness": declared})
    record, = world.query.evidence("claim", 1.)
    assert record.completeness.value == expected
    assert world.belief("claim", 1.)["evidence_hierarchy"][0]["completeness"] == expected


def test_parent_and_grandparent_aliases_preserve_the_original_root_and_sample():
    world = WorldModel()
    root = claim(world, "root", at=1.)
    parent = claim(world, "parent", at=2., provenance={"parent_observation_id": root.observation_id})
    claim(world, "child", at=3., provenance={"parent_observation_id": parent.observation_id})
    entries = world.query.evidence("claim", 3.)
    assert entries[-1].lineage.root_observation_ids == (root.observation_id,)
    assert entries[-1].observed_at == 1.
    assert len(world.belief("claim", 3.)["evidence"]) == 1


def test_a_late_copy_cannot_override_a_known_origin_with_a_newer_timestamp():
    world = WorldModel()
    root = claim(world, "root", at=1.)
    claim(world, "late", at=10., provenance={"root_observation_ids": [root.observation_id],
          "observed_at_monotonic": 10.})
    assert world.belief("claim", 10.)["value"] is None
    assert world.query.evidence("claim", 10.) == ()
    assert len(world.query.evidence("claim", 10., include_inactive=True)) == 2


def test_partial_or_malformed_lineage_is_bounded_and_cannot_raise_independent_support():
    world = WorldModel()
    for index in range(3):
        claim(world, str(index), provenance={"root_observation_ids": [f"{index}:{j}" for j in range(65)]})
    entries = world.query.evidence("claim", 1.)
    assert all(len(e.lineage.root_observation_ids) == 64 and e.lineage.correlation_uncertain for e in entries)
    belief = world.belief("claim", 1.)
    assert len(belief["evidence"]) == 1 and belief["sensor_tier"] == "PERCEPTION"
    assert belief["provenance"]["lineage_truncated"] is True


def test_provenance_projection_copies_only_the_named_metadata_fields():
    world = WorldModel()
    claim(world, "safe", provenance={"producer": "test", "ipc_key": "FAKE_SECRET", "raw_payload": "FAKE_RAW"})
    record, = world.query.evidence("claim", 1.)
    projected = json.dumps(record.lineage.as_dict())
    assert "FAKE_SECRET" not in projected and "FAKE_RAW" not in projected
    assert json.dumps(world.belief("claim", 1.))


def test_packet_evidence_keeps_direction_scope_and_real_sample_age_without_double_subtraction(bridge):
    deliver(bridge, decoded(timestamp=999.6)[-1])
    record = next(e for e in bridge.world.query.evidence("player_world_position", 10.)
                  if e.source == "PACKET_TELEMETRY")
    assert record.observed_at == pytest.approx(9.6) and record.received_at == 10.
    assert record.expires_at == pytest.approx(10.35)
    assert record.age_ms(10.) == 400
    assert record.lineage.direction is EvidenceDirection.CLIENT_TO_SERVER
    assert record.lineage.event_id and record.lineage.game_build == 69587 and record.lineage.payload_layout
    assert record.session_context.identity.selected_pid == 77
    assert record.session_context.world.instance_id == 2175
    assert record.session_context.world.ui_map_id == 1409
    assert record.is_fresh(10.3) and not record.is_fresh(10.36)
    assert bridge.world.last_received == 9.  # receipt does not grant addon/input liveness


def test_pruning_retains_not_yet_received_data_but_drops_expired_and_invalid_records():
    world = WorldModel()
    claim(world, "future", at=10.)
    assert world.prune_expired_evidence(1.) == 0
    assert world.prune_expired_evidence(math.nan) == 0
    assert world.prune_expired_evidence(20.) == 1


def test_independent_origins_remain_independent_without_promoting_named_identity_to_truth():
    world = WorldModel()
    for index in range(3):
        claim(world, f"capture:{index}", provenance={"root_observation_ids": [f"source:{index}"]})
    belief = world.belief("claim", 1.)
    assert len(belief["evidence"]) == 3
    assert belief["sensor_tier"] == "STRONG" and belief["status"] == "SUPPORTED"


def test_a_correlated_copy_does_not_replace_the_existing_source_priority():
    world = WorldModel()
    root = claim(world, "parent", "current", source="ADDON_TELEMETRY")
    claim(world, "derived", "guess", source="WORLD3D", provenance={
        "root_observation_ids": [root.observation_id]})
    belief = world.belief("claim", 1.)
    assert belief["source"] == "ADDON_TELEMETRY" and belief["value"] == "current"
    assert belief["evidence"] == [root.observation_id]


def test_ancestry_bridge_merges_components_in_every_ingestion_order():
    from itertools import permutations
    from wowbot.evidence_contracts import independent_evidence

    roots = (("A",), ("B",), ("C",), ("A", "B", "C"))
    records = [evidence(observation_id=f"obs:{index}", independence_group=f"group:{index}",
                       lineage=SourceLineage(root_observation_ids=origins)) for index, origins in enumerate(roots)]
    assert all(len(independent_evidence(order)) == 1 for order in permutations(records))


@pytest.mark.parametrize("bad", [{"root_observation_ids": "wrong"}, {"parent_observation_ids": [None]},
    {"independence_group": ["not-an-ID"]}, {"parent_observation_id": True}])
def test_malformed_lineage_cannot_masquerade_as_independent_copies(bad):
    world = WorldModel()
    for index in range(3):
        claim(world, f"malformed:{index}", provenance=bad)
    assert all(e.lineage.correlation_uncertain for e in world.query.evidence("claim", 1.))
    assert len(world.belief("claim", 1.)["evidence"]) == 1


@pytest.mark.parametrize("bad_time", [True, 11., math.inf])
def test_invalid_parent_time_cannot_be_laundered_by_a_new_child_timestamp(bad_time):
    world = WorldModel()
    parent = claim(world, "bad-parent", at=1., provenance={"observed_at_monotonic": bad_time})
    claim(world, "child", at=2., provenance={"parent_observation_id": parent.observation_id,
          "observed_at_monotonic": 2.})
    assert world.belief("claim", 2.)["value"] is None
    assert world.query.evidence("claim", 2., include_inactive=True)[-1].invalid_reason == "INVALID_ANCESTOR"


def test_query_returns_records_without_mutating_the_world_or_granting_input_authority():
    world = WorldModel()
    obs = claim(world, "passive", {"guid": "candidate"})
    before = dict(world.state)
    query = world.query.evidence("claim", 1.)
    assert isinstance(query, tuple) and query[0].observation_id == obs.observation_id
    query[0].value["guid"] = "changed copy"
    assert query[0].value == {"guid": "candidate"}
    assert world.state == before and world.last_received == 0.


def test_sibling_sources_keep_the_original_addon_time_and_identity_group():
    from test_agent_core import state

    world = WorldModel()
    parent = Observation.create(state(mouseover={"guid": "npc"}), 1.)
    world.ingest(parent)
    derived = Observation.create({"session_id": world.session_id, "timestamp": 1.,
        "frame_id": parent.correlation_id, "mouseover": {"guid": "npc"},
        "provenance": {"producer": "AIPlayerControllerExport", "parent_observation_id": parent.observation_id,
          "root_observation_ids": [parent.observation_id], "observed_at_monotonic": 1.,
          "independence_group": parent.observation_id}}, 1.2, "MOUSEOVER")
    assert world.ingest(derived)
    records = world.query.evidence("mouseover", 1.2)
    assert records[-1].received_at == 1.2 and records[-1].observed_at == 1.
    assert len(world.belief("mouseover", 1.2)["evidence"]) == 1
    assert world.last_received == 1.


def test_a_child_preserves_the_known_parents_uncertain_ancestry():
    world = WorldModel()
    parent = claim(world, "partial-parent", provenance={"root_observation_ids": [None]})
    claim(world, "partial-child", at=2., provenance={"parent_observation_id": parent.observation_id})
    assert world.query.evidence("claim", 2.)[-1].lineage.correlation_uncertain is True


def test_diagnostic_view_does_not_repeat_the_full_ancestry_for_every_vote():
    world = WorldModel()
    for index in range(3):
        claim(world, f"sample:{index}", provenance={"root_observation_ids": [f"root:{index}"]})
    belief = world.belief("claim", 1.)
    assert len(belief["evidence_hierarchy"]) == 3
    assert all("provenance" not in row for row in belief["evidence_hierarchy"])
    assert belief["provenance"]["root_observation_ids"]
    assert {root for entry in world.query.evidence("claim", 1.) for root in entry.lineage.root_observation_ids} == {
        "root:0", "root:1", "root:2"}
