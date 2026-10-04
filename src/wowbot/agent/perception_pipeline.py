"""Surface orchestration for perception without owning detector semantics."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


Processor = Callable[[tuple[bytes, int, int], float, dict], list[Any]]


@dataclass(frozen=True, slots=True)
class PerceptionBatch:
    surface: str
    observed_at: float
    observations: tuple[Any, ...]
    metadata: dict[str, Any] = field(default_factory=dict)


class PerceptionPipeline:
    """One orchestration seam over the existing surface authorities.

    Detectors retain ownership of detection and trackers retain identity.  This
    class only selects the visible surface, normalizes batches, and publishes
    through an explicitly supplied sink.
    """

    def __init__(self, *, world3d: Processor, minimap: Processor,
                 world_map: Processor, ui: Processor | None = None) -> None:
        self._world3d = world3d
        self._minimap = minimap
        self._world_map = world_map
        self._ui = ui or (lambda frame, at, geometry: [])

    @staticmethod
    def _batch(surface: str, observed_at: float, values: list[Any], **metadata) -> PerceptionBatch:
        return PerceptionBatch(surface, observed_at, tuple(values), dict(metadata))

    def process_world3d(self, frame, observed_at: float, geometry: dict) -> list[Any]:
        return self._world3d(frame, observed_at, geometry)

    def process_minimap(self, frame, observed_at: float, geometry: dict) -> list[Any]:
        return self._minimap(frame, observed_at, geometry)

    def process_world_map(self, frame, observed_at: float, geometry: dict) -> list[Any]:
        return self._world_map(frame, observed_at, geometry)

    def process_ui(self, frame, observed_at: float, geometry: dict) -> list[Any]:
        return self._ui(frame, observed_at, geometry)

    def process_frame(self, frame, observed_at: float, geometry: dict) -> tuple[PerceptionBatch, ...]:
        map_open = bool(geometry.get("world_map_open"))
        primary = (self.process_world_map(frame, observed_at, geometry) if map_open
                   else self.process_world3d(frame, observed_at, geometry))
        batches = [self._batch("WORLD_MAP" if map_open else "WORLD3D", observed_at, primary)]
        if not map_open and geometry.get("visible"):
            batches.append(self._batch("MINIMAP", observed_at,
                                       self.process_minimap(frame, observed_at, geometry)))
        batches.append(self._batch("UI", observed_at, self.process_ui(frame, observed_at, geometry)))
        return tuple(batches)

    @staticmethod
    def fuse(batch: PerceptionBatch, normalizer: Callable[[Any], Any] | None = None) -> PerceptionBatch:
        if normalizer is None:
            return batch
        return PerceptionBatch(batch.surface, batch.observed_at,
                               tuple(normalizer(item) for item in batch.observations), batch.metadata)

    @staticmethod
    def publish(batch: PerceptionBatch, sink: Callable[[PerceptionBatch], Any]) -> Any:
        return sink(batch)
