
from __future__ import annotations

from dataclasses import dataclass, field
from math import hypot
from typing import Iterable


@dataclass(frozen=True)
class PathSample:
    x: float
    y: float
    timestamp: float


@dataclass
class PathTrace:
    context_id: str
    edge_id: str | None = None
    min_spacing: float = 0.003
    max_samples: int = 2000
    samples: list[PathSample] = field(default_factory=list)

    def add(self, x: float, y: float, timestamp: float) -> bool:
        if not self.samples:
            self.samples.append(PathSample(x, y, timestamp))
            return True
        last = self.samples[-1]
        if hypot(x - last.x, y - last.y) < self.min_spacing:
            return False
        if len(self.samples) >= self.max_samples:
            self.samples.pop(0)
        self.samples.append(PathSample(x, y, timestamp))
        return True

    @property
    def length(self) -> float:
        return sum(
            hypot(b.x - a.x, b.y - a.y)
            for a, b in zip(self.samples, self.samples[1:])
        )

    def as_points(self) -> list[tuple[float, float]]:
        return [(s.x, s.y) for s in self.samples]


def sample_path(
    positions: Iterable[tuple[float, float, float]],
    *,
    context_id: str,
    edge_id: str | None = None,
    min_spacing: float = 0.003,
) -> PathTrace:
    trace = PathTrace(context_id=context_id, edge_id=edge_id, min_spacing=min_spacing)
    for x, y, timestamp in positions:
        trace.add(x, y, timestamp)
    return trace
