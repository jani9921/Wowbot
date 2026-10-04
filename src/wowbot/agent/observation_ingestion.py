"""Observation batching for the canonical agent tick."""
from __future__ import annotations

from dataclasses import dataclass

from .models import Observation


# Perception outputs stay in the WorldModel but are not appended to SQLite.
# WORLD3D_LOCAL_VIEW was missing here: live 2026-09-30 it wrote ~94 KB per
# perception update (raw detector batch, scene geometry, traversability),
# 316 MB in 25 minutes, and the per-tick commit held the agent thread in
# SQLite for more than half of all profiler samples.
EPHEMERAL_OBSERVATION_SOURCES = frozenset({
    "WORLD3D", "WORLD3D_LOCAL_VIEW", "UI_CV", "MINIMAP_CV", "WORLD_MAP_CV",
    "CROSS_VIEW", "CAMERA_CONTROL",
    # Per-tick projections of the same addon packet (live 2026-10-03: ~35k
    # rows each in 30 min, never trimmed; DB grew ~510 MB/h with a 2.2 GB WAL
    # and 13 s query latency).  The addon telemetry itself stays durable.
    "MOUSEOVER", "PLAYER_STATE", "UI_STATE", "WORLD_MAP_STATE", "ACTIVE_PERCEPTION",
})


@dataclass(frozen=True)
class IngestionResult:
    primary: Observation | None
    durable: tuple[Observation, ...]


class ObservationIngestion:
    """Creates and atomically ingests one observation batch; owns no policy."""

    @staticmethod
    def primary(payload: dict | None, now: float) -> Observation | None:
        return Observation.create(payload, now) if payload is not None else None

    @staticmethod
    def session_changed(current_session_id: str | None, primary: Observation | None) -> bool:
        return bool(primary is not None and current_session_id
                    and primary.session_id != current_session_id)

    @staticmethod
    def ingest(world, primary: Observation | None,
               supplemental: tuple[Observation, ...]) -> IngestionResult:
        durable: list[Observation] = []
        if primary is not None and world.ingest(primary, defer_rebuild=True):
            durable.append(primary)
        for observation in supplemental:
            if world.ingest(observation, defer_rebuild=True):
                if observation.source not in EPHEMERAL_OBSERVATION_SOURCES:
                    durable.append(observation)
        world.flush_pending()
        return IngestionResult(primary=primary, durable=tuple(durable))
