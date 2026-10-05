"""NavigationService search regions, walkable points, destination permits and topology feedback.

Split out of service.py (2026-10-05); unchanged.
"""
from __future__ import annotations
from wowbot.agent.models import number


class NavigationSearchMixin:
    """Methods of NavigationService (service.py); moved verbatim."""

    def permits(self, world, destination: dict, now: float) -> bool:
        self._danger.observe_hostiles(world.state, now)
        if not self._danger.permits(destination["x"], destination["y"], now,
                                    avoid_combat=bool(destination.get("avoid_combat")),
                                    allow_combat=bool(destination.get("allow_combat")),
                                    exempt_entity_id=str(destination.get("target_guid") or "") or None):
            return False
        return self._routes.permits(world, destination, now)

    def retry_at(self, world, destination: dict, now: float) -> float | None:
        return self._routes.retry_at(world, destination, now)

    def report_entity_failure(self, entity_id: str | None, reason: str, now: float) -> None:
        if entity_id:
            self._reachability.report_failure(str(entity_id), reason, now)

    def report_entity_success(self, entity_id: str | None, now: float) -> None:
        if entity_id:
            self._reachability.report_success(str(entity_id), now)

    def begin_search_region(self, region_id: str, region: dict) -> None:
        self._search_coverage.begin(region_id, region)

    def observe_search_region(self, region_id: str, state: dict, now: float, *, target_detected: bool) -> None:
        region = (self._search_coverage.snapshot().get(str(region_id), {}).get("region") or {})
        position = ((state.get("player_world_position") or {})
                    if region.get("coordinate_space") == "WORLD_YARDS"
                    else (state.get("position") or {}))
        self._search_coverage.observe(region_id, player_x=number(position.get("x")),
                                      player_y=number(position.get("y")),
                                      target_detected=target_detected, now=now)

    def mark_search_cell_visited(self, region_id: str, cell_id: str, now: float) -> None:
        self._search_coverage.mark_visited(region_id, cell_id, now)

    def search_region_completed(self, region_id: str) -> bool | None:
        return self._search_coverage.completed(region_id)

    def walkable_point(self, instance_id: int, point: dict, *,
                       z_hint: float | None = None) -> dict | None:
        """Project world X/Y onto the configured mmap surface (None = off-mesh).

        Without a configured navmesh nothing is walkable: exploration must not
        invent destinations the route contract would reject anyway.
        """
        projector = getattr(self._navmesh, "project_position", None)
        if not callable(projector):
            return None
        try:
            projected = projector(int(instance_id), dict(point), z_hint=z_hint)
        except Exception:  # noqa: BLE001 -- a bad tile must not stop planning
            return None
        # project_position falls back to the *nearest* polygon; only a point
        # actually contained by a walkable polygon is an exploration target.
        diagnostics = getattr(self._navmesh, "last_surface_projection", None) or {}
        if projected is None or int(diagnostics.get("contained_candidates") or 0) <= 0:
            return None
        return projected

    def next_search_waypoint(self, region_id: str, state: dict) -> dict | None:
        region = (self._search_coverage.snapshot().get(str(region_id), {}).get("region") or {})
        position = ((state.get("player_world_position") or {})
                    if region.get("coordinate_space") == "WORLD_YARDS"
                    else (state.get("position") or {}))
        return self._search_coverage.next_waypoint(region_id, player_x=number(position.get("x")),
                                                   player_y=number(position.get("y")))

    def waypoint(self, world, destination: dict) -> dict:
        return self._routes.waypoint(world, destination)

    def observe_verified_move(self, before: dict, after: dict, destination: dict | None = None) -> None:
        self._routes.observe_verified_move(before, after, destination)

    def observe_failed_move(self, before: dict, after: dict, destination: dict,
                            observation_id: str, now: float):
        return self._routes.observe_failed_move(before, after, destination, observation_id, now)

    def observe_topology(self, state: dict, observation_id: str, now: float) -> list[dict]:
        return self._routes.observe_topology(state, observation_id, now)
