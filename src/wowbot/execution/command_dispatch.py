"""Single engine-facing route into the authoritative input executor."""
from __future__ import annotations

from enum import StrEnum

from .command_ack import CommandAcknowledgements, CommandReceipt, CommandState


class DispatchLane(StrEnum):
    DISCRETE = "DISCRETE"
    MOVEMENT = "MOVEMENT"


class CommandDispatcher:
    """Route authorized commands without becoming an input backend or owner.

    Binding resolution, selected PID, foreground validation, cancellation and
    physical input remain responsibilities of the supplied InputExecutor.
    """

    def __init__(self, executor, acknowledgements=None) -> None:
        self.executor = executor
        self.acknowledgements = acknowledgements or CommandAcknowledgements()

    def dispatch(self, commands, lane: DispatchLane = DispatchLane.DISCRETE, *,
                 correlation_id: str | None = None) -> CommandReceipt | None:
        if not commands:
            return None
        receipt = self.acknowledgements.create(
            lane.value, len(commands), correlation_id)
        self.acknowledgements.transition(receipt.command_id, CommandState.QUEUED)
        self.acknowledgements.transition(receipt.command_id, CommandState.DISPATCHED)
        try:
            if lane is DispatchLane.MOVEMENT:
                execute = getattr(self.executor, "execute_movement", self.executor.execute)
                execute(commands)
            else:
                self.executor.execute(commands)
        except Exception as error:
            self.acknowledgements.transition(
                receipt.command_id, CommandState.FAILED, error=str(error))
            raise
        return self.acknowledgements.transition(
            receipt.command_id, CommandState.LOCAL_ACK)

    def ack(self, command_id: str) -> CommandReceipt | None:
        """Return a local receipt; this never verifies a world outcome."""
        return self.acknowledgements.get(command_id)

    def cancel(self, command_id: str) -> CommandReceipt:
        return self.acknowledgements.cancel(command_id)

    def diagnostics(self) -> dict:
        return self.acknowledgements.diagnostics()

    def stop_movement(self) -> None:
        stop = getattr(self.executor, "stop_movement", None)
        if stop:
            stop()
