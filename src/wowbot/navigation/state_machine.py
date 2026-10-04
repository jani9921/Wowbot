from __future__ import annotations

from dataclasses import dataclass

from .models import NavigationStatus


@dataclass(slots=True)
class NavigationStateMachine:
    status: NavigationStatus = NavigationStatus.IDLE

    _allowed = {
        NavigationStatus.IDLE: {NavigationStatus.RESOLVING},
        NavigationStatus.RESOLVING: {NavigationStatus.ROUTING, NavigationStatus.FAILED},
        NavigationStatus.ROUTING: {NavigationStatus.READY, NavigationStatus.FAILED},
        NavigationStatus.READY: {NavigationStatus.NAVIGATING, NavigationStatus.FAILED},
        NavigationStatus.NAVIGATING: {NavigationStatus.STUCK, NavigationStatus.REPLANNING, NavigationStatus.ARRIVED, NavigationStatus.FAILED},
        NavigationStatus.STUCK: {NavigationStatus.REPLANNING, NavigationStatus.FAILED},
        NavigationStatus.REPLANNING: {NavigationStatus.READY, NavigationStatus.FAILED},
        NavigationStatus.ARRIVED: {NavigationStatus.IDLE},
        NavigationStatus.FAILED: {NavigationStatus.IDLE},
    }

    def transition(self, target: NavigationStatus) -> None:
        if target not in self._allowed[self.status]:
            raise ValueError(f"invalid navigation transition {self.status} -> {target}")
        self.status = target
