from wowbot.agent.models import Observation
from wowbot.agent.observation_ingestion import ObservationIngestion
from wowbot.agent.world import WorldModel


class FakeWorld:
    def __init__(self):
        self.ingested = []
        self.flushes = 0

    def ingest(self, observation, *, defer_rebuild=False):
        self.ingested.append((observation, defer_rebuild))
        return True

    def flush_pending(self):
        self.flushes += 1


def test_ingestion_batches_primary_and_supplemental_with_one_flush():
    world = FakeWorld()
    primary = Observation.create({"session_id": "s", "frame_id": "a"}, 1.)
    durable = Observation.create({"session_id": "s", "frame_id": "b"}, 1.1, "ADDON_EVENT")
    ephemeral = Observation.create({"session_id": "s", "frame_id": "c"}, 1.2, "WORLD3D")

    result = ObservationIngestion.ingest(world, primary, (durable, ephemeral))

    assert [item[0] for item in world.ingested] == [primary, durable, ephemeral]
    assert all(item[1] is True for item in world.ingested)
    assert world.flushes == 1
    assert result.durable == (primary, durable)


def test_ingestion_reports_session_transition_without_owning_reset_policy():
    primary = ObservationIngestion.primary({"session_id": "new", "frame_id": "a"}, 2.)

    assert ObservationIngestion.session_changed("old", primary) is True
    assert ObservationIngestion.session_changed("new", primary) is False
    assert ObservationIngestion.session_changed(None, primary) is False
    assert ObservationIngestion.session_changed("old", None) is False


def test_addon_only_fast_position_does_not_reclone_unchanged_visual_projection():
    world = WorldModel()
    full = Observation.create({
        "session_id": "s", "frame_id": "full:1", "timestamp": 1.,
        "transport_kind": "STATE", "position": {"x": .1, "y": .2},
    }, 1.)
    visual = Observation.create({
        "session_id": "s", "frame_id": "vision:1", "timestamp": 1.,
        "visual_candidates": [{"track_id": "t1", "source": "WORLD3D"}],
    }, 1., "WORLD3D")
    ObservationIngestion.ingest(world, full, (visual,))
    candidates = world.state["visual_candidates"]
    fast = Observation.create({
        "session_id": "s", "frame_id": "fast:2", "timestamp": 1.05,
        "transport_kind": "FAST", "telemetry_lane": "FAST_STATE",
        "position": {"x": .11, "y": .21},
        "player_world_position": {"x": 10., "y": 20.},
    }, 1.05)

    ObservationIngestion.ingest(world, fast, ())

    assert world.state["position"] == {"x": .11, "y": .21}
    assert world.state["player_world_position"] == {"x": 10., "y": 20.}
    assert world.state["visual_candidates"] is candidates
