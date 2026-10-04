"""Bounded local command-dispatch acknowledgement lifecycle.

LOCAL_ACK proves only that the selected input backend returned successfully.
It is deliberately not evidence that the intended world/UI outcome happened.
"""
from __future__ import annotations

from collections import Counter, deque
from dataclasses import dataclass, field
from enum import StrEnum
import threading
import time
import uuid


class CommandState(StrEnum):
    CREATED = "CREATED"
    QUEUED = "QUEUED"
    DISPATCHED = "DISPATCHED"
    LOCAL_ACK = "LOCAL_ACK"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


_TERMINAL = frozenset({
    CommandState.LOCAL_ACK, CommandState.FAILED, CommandState.CANCELLED,
})
_ALLOWED = {
    CommandState.CREATED: frozenset({CommandState.QUEUED, CommandState.CANCELLED}),
    CommandState.QUEUED: frozenset({CommandState.DISPATCHED, CommandState.CANCELLED}),
    CommandState.DISPATCHED: frozenset({CommandState.LOCAL_ACK, CommandState.FAILED}),
}


@dataclass
class CommandReceipt:
    command_id: str
    lane: str
    command_count: int
    state: CommandState
    created_at: float
    updated_at: float
    correlation_id: str | None = None
    error: str | None = None
    transitions: list[tuple[str, float]] = field(default_factory=list)

    def snapshot(self) -> dict:
        return {
            "command_id": self.command_id,
            "lane": self.lane,
            "command_count": self.command_count,
            "state": self.state.value,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "correlation_id": self.correlation_id,
            "error": self.error,
            "transitions": list(self.transitions),
            "world_success": None,
        }


class CommandAcknowledgements:
    """Thread-safe bounded record of local backend delivery state."""

    def __init__(self, *, max_receipts: int = 256, clock=time.monotonic) -> None:
        self.max_receipts = max(8, int(max_receipts))
        self.clock = clock
        self._lock = threading.RLock()
        self._receipts: dict[str, CommandReceipt] = {}
        self._order: deque[str] = deque()

    def create(self, lane: str, command_count: int,
               correlation_id: str | None = None) -> CommandReceipt:
        now = self.clock()
        receipt = CommandReceipt(
            uuid.uuid4().hex, str(lane), int(command_count),
            CommandState.CREATED, now, now,
            correlation_id=correlation_id,
            transitions=[(CommandState.CREATED.value, now)])
        with self._lock:
            self._receipts[receipt.command_id] = receipt
            self._order.append(receipt.command_id)
            while len(self._order) > self.max_receipts:
                self._receipts.pop(self._order.popleft(), None)
        return receipt

    def transition(self, command_id: str, state: CommandState,
                   *, error: str | None = None) -> CommandReceipt:
        with self._lock:
            receipt = self._receipts[command_id]
            if receipt.state in _TERMINAL:
                if receipt.state is state:
                    return receipt
                raise RuntimeError(
                    f"command {command_id} already terminal: {receipt.state.value}")
            if state not in _ALLOWED.get(receipt.state, frozenset()):
                raise RuntimeError(
                    f"invalid command transition {receipt.state.value}->{state.value}")
            now = self.clock()
            receipt.state = state
            receipt.updated_at = now
            receipt.error = error
            receipt.transitions.append((state.value, now))
            return receipt

    def cancel(self, command_id: str) -> CommandReceipt:
        return self.transition(command_id, CommandState.CANCELLED)

    def get(self, command_id: str) -> CommandReceipt | None:
        with self._lock:
            return self._receipts.get(command_id)

    def diagnostics(self) -> dict:
        with self._lock:
            receipts = [self._receipts[item] for item in self._order
                        if item in self._receipts]
            counts = Counter(receipt.state.value for receipt in receipts)
            return {
                "retained": len(receipts),
                "max_receipts": self.max_receipts,
                "states": dict(counts),
                "latest": receipts[-1].snapshot() if receipts else None,
            }
