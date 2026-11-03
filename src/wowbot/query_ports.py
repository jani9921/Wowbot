"""Small, read-only query contracts shared across domain boundaries.

Providers are injected into their consumers, never placed in world data or
stored in module globals. Queries cannot execute movement/input. Navigation
may retain its own planning caches and sweep progress behind these ports.
"""
from __future__ import annotations

from collections.abc import Hashable
from dataclasses import dataclass
from typing import Any, Protocol


class QuestObjectiveGeometryPort(Protocol):
    """Scoped, owned geometry for one normalized objective; never an action."""

    def __call__(self, quest_id: int | str, objective: Any,
                 now: float | None = None) -> tuple[dict[str, Any], ...]: ...


class TravelCostPort(Protocol):
    """Walking length for this owner's context, or None if no route is known."""

    def __call__(self, state: dict[str, Any], destination: dict[str, Any]) -> float | None: ...


class PlayerLayerPort(Protocol):
    """Resolved player-floor height, or None when unavailable."""

    def __call__(self, state: dict[str, Any]) -> float | None: ...


class LowerLayerPort(Protocol):
    """A reachable lower-floor point, or None; never a movement command."""

    def __call__(self, state: dict[str, Any], destination: dict[str, Any]) -> dict[str, Any] | None: ...


class ZoneSweepPort(Protocol):
    """Navigation-owned sweep's next point; None also covers a finished sweep."""

    def __call__(self, state: dict[str, Any], destination: dict[str, Any], key: Hashable) -> dict[str, Any] | None: ...


class HostileUnitsPort(Protocol):
    """Planning threat candidates near a point, not combat/input authority."""

    def __call__(self, state: dict[str, Any], center: dict[str, Any], radius: float = 60.) -> list[dict[str, Any]]: ...


class FlightDeparturePort(Protocol):
    """A geometry-proven walking leg to open sky, or None when unproven."""

    def __call__(self, parameters: dict[str, Any], state: dict[str, Any]) -> dict[str, Any] | None: ...


@dataclass(frozen=True, slots=True)
class NavigationQueryPorts:
    """Capabilities of one navigation owner, held only by planning consumers.

    This bundle has no routing/input methods or independent state. The
    existing TravelCostPort is still supplied explicitly for compatibility.
    """

    player_layer: PlayerLayerPort | None = None
    lower_layer: LowerLayerPort | None = None
    zone_sweep: ZoneSweepPort | None = None
    hostile_units: HostileUnitsPort | None = None
    flight_departure_walk: FlightDeparturePort | None = None
