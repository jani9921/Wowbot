"""
Mock implementations of the core interfaces, used for testing FishingTask
(and later tasks) without launching a real WoW client or connecting to
a sandbox server. Tests drive these mocks explicitly to simulate
specific scenarios (cast success, bobber timeout, bite detected, etc).
"""

from __future__ import annotations

import time
import uuid
from typing import Callable, Optional

from src.core.commands import ClientCommand, CommandResult, CommandStatus
from src.core.events import Event, EventType
from src.core.interfaces import (
    IClientStateReader,
    IClientCommandExecutor,
    IEventSource,
    IWorldState,
)
from src.core.state import PlayerState


class MockStateReader(IClientStateReader):
    def __init__(self, client_id: str) -> None:
        self.client_id = client_id
        self.state = PlayerState(client_id=client_id, timestamp=time.time())

    def read_state(self) -> PlayerState:
        return self.state

    def set_state(self, **fields) -> None:
        self.state = PlayerState(**{**self.state.__dict__, **fields, "timestamp": time.time()})


class MockCommandExecutor(IClientCommandExecutor):
    """By default, commands succeed immediately on the *next* call to
    get_result (simulating one tick of latency). Tests can override
    per-command behavior via `set_outcome` or `set_default_outcome`."""

    def __init__(self) -> None:
        self._queued: dict[str, ClientCommand] = {}
        self._results: dict[str, CommandResult] = {}
        self._forced_outcomes: dict[str, CommandStatus] = {}
        self.default_outcome: Optional[CommandStatus] = CommandStatus.SUCCESS
        self.auto_resolve: bool = True

    def submit(self, command: ClientCommand) -> None:
        command.status = CommandStatus.QUEUED
        self._queued[command.command_id] = command
        if self.auto_resolve:
            self._resolve(command.command_id)

    def cancel(self, command_id: str) -> bool:
        if command_id in self._queued and command_id not in self._results:
            self._results[command_id] = CommandResult(command_id, CommandStatus.CANCELLED)
            return True
        return False

    def get_result(self, command_id: str) -> Optional[CommandResult]:
        return self._results.get(command_id)

    def set_outcome(self, command_id: str, status: CommandStatus) -> None:
        self._forced_outcomes[command_id] = status

    def resolve_pending(self) -> None:
        """Manually resolve all queued-but-unresolved commands (used when
        auto_resolve is False, to simulate command latency across ticks)."""
        for cmd_id in list(self._queued.keys()):
            if cmd_id not in self._results:
                self._resolve(cmd_id)

    def _resolve(self, command_id: str) -> None:
        status = self._forced_outcomes.get(command_id, self.default_outcome)
        if status is None:
            return
        self._results[command_id] = CommandResult(command_id, status)


class MockEventSource(IEventSource):
    def __init__(self) -> None:
        self._handlers: list[Callable[[Event], None]] = []
        self._log: list[Event] = []

    def subscribe(self, handler: Callable[[Event], None]) -> Callable[[], None]:
        self._handlers.append(handler)

        def unsubscribe() -> None:
            if handler in self._handlers:
                self._handlers.remove(handler)

        return unsubscribe

    def poll(self) -> list[Event]:
        return list(self._log)

    def emit(self, client_id: str, event_type: EventType, **payload) -> None:
        event = Event(client_id=client_id, type=event_type, payload=payload, source="mock")
        self._log.append(event)
        for handler in list(self._handlers):
            handler(event)


class MockWorldState(IWorldState):
    def __init__(self) -> None:
        self._in_water_range: Optional[bool] = True
        self._under_attack: Optional[bool] = False

    def is_in_water_range(self) -> Optional[bool]:
        return self._in_water_range

    def is_under_attack(self) -> Optional[bool]:
        return self._under_attack

    def set_in_water_range(self, value: Optional[bool]) -> None:
        self._in_water_range = value

    def set_under_attack(self, value: Optional[bool]) -> None:
        self._under_attack = value
