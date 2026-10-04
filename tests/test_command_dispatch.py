import pytest

from wowbot.execution import (CommandAcknowledgements, CommandDispatcher,
                              CommandState, DispatchLane)


class Executor:
    def __init__(self):
        self.calls = []
        self.stops = 0

    def execute(self, commands):
        self.calls.append(("DISCRETE", tuple(commands)))

    def execute_movement(self, commands):
        self.calls.append(("MOVEMENT", tuple(commands)))

    def stop_movement(self):
        self.stops += 1


def test_dispatch_routes_each_command_batch_to_exactly_one_executor_lane():
    executor = Executor()
    dispatcher = CommandDispatcher(executor)

    dispatcher.dispatch(["click"])
    dispatcher.dispatch(["forward", "left"], DispatchLane.MOVEMENT)

    assert executor.calls == [
        ("DISCRETE", ("click",)),
        ("MOVEMENT", ("forward", "left")),
    ]


def test_empty_dispatch_is_noop_and_stop_delegates_to_same_executor():
    executor = Executor()
    dispatcher = CommandDispatcher(executor)

    dispatcher.dispatch([])
    dispatcher.stop_movement()

    assert executor.calls == []
    assert executor.stops == 1


def test_movement_lane_falls_back_for_recording_executor_compatibility():
    class RecordingOnly:
        def __init__(self):
            self.commands = []

        def execute(self, commands):
            self.commands.extend(commands)

    executor = RecordingOnly()
    CommandDispatcher(executor).dispatch(["forward"], DispatchLane.MOVEMENT)
    assert executor.commands == ["forward"]


def test_successful_dispatch_has_explicit_local_ack_but_no_world_success():
    dispatcher = CommandDispatcher(Executor())
    receipt = dispatcher.dispatch(["click"], correlation_id="action:7")

    assert receipt.state is CommandState.LOCAL_ACK
    assert [state for state, _ in receipt.transitions] == [
        "CREATED", "QUEUED", "DISPATCHED", "LOCAL_ACK"]
    assert dispatcher.ack(receipt.command_id) is receipt
    assert receipt.correlation_id == "action:7"
    assert receipt.snapshot()["world_success"] is None


def test_backend_exception_records_failed_local_dispatch_and_reraises():
    class Broken:
        def execute(self, commands):
            raise RuntimeError("foreground lost")

    dispatcher = CommandDispatcher(Broken())
    with pytest.raises(RuntimeError, match="foreground lost"):
        dispatcher.dispatch(["click"])

    latest = dispatcher.diagnostics()["latest"]
    assert latest["state"] == "FAILED"
    assert latest["error"] == "foreground lost"
    assert latest["world_success"] is None


def test_acknowledgement_transition_is_fail_closed_and_bounded():
    ticks = iter(float(value) for value in range(100))
    acknowledgements = CommandAcknowledgements(max_receipts=8, clock=lambda: next(ticks))
    first = acknowledgements.create("DISCRETE", 1)
    acknowledgements.transition(first.command_id, CommandState.QUEUED)
    acknowledgements.cancel(first.command_id)
    with pytest.raises(RuntimeError, match="already terminal"):
        acknowledgements.transition(first.command_id, CommandState.DISPATCHED)

    for _ in range(12):
        acknowledgements.create("MOVEMENT", 1)
    diagnostics = acknowledgements.diagnostics()
    assert diagnostics["retained"] == 8
    assert acknowledgements.get(first.command_id) is None
