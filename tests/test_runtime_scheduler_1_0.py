from wowbot.agent.runtime_scheduler import BrainScheduler, RateMeter, RuntimeCadenceScheduler


def test_brain_scheduler_is_event_driven_and_ignores_cursor_noise():
    scheduler = BrainScheduler(minimum_interval=.5)
    state = {"session_id": "s", "quest_state_revision": 1,
             "cursor_position": {"nx": .1, "ny": .1}}
    assert scheduler.should_plan(state, None, 1) == (True, "INITIAL")
    state["cursor_position"] = {"nx": .9, "ny": .8}
    assert scheduler.should_plan(state, None, 1.1) == (False, "FAST_LOOP_CONTINUES")
    state["quest_state_revision"] = 2
    assert scheduler.should_plan(state, None, 1.11) == (True, "WORLD_EVENT")


def test_rate_meter_reports_observed_frequency():
    meter = RateMeter(10)
    for index in range(11):
        meter.mark(index*.1)
    assert 9.9 <= meter.hz(1.) <= 10.1


def test_named_sensor_gates_have_independent_cadences_and_report_rates():
    scheduler = RuntimeCadenceScheduler()
    assert scheduler.should_capture(1., interval=.025)
    assert not scheduler.should_capture(1.01, interval=.025)
    assert scheduler.should_run_world3d(1., interval=.1)
    assert scheduler.should_run_minimap(1., interval=.2)
    assert scheduler.should_run_map(1., interval=.3)
    assert scheduler.should_run_ocr(1., interval=.6)
    assert not scheduler.should_run_world3d(1.05, interval=.1)
    assert scheduler.should_run_world3d(1.1, interval=.1)
    rates = scheduler.rates(1.1)
    assert "world3d_hz" in rates and rates["capture_skips"] == 1


def test_brain_scheduler_exposes_full_runtime_scheduler_contract():
    scheduler = BrainScheduler()
    for name in ("should_capture", "should_run_world3d", "should_run_minimap",
                 "should_run_map", "should_run_ocr", "should_plan", "rates"):
        assert callable(getattr(scheduler, name))


def test_brain_scheduler_wakes_when_an_open_dialog_becomes_addressable():
    scheduler = BrainScheduler(minimum_interval=.5)
    state = {"session_id": "s", "quest_state_revision": 1,
             "quest_ui_open": True, "quest_ui": {"open": True}}
    assert scheduler.should_plan(state, None, 1.) == (True, "INITIAL")
    state.update({"quest_ui_action": "ACCEPT", "quest_ui_x": .035, "quest_ui_y": .43,
                  "quest_ui_quest_id": 55122})
    assert scheduler.should_plan(state, None, 1.01) == (True, "WORLD_EVENT")


# Live-confirmed 2026-09-22: a never-stabilizing vision track gets a brand
# new track_id every tick even though its (state, belief, inspectable)
# triple is unchanged, and track_id used to be part of the signature -- this
# forced a full replan on effectively every tick (brain_skips stuck at 0)
# during any stuck search/INSPECT loop instead of the intended ~2 Hz cadence.

def _churning_candidates(tick, *, n=25, extra=None):
    candidates = [{"track_id": f"WORLD3D:{tick}-{i}", "track_state": "TENTATIVE",
                   "belief": "CANDIDATE", "inspectable": False} for i in range(n)]
    if extra:
        candidates.append(extra)
    return candidates


def test_pure_track_identity_churn_does_not_force_a_replan():
    scheduler = BrainScheduler(minimum_interval=.5)
    state = {"session_id": "s", "quest_state_revision": 1,
             "visual_candidates": _churning_candidates(0)}
    assert scheduler.should_plan(state, None, 1.) == (True, "INITIAL")
    for tick, now in enumerate((1.05, 1.10, 1.15, 1.20), start=1):
        state["visual_candidates"] = _churning_candidates(tick)
        assert scheduler.should_plan(state, None, now) == (False, "FAST_LOOP_CONTINUES")


def test_a_genuinely_new_or_upgraded_track_still_forces_a_replan_during_churn():
    scheduler = BrainScheduler(minimum_interval=.5)
    state = {"session_id": "s", "quest_state_revision": 1,
             "visual_candidates": _churning_candidates(0)}
    scheduler.should_plan(state, None, 1.)
    state["visual_candidates"] = _churning_candidates(1)
    assert scheduler.should_plan(state, None, 1.05) == (False, "FAST_LOOP_CONTINUES")
    # A track that becomes SUPPORTED/inspectable is a real planning-relevant
    # change, not identity noise, and must still wake the scheduler even
    # while background tracks keep churning.
    state["visual_candidates"] = _churning_candidates(2, extra={
        "track_id": "WORLD3D:new", "track_state": "ACTIVE",
        "belief": "SUPPORTED", "inspectable": True})
    assert scheduler.should_plan(state, None, 1.10) == (True, "WORLD_EVENT")
