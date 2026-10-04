from dataclasses import asdict
import json
from pathlib import Path

from wowbot.agent.models import Observation
from wowbot.agent.soft_targeting import observe_soft_targets, use_as_candidate_hint
from wowbot.agent.world import WorldModel


ROOT = Path(__file__).parents[1]


def sample():
    return [{
        "source_unit": "softinteract", "guid": "Creature-0-1-2-3-166709-1",
        "npc_id": 166709, "name": "Lady Jaina Proudmoore", "unit_type": "NPC",
        "is_attackable": False, "is_dead": False,
        "evidence_role": "CANDIDATE_HINT", "confirmed": False,
    }]


def test_soft_target_is_bounded_unknown_evidence_not_canonical_target():
    hints = observe_soft_targets(sample() * 4)
    assert len(hints) == 1
    hint = hints[0]
    assert hint.evidence_role == "CANDIDATE_HINT"
    assert hint.confirmed is False
    assert hint.semantic_type == "UNKNOWN"
    assert hint.confidence < 1.
    assert observe_soft_targets([{"source_unit": "target", "guid": "bad"}]) == ()


def test_soft_target_only_supports_an_existing_candidate():
    hints = observe_soft_targets(sample())
    match = use_as_candidate_hint(hints, {"guid": sample()[0]["guid"]})
    assert match is not None
    assert match.reasons == ("exact_guid",)
    assert match.confirmed is False
    assert match.semantic_type == "UNKNOWN"
    assert use_as_candidate_hint(hints, {"name": "Unrelated Rock"}) is None


def test_full_and_fast_addon_observations_reach_the_read_only_query():
    model = WorldModel()
    full = Observation.create({"session_id": "s", "timestamp": 1., "soft_targets": sample()}, 1.)
    assert model.ingest(full)
    assert asdict(model.query.soft_target_hints()[0])["npc_id"] == 166709
    assert model.query.target() == {}

    fast_value = [{**sample()[0], "source_unit": "softenemy", "name": "Murloc", "guid": "Creature-2"}]
    fast = Observation.create({
        "session_id": "s", "timestamp": 2., "transport_kind": "FAST",
        "soft_targets": fast_value,
    }, 2.)
    assert model.ingest(fast)
    assert model.query.soft_target_hints()[0].name == "Murloc"
    evidence_value = json.loads(model.evidence["soft_targets"][-1].value_json)
    assert evidence_value[0]["source_unit"] == "softenemy"


def test_addon_exports_candidate_only_soft_tokens_on_full_and_fast_lanes():
    for package in ("AIPlayerControllerExport", "AIPlayerControllerExport-12.1.0"):
        source = (ROOT / "addon" / package / "AIPlayerControllerExport.lua").read_text(encoding="utf-8")
        transport = (ROOT / "addon" / package / "Transport.lua").read_text(encoding="utf-8")
        for token in ("softenemy", "softfriend", "softinteract"):
            assert token in source
        assert "soft_targets = readSoftTargets()," in source
        assert "result.soft_targets = readSoftTargets()" in source
        assert 'evidence_role = "CANDIDATE_HINT"' in source
        assert "confirmed = false" in source
        assert "soft_targets=compactSoftTargets(sample.soft_targets)" in transport


def test_soft_target_helper_has_no_planning_or_input_authority():
    source = (ROOT / "src" / "wowbot" / "agent" / "soft_targeting.py").read_text(encoding="utf-8")
    for forbidden in ("Proposal(", "InputExecutor", ".execute(", ".dispatch(", "selected_target"):
        assert forbidden not in source
