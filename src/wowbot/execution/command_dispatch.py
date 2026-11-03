"""Single engine-facing route into the authoritative input executor."""
from __future__ import annotations

from enum import StrEnum

from .command_ack import CommandAcknowledgements, CommandReceipt, CommandState


class DispatchLane(StrEnum):
    DISCRETE = "DISCRETE"
    MOVEMENT = "MOVEMENT"


# User 2026-10-21 16:15 ("az egeret is húzogatja rá a trackekre, azt is ki
# kellene venni"): in server mode no command moves the pointer onto a screen
# track or pans the camera for a search.  UI clicks (dialog rows, shop items,
# death popups) are CLICKs and stay.
WORLD_POINTER_KINDS = frozenset({"HOVER", "POINTER", "CAMERA_GLANCE", "CAMERA_PAN"})


# Main action-bar buttons a flight controller may tap while airborne (user
# 2026-10-25: Skyriding Surge Forward).  The controller verifies the Skyriding
# bar before choosing one; a tap is a discrete key press, never a key held by
# the movement lease (InputExecutor.execute_movement still rejects it).
FLIGHT_ABILITY_ACTIONS = frozenset(f"ACTIONBUTTON{index}" for index in range(1, 13))


def flight_ability_tap(commands) -> bool:
    """One bare action-button press returned by a movement controller."""
    return (len(commands) == 1 and getattr(commands[0], "kind", None) == "BIND"
            and not getattr(commands[0], "simultaneous", ())
            and getattr(commands[0], "binding", None) in FLIGHT_ABILITY_ACTIONS)


class CommandDispatcher:
    """Route authorized commands without becoming an input backend or owner.

    Binding resolution, selected PID, foreground validation, cancellation and
    physical input remain responsibilities of the supplied InputExecutor.
    """

    def __init__(self, executor, acknowledgements=None, pointer_gate=None) -> None:
        self.executor = executor
        self.acknowledgements = acknowledgements or CommandAcknowledgements()
        # Callable: True while world-pointer commands are withheld (server mode).
        self.pointer_gate = pointer_gate
        self.withheld_pointer_commands = 0

    def dispatch(self, commands, lane: DispatchLane = DispatchLane.DISCRETE, *,
                 correlation_id: str | None = None) -> CommandReceipt | None:
        if commands and self.pointer_gate is not None and self.pointer_gate():
            kept = tuple(command for command in commands
                         if getattr(command, "kind", None) not in WORLD_POINTER_KINDS)
            self.withheld_pointer_commands += len(commands) - len(kept)
            commands = kept
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
