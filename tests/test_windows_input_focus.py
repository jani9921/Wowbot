"""Issue #78: the SendInput boundary rechecks selected-PID focus per press."""
import pytest

from wowbot.agent.executor import ExecutionError
from wowbot.agent.windows_input import WindowsInput


class FakeApi:
    def __init__(self):
        self.sent = []

    def SendInput(self, count, event, size):
        ev = event._obj
        if ev.type == 1:
            self.sent.append((ev.ki.vk, "up" if ev.ki.flags & 2 else "down"))
        else:
            self.sent.append(("mouse", ev.mi.dwFlags))
        return 1


def backend(focus):
    win = WindowsInput.__new__(WindowsInput)
    win.pid, win.api = 42, FakeApi()
    win.is_selected_foreground = focus
    return win


def test_key_down_is_refused_without_selected_foreground():
    win = backend(lambda: False)
    with pytest.raises(ExecutionError):
        win.key("W", True)
    assert win.api.sent == []


def test_key_up_is_still_sent_after_focus_loss():
    win = backend(lambda: False)
    win.key("W", False)
    assert win.api.sent == [(ord("W"), "up")]


def test_focus_loss_inside_a_chord_releases_pressed_modifiers():
    answers = iter([True, False])
    win = backend(lambda: next(answers))
    with pytest.raises(ExecutionError):
        win.key("SHIFT-W", True)
    assert win.api.sent == [(16, "down"), (16, "up")]


def test_focused_chord_is_sent_in_order():
    win = backend(lambda: True)
    win.key("CTRL-1", True)
    win.key("CTRL-1", False)
    assert win.api.sent == [(17, "down"), (ord("1"), "down"), (ord("1"), "up"), (17, "up")]
