"""V4-009 wiring: WorldQuery.evidence_freshness()."""
from wowbot.agent.evidence_freshness import FreshnessTier
from wowbot.agent.models import Observation
from wowbot.agent.world import WorldModel


def _observation(source="WORLD3D", received_at=100.0):
    return Observation.create({"session_id": "session-1"}, received_at, source)


def test_no_evidence_for_key_returns_none_not_expired():
    world = WorldModel()
    assert world.query.evidence_freshness("unknown_key", now=100.0) is None


def test_fresh_world3d_evidence_classifies_as_fresh():
    world = WorldModel()
    world.add_evidence("some_key", {"x": 1}, _observation(received_at=100.0))
    assert world.query.evidence_freshness("some_key", now=100.1) is FreshnessTier.FRESH


def test_old_world3d_evidence_classifies_as_expired():
    world = WorldModel()
    world.add_evidence("some_key", {"x": 1}, _observation(received_at=100.0))
    assert world.query.evidence_freshness("some_key", now=110.0) is FreshnessTier.EXPIRED
