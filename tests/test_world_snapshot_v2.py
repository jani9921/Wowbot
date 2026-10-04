import pytest

from wowbot.agent.models import Observation, Proposal
from wowbot.agent.world import Fact, SensorHealth, WorldModel, WorldQuery as PublicWorldQuery, WorldSnapshot
from wowbot.agent.world_query import WorldQuery
from test_agent_core import agent, state


def test_fact_freshness_uses_monotonic_time():
    fact = Fact("value", 10., 1_700_000_000., "obs", "ADDON_TELEMETRY", 1., 3)
    assert fact.age(10.75) == .75
    assert fact.is_fresh(10.75, 1.) is True
    assert fact.is_fresh(12., 1.) is False
    assert fact.is_fresh(9., 1.) is False


def test_world_model_constructs_the_extracted_read_only_query_boundary():
    """Planner-facing reads have one active implementation outside reducer code."""
    assert PublicWorldQuery is WorldQuery
    assert isinstance(WorldModel().query, WorldQuery)


def test_world_snapshot_has_source_revisions_health_and_stable_top_level_state():
    model = WorldModel()
    first = state(1, health=100, movement={"speed": 0., "moving": False})
    model.ingest(Observation.create(first, 1.))
    model.ingest(Observation.create({
        "session_id": first["session_id"], "timestamp": 1.1, "frame_id": "world3d:1",
        "visual_candidates": [{"source": "WORLD3D", "track_id": "WORLD3D:1",
                               "x": .5, "y": .5, "confidence": .8}],
    }, 1.1, "WORLD3D"))
    snapshot = model.planning_snapshot(1.2)

    assert snapshot.revision == 2
    assert snapshot.source_revisions["ADDON_TELEMETRY"] == 1
    assert snapshot.source_revisions["WORLD3D"] == 1
    assert snapshot.sensor_health["ADDON_TELEMETRY"]["status"] == SensorHealth.HEALTHY
    assert snapshot.player.value["health"] == 100
    assert snapshot.world3d_tracks.value[0]["track_id"] == "WORLD3D:1"
    with pytest.raises(TypeError):
        snapshot.state["health"] = 50

    model.ingest(Observation.create(state(2, health=50), 2.))
    assert snapshot.state["health"] == 100
    assert model.planning_snapshot(2.).revision == 3


def test_planner_receives_world_snapshot_boundary():
    value, _ = agent()
    received = []

    def candidates(goal, world, now):
        received.append(world)
        return [Proposal.make("WAIT", "snapshot boundary test")]

    value.planner.candidates = candidates
    value.tick(state(1), 1.)

    assert len(received) == 1
    assert isinstance(received[0], WorldSnapshot)
