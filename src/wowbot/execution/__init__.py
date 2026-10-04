"""Execution-layer primitives.

They serialize already-authorized commands; binding resolution, PID/focus
validation, and the actual Windows backend remain outside this package.
"""

from .input_scheduler import InputScheduler
from .command_dispatch import CommandDispatcher, DispatchLane
from .command_ack import CommandAcknowledgements, CommandReceipt, CommandState

__all__ = [
    "InputScheduler", "CommandDispatcher", "DispatchLane",
    "CommandAcknowledgements", "CommandReceipt", "CommandState",
]
