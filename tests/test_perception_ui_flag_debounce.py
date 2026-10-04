from types import SimpleNamespace

from wowbot.agent.perception import PerceptionWorker


def _worker():
    return SimpleNamespace(_ui_flags={}, ui_flag_raw_flips={}, ui_flag_debounce=.25)


def test_flickering_world_map_flag_does_not_change_perception_context():
    worker = _worker()
    flag = lambda raw, at: PerceptionWorker._debounced_ui_flag(worker, "world_map_open", raw, at)
    assert flag(False, 0.0) is False
    # Live 2026-09-30: flips every 20-250 ms around OPEN_MAP.
    at, raw = 0.0, False
    for step in range(40):
        at += .03 + (step % 4) * .04
        raw = not raw
        assert flag(raw, at) is False
    assert worker.ui_flag_raw_flips["world_map_open"] == 40


def test_persistent_world_map_open_takes_effect_after_debounce():
    worker = _worker()
    flag = lambda raw, at: PerceptionWorker._debounced_ui_flag(worker, "world_map_open", raw, at)
    assert flag(False, 0.0) is False
    assert flag(True, 1.0) is False
    assert flag(True, 1.1) is False
    assert flag(True, 1.26) is True
    assert flag(True, 2.0) is True
    assert flag(False, 3.0) is True
    assert flag(False, 3.3) is False
