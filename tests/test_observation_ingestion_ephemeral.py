from wowbot.agent.observation_ingestion import EPHEMERAL_OBSERVATION_SOURCES, ObservationIngestion


class _World:
    def ingest(self, observation, defer_rebuild=False):
        return True

    def flush_pending(self):
        pass


class _Observation:
    def __init__(self, source):
        self.source = source


def test_world3d_local_view_stays_in_world_model_but_is_not_persisted():
    """Live 2026-09-30: ~94 KB per update, 316 MB in 25 minutes of SQLite commits."""
    assert "WORLD3D_LOCAL_VIEW" in EPHEMERAL_OBSERVATION_SOURCES
    local_view, addon = _Observation("WORLD3D_LOCAL_VIEW"), _Observation("ADDON_TELEMETRY")
    result = ObservationIngestion.ingest(_World(), None, (local_view, addon))
    assert result.durable == (addon,)


def test_per_tick_addon_projections_are_not_persisted():
    """Live 2026-10-03: MOUSEOVER/PLAYER_STATE/UI_STATE/WORLD_MAP_STATE/
    ACTIVE_PERCEPTION copies of every packet grew the DB ~510 MB/h."""
    projections = tuple(_Observation(source) for source in (
        "MOUSEOVER", "PLAYER_STATE", "UI_STATE", "WORLD_MAP_STATE", "ACTIVE_PERCEPTION"))
    assert ObservationIngestion.ingest(_World(), None, projections).durable == ()
