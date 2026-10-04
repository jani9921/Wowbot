from __future__ import annotations

from dataclasses import dataclass
import time

from wowbot.vision.models import NavigationVisionObservation, WorldPosition
from .arrival import ArrivalVerifier
from .graph import NavGraph
from .local import LocalNavigator
from .memory import NavigationMemory
from .learning import LearningPolicy
from .models import DestinationIntent, MovementIntent, NavigationPlan, NavigationStatus
from .planner import RoutePlanner, NoRouteError
from .progress import ProgressMonitor
from .state_machine import NavigationStateMachine


@dataclass(frozen=True, slots=True)
class NavigationTick:
    status: NavigationStatus
    movement_intent: MovementIntent | None
    route_revision: int
    reason: str


class NavigationEngine:
    """Single navigation authority: route, progress, replanning and arrival lifecycle."""

    def __init__(self, *, graph: NavGraph, memory: NavigationMemory | None = None) -> None:
        self.graph = graph
        self.memory = memory
        self.learning = LearningPolicy(memory) if memory is not None else None
        self.state = NavigationStateMachine()
        self.local = LocalNavigator()
        self.arrival = ArrivalVerifier()
        self.progress = ProgressMonitor()
        self.plan: NavigationPlan | None = None
        self.route_id: str | None = None
        self.started_at: float | None = None
        self.replans = 0
        self.stuck_events = 0

    def start(self, destination: DestinationIntent, position: WorldPosition) -> NavigationPlan:
        self.arrival.reset()
        self.state.transition(NavigationStatus.RESOLVING)
        self.state.transition(NavigationStatus.ROUTING)
        if destination.position is None:
            self.state.transition(NavigationStatus.FAILED)
            raise NoRouteError("zone-only destinations require a resolver before routing")
        route = RoutePlanner(self.graph, learning=self.learning).plan(position, destination.position)
        self.plan = NavigationPlan(destination, list(route.node_ids), revision=1, status=NavigationStatus.READY)
        self.route_id = f"route:{destination.purpose}:{self.plan.route_node_ids[0]}:{self.plan.route_node_ids[-1]}"
        if self.memory:
            self.memory.record_route(self.route_id, zone=destination.zone, start_key=self.plan.route_node_ids[0], destination_key=self.plan.route_node_ids[-1], node_ids=self.plan.route_node_ids)
        self.started_at = time.time()
        self.state.transition(NavigationStatus.READY)
        return self.plan

    def tick(self, *, position: WorldPosition, observation: NavigationVisionObservation, now: float | None = None) -> NavigationTick:
        if self.plan is None:
            return NavigationTick(NavigationStatus.FAILED, None, 0, "no_plan")
        now = time.time() if now is None else now
        self.progress.add(position, now)
        current_node = self.graph.nodes[self.plan.current_node_id] if self.plan.current_node_id else None
        if current_node and self._arrived_at_node(position, current_node.position):
            if self.plan.current_index < len(self.plan.route_node_ids) - 1:
                self.plan.current_index += 1
                self.plan.status = NavigationStatus.NAVIGATING
                self.state.status = NavigationStatus.NAVIGATING
                current_node = self.graph.nodes[self.plan.current_node_id] if self.plan.current_node_id else None
                if current_node and self._arrived_at_node(position, current_node.position) and self.plan.current_index == len(self.plan.route_node_ids) - 1:
                    if self.arrival.verify(position, self.plan.destination.arrival, observed_facts={"destination": self.plan.destination.position, **observation.addon_facts}):
                        self.plan.status = NavigationStatus.ARRIVED
                        self.state.status = NavigationStatus.ARRIVED
                        self._record_outcome(True, now)
                        return NavigationTick(self.state.status, None, self.plan.revision, "arrival_verified")
            elif self.arrival.verify(position, self.plan.destination.arrival, observed_facts={"destination": self.plan.destination.position, **observation.addon_facts}):
                self.plan.status = NavigationStatus.ARRIVED
                self.state.status = NavigationStatus.ARRIVED
                self._record_outcome(True, now)
                return NavigationTick(self.state.status, None, self.plan.revision, "arrival_verified")
        if self.state.status == NavigationStatus.READY:
            self.state.transition(NavigationStatus.NAVIGATING)
        if not self.progress.making_progress() and len(self.plan.route_node_ids) > 1:
            self.stuck_events += 1
            self.state.status = NavigationStatus.STUCK
            self._replan(position)
            return NavigationTick(self.state.status, None, self.plan.revision, "no_progress_replan")
        if current_node is None:
            return NavigationTick(self.state.status, None, self.plan.revision, "route_exhausted")
        decision = self.local.decide(player_position=position, waypoint=current_node.position, minimap=observation.minimap, world=observation.world)
        if decision.blocked:
            self._replan(position)
            return NavigationTick(self.state.status, None, self.plan.revision, "obstacle_replan")
        return NavigationTick(self.state.status, self.local.to_movement_intent(decision), self.plan.revision, "navigate")

    def _replan(self, position: WorldPosition) -> None:
        self.state.status = NavigationStatus.REPLANNING
        self.replans += 1
        assert self.plan is not None and self.plan.destination.position is not None
        route = RoutePlanner(self.graph, learning=self.learning).plan(position, self.plan.destination.position)
        self.plan.route_node_ids = list(route.node_ids)
        self.plan.current_index = 0
        while self.plan.current_index < len(self.plan.route_node_ids) - 1:
            node = self.graph.nodes[self.plan.route_node_ids[self.plan.current_index]]
            if not self._arrived_at_node(position, node.position):
                break
            self.plan.current_index += 1
        self.plan.revision += 1
        self.plan.status = NavigationStatus.READY
        self.state.status = NavigationStatus.READY

    def _record_outcome(self, success: bool, now: float) -> None:
        if self.memory and self.route_id:
            elapsed = (now - self.started_at) if self.started_at is not None else None
            self.memory.record_outcome(self.route_id, success=success, elapsed_seconds=elapsed, stuck_count=self.stuck_events, replan_count=self.replans)

    @staticmethod
    def _arrived_at_node(position: WorldPosition, node: WorldPosition, tolerance: float = 0.05) -> bool:
        return ((position.x-node.x)**2 + (position.y-node.y)**2 + (position.z-node.z)**2) ** 0.5 <= tolerance
