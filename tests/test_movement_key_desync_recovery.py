from wowbot.agent.bindings import BindingsCache
from wowbot.agent.executor import InputExecutor
from wowbot.agent.models import Command


def binding_file(tmp_path, extra=""):
    path = tmp_path / "bindings-cache.wtf"
    path.write_text('bind "W" "MOVEFORWARD"\nbind "A" "TURNLEFT"\nbind "D" "TURNRIGHT"\n' + extra,
                    encoding="utf-8")
    return path


class VerifiableBackend:
    """Like test_agent_core.py's Backend, but reports real key state so
    execute_movement's staleness check has something to compare against."""

    def __init__(self):
        self.foreground, self.emergency, self.calls = True, False, []
        self.real_state: dict[str, bool] = {}

    def is_selected_foreground(self):
        return self.foreground

    def emergency_pressed(self):
        return self.emergency

    def key(self, key, down):
        self.calls.append((key, down))
        self.real_state[key] = down

    def is_key_down(self, key):
        return self.real_state.get(key, False)

    def move(self, x, y):
        self.calls.append((x, y))


def test_desynced_key_is_released_and_repressed_on_the_next_update(tmp_path):
    # Live-observed 2026-09-14: MOVE displayed unchanged for 64+ real seconds
    # with zero character displacement, then started the moment the user
    # moved the mouse. execute_movement only skips re-pressing a movement key
    # already in self._held -- if the game or Windows silently dropped that
    # key without us knowing (self._held and reality disagree), the same
    # direction being requested again forever never triggers a fresh
    # key-down. Simulating exactly that: the backend reports "W" as no
    # longer physically down between two identical MOVEFORWARD updates.
    backend = VerifiableBackend()
    exe = InputExecutor(42, BindingsCache(binding_file(tmp_path)), backend)
    exe.execute_movement((Command("BIND", "MOVEFORWARD", .08),))
    assert backend.calls == [("W", True)]

    # Something external released it without telling us.
    backend.real_state["W"] = False

    exe.execute_movement((Command("BIND", "MOVEFORWARD", .08),))
    assert backend.calls[-2:] == [("W", False), ("W", True)]
    assert backend.real_state["W"] is True


def test_key_reported_still_down_is_left_alone(tmp_path):
    backend = VerifiableBackend()
    exe = InputExecutor(42, BindingsCache(binding_file(tmp_path)), backend)
    exe.execute_movement((Command("BIND", "MOVEFORWARD", .08),))
    exe.execute_movement((Command("BIND", "MOVEFORWARD", .08),))
    # Real state matched the whole time; no spurious release/re-press.
    assert backend.calls == [("W", True)]


def test_backend_without_is_key_down_is_unaffected(tmp_path):
    # Confirms the check is purely additive: a backend that doesn't support
    # it (e.g. the plain test double used elsewhere) behaves exactly as
    # before.
    class PlainBackend:
        def __init__(self):
            self.calls = []
        def is_selected_foreground(self): return True
        def emergency_pressed(self): return False
        def key(self, key, down): self.calls.append((key, down))
        def move(self, x, y): self.calls.append((x, y))

    backend = PlainBackend()
    exe = InputExecutor(42, BindingsCache(binding_file(tmp_path)), backend)
    exe.execute_movement((Command("BIND", "MOVEFORWARD", .08),))
    exe.execute_movement((Command("BIND", "MOVEFORWARD", .08),))
    assert backend.calls == [("W", True)]
