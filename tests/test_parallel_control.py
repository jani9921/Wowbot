"""Compatible control activities, one canonical attempt, no client input."""
import threading
import time
from types import SimpleNamespace

import pytest

from test_active_pointer_tracking import attempt, box, scene
from test_agent_core import state
from wowbot.agent.engine import AutonomousAgent
from wowbot.agent.executor import RecordingExecutor
from wowbot.agent.models import Command, Mode, Observation
from wowbot.agent.parallel_runtime import ParallelRuntimePump
from wowbot.agent.parallel_view import control_safety, control_view
from wowbot.agent.sensor import BufferedPixelSensor
from wowbot.agent.sensor_hub import SensorHub
from wowbot.agent.visual_recognition_worker import VisualRecognitionWorker
from wowbot.execution.resource_arbiter import Resource, ResourceArbiter
from wowbot.runtime import Intent


def setup(skill="VISUAL_APPROACH", now=10.):
    executor = RecordingExecutor()
    agent = AutonomousAgent(executor)
    current = scene(now)
    current["target"].update(visual_track_id="WORLD3D:npc", screen_position={
        "x": .55, "y": .6, "source": "BOUND_WORLD3D_TRACK", "track_id": "WORLD3D:npc", "sample_time": now})
    agent.world.ingest(Observation.create(current, now))
    agent.set_mode(Mode.FULL_AI)
    params = ({"track_id": "WORLD3D:npc", "purpose": "INTERACT"} if skill == "OBJECT_USE" else
              {"guid": "henry", "track_id": "WORLD3D:npc", "purpose": "INTERACT"})
    agent.pending = attempt(skill, params)
    if skill == "VISUAL_APPROACH":
        started = agent.visual_approach_skill.begin(agent.active_skill.state, current, "v0", now)
        executor.execute_movement(tuple(started.commands))
    agent.parallel_control.enabled = True
    agent.parallel_control.expected_epoch = 1
    return agent, executor


def control_sample(agent, now, index, x=.55):
    payload = state(now, transport_kind="FAST", telemetry_lane="FAST_STATE", fast_sequence=index,
                    target={"guid": "henry", "attackable": False},
                    cursor_position={"nx": .1, "ny": .3})
    vision = {"items": [box(now, x)], "revision": index, "epoch": 1,
              "at": now, "context": (agent.world.session_id, agent.world.state.get("character_guid"),
                                       agent.world.state.get("map_id"), 0)}
    return payload, vision


def test_fast_servo_and_pointer_advance_without_medium_observation_builds():
    agent, executor = setup()
    original = agent.world.latest.observation_id
    for index in range(12):
        now = 10.+index*.04
        payload, vision = control_sample(agent, now, index, .55+index*.004)
        result = agent.parallel_control.tick(payload, now, vision, now)
        assert result["consumed"]
    assert len([c for c in executor.commands if c.kind == "POINTER"]) == 12
    assert len([c for c in executor.commands if c.binding == "MOVEFORWARD"]) == 12
    assert agent.world.latest.observation_id == original
    assert agent.pending.action_id == "a"
    assert agent.parallel_control.counts["VISUAL_APPROACH"] == 12


def test_move_discovers_a_quest_npc_with_mouseover_without_stopping_navigation():
    agent, executor = setup("MOVE")
    # A location route has no committed NPC yet; attention can identify it
    # while the SAME NavigationService continues to own the forward lease.
    agent.pending.proposal = agent.pending.proposal.make("MOVE", "route", {
        "x": .5, "y": .4, "map_id": 1609, "purpose": "SEARCH_TURN_IN_AREA"})
    payload, vision = control_sample(agent, 10., 1)
    vision["items"][0]["visual_group"] = {"appearance_labels": ["overhead_symbol_like"], "belief": "SUPPORTED"}
    agent.navigation.start_skill_request("MOVE", agent.pending.proposal.parameters,
                                         agent.world.state, "start", 10.)
    agent.parallel_control.tick(payload, 10., vision, 10.)
    assert any(c.binding == "MOVEFORWARD" for c in executor.commands)
    assert any(c.kind == "POINTER" for c in executor.commands)
    assert not any(c.kind == "HOVER" or c.kind.startswith("CLICK") for c in executor.commands)
    resources = agent.parallel_control.arbiter.snapshot(10.)
    assert resources["LEGS"]["owner"] == "LOCOMOTION"
    assert resources["MOUSE"]["owner"] == "ATTENTION"


def test_target_verifies_a_moving_box_without_waiting_for_a_medium_tick():
    agent, executor = setup("TARGET")
    params = {"guid": "new-npc", "track_id": "WORLD3D:npc", "hover_x": .55, "hover_y": .6,
              "click_current_cursor": True}
    agent.active_skill.state.intent = Intent("TARGET", params, "new-npc")
    agent.target_skill.begin(agent.active_skill.state)
    payload, vision = control_sample(agent, 10.04, 2, .6)
    agent.parallel_control.tick(payload, 10.04, vision, 10.04)
    assert executor.commands[-1].kind == "POINTER"
    payload, vision = control_sample(agent, 10.08, 3, .6)
    payload.update(mouseover={"guid": "new-npc"}, mouseover_sample_time=10.08,
                   cursor_position={"nx": .6, "ny": .6}, cursor_sample_time=10.08)
    agent.parallel_control.tick(payload, 10.08, vision, 10.08)
    assert executor.commands[-1].kind == "CLICK_CURRENT_CURSOR"
    assert agent.pending.action_id == "a"      # still the same target FSM


def test_combat_rotation_and_its_target_pointer_share_fast_control():
    from test_m0_combat_loot_skills import combat_state
    agent, executor = setup("COMBAT")
    params = agent.active_skill.state.intent.parameters
    params.update(guid="mob-1")
    agent.active_skill.state.intent = Intent("COMBAT", params, "mob-1")
    agent.pending.proposal = agent.pending.proposal.make("COMBAT", "fight", params)
    first = {**state(10.), **combat_state(), "is_in_combat": True}
    first["target"].update(visual_track_id="WORLD3D:npc", screen_position={
        "x": .5, "y": .6, "sample_time": 10., "track_id": "WORLD3D:npc"})
    first["visual_candidates"] = [box(10., .5)]
    agent.world.ingest(Observation.create(first, 10.))
    started = agent.combat_skill.begin(agent.active_skill.state, first, 10.)
    assert started.commands[0].binding == "ACTIONBUTTON1"
    payload, vision = control_sample(agent, 11., 2, .5)
    payload.update(target={"guid": "mob-1", "attackable": True, "health": 100}, is_in_combat=True)
    agent.parallel_control.tick(payload, 11., vision, 11.)
    assert any(c.kind == "POINTER" for c in executor.commands)
    assert any(c.binding == "ACTIONBUTTON1" for c in executor.commands)


def test_object_use_gets_fresh_hover_and_sends_only_one_right_click_in_fast_lane():
    from wowbot.skills.object_use import ObjectUseSkill
    agent, executor = setup("OBJECT_USE")
    params = {"x": .55, "y": .6, "object_id": 77, "expected_tooltips": ["Campfire"],
              "mouseover_tooltip": "Campfire", "quest_ids": [10], "objective_ids": ["10:0"]}
    agent.active_skill.state.intent.parameters.update(params)
    payload, vision = control_sample(agent, 10., 1)
    payload.update(mouseover={"object_id": 77, "tooltip": "Campfire", "quest_id": 10, "quest_related": True},
                   mouseover_sample_time=10., cursor_sample_time=10., cursor_position={"nx": .55, "ny": .6})
    first = control_view(agent.world.state, payload, vision, 10.)
    started = ObjectUseSkill().begin(agent.active_skill.state, first)
    assert started.commands[0].kind == "HOVER"
    payload.update(monotonic_time=10.1, fast_sequence=2, mouseover_sample_time=10.1, cursor_sample_time=10.1)
    agent.parallel_control.tick(payload, 10.1, vision, 10.1)
    assert [(c.kind, c.button) for c in executor.commands] == [("CLICK", "RIGHT")]
    payload.update(monotonic_time=10.2, fast_sequence=3)
    agent.parallel_control.tick(payload, 10.2, vision, 10.2)
    assert len(executor.commands) == 1


@pytest.mark.parametrize("change,reason", [
    ({"is_in_combat": True}, "combat_preemption"), ({"loading": True}, "client_blocked"),
    ({"input_blocked": True}, "client_blocked"), ({"is_dead": True}, "death_transition"),
    ({"movement": {"falling": True}}, "fall_transition"), ({"quest_ui_open": True}, "modal_ui"),
    ({"gossip_open": True}, "modal_ui"), ({"world_map_open": True}, "modal_ui"),
    ({"session_id": "other"}, "vision_context_changed"),
])
def test_fast_safety_preempts_pointer_and_movement(change, reason):
    agent, executor = setup()
    payload, vision = control_sample(agent, 10., 1)
    payload.update(change)
    result = agent.parallel_control.tick(payload, 10., vision, 10.)
    assert result.get("force_medium") and result["reason"] == reason
    assert not any(c.kind == "POINTER" for c in executor.commands)
    assert executor.stops > 0
    assert agent.parallel_control.arbiter.snapshot(10.) == {}


def test_vision_epoch_reset_cannot_reuse_an_old_track_identity():
    agent, executor = setup()
    payload, vision = control_sample(agent, 10., 1)
    vision["epoch"] = 2
    result = agent.parallel_control.tick(payload, 10., vision, 10.)
    assert result["reason"] == "vision_epoch_changed" and not any(c.kind == "POINTER" for c in executor.commands)


def test_repeated_or_old_sensor_data_is_not_an_unlimited_movement_lease():
    agent, executor = setup()
    payload, vision = control_sample(agent, 10., 1)
    agent.parallel_control.tick(payload, 10., vision, 10.)
    count = len(executor.commands)
    agent.parallel_control.tick(payload, 10., vision, 10.01)
    assert len(executor.commands) == count
    result = agent.parallel_control.tick(payload, 10., vision, 10.6)
    assert result["reason"] == "telemetry_gap" and len(executor.commands) == count


def test_fast_control_does_not_wait_for_the_canonical_lock():
    agent, executor = setup()
    ready, release = threading.Event(), threading.Event()
    def hold():
        with agent.lock:
            ready.set()
            release.wait(1.)
    thread = threading.Thread(target=hold)
    thread.start()
    try:
        assert ready.wait(1.)
        payload, vision = control_sample(agent, 10., 1)
        result = agent.parallel_control.tick(payload, 10., vision, 10.)
        assert result["reason"] == "canonical_owner_busy" and not any(c.kind == "POINTER" for c in executor.commands)
    finally:
        release.set()
        thread.join(1.)


def test_fast_terminal_is_staged_once_for_the_same_attempt_not_a_second_skill():
    agent, executor = setup()
    payload, vision = control_sample(agent, 10., 1)
    payload["target"]["guid"] = "kee-la"
    result = agent.parallel_control.tick(payload, 10., vision, 10.)
    assert result["terminal"] and agent.pending.action_id == "a"
    assert agent.parallel_control.take_terminal("different-action") is None
    # Reproduce without consuming the staged result under a different ID.
    payload, vision = control_sample(agent, 10.04, 2)
    payload["target"]["guid"] = "kee-la"
    agent.parallel_control.tick(payload, 10.04, vision, 10.04)
    terminal = agent.parallel_control.take_terminal("a")
    assert terminal is not None and terminal.terminal_outcome is not None
    assert agent.parallel_control.take_terminal("a") is None
    assert not any(c.kind == "POINTER" for c in executor.commands)


def test_fast_view_preserves_identity_only_for_exact_same_guid_and_track():
    agent, _ = setup()
    base = agent.world.state
    payload, vision = control_sample(agent, 10.1, 2, .65)
    projected = control_view(base, payload, vision, 10.1)
    assert projected["target"]["screen_position"]["x"] == .65
    assert projected["target"]["screen_position"]["sample_time"] == 10.1
    assert base["target"]["screen_position"]["x"] == .55
    payload["target"] = {"guid": "kee-la"}
    projected = control_view(base, payload, vision, 10.1)
    assert "screen_position" not in projected["target"]
    vision["items"][0]["observed_at"] = 9.
    assert control_view(base, payload, vision, 10.1)["visual_candidates"][0]["observed_at"] == 9.


def test_fast_view_never_restamps_delayed_or_omitted_hover_as_a_new_sample():
    agent, _ = setup()
    agent.world.state.update(mouseover={"guid": "before-hover"}, mouseover_sample_time=9.5)
    payload, vision = control_sample(agent, 10., 1)
    payload.update(mouseover={"guid": "after-hover"})
    payload.pop("mouseover_sample_time", None)
    projected = control_view(agent.world.state, payload, vision, 10.2)
    assert projected["mouseover_sample_time"] == 10.  # real sample, not 10.2
    payload.pop("mouseover")
    projected = control_view(agent.world.state, payload, vision, 10.2)
    assert projected["mouseover_sample_time"] == 9.5
    assert agent.world.state["mouseover_sample_time"] == 9.5


@pytest.mark.parametrize("field", ["is_casting", "is_channeling"])
def test_cast_blocks_forward_and_turn_but_can_keep_the_cursor_on_its_target(field):
    agent, executor = setup()
    payload, vision = control_sample(agent, 10.04, 1, .65)
    payload[field] = True
    before = len(executor.commands)
    result = agent.parallel_control.tick(payload, 10.04, vision, 10.04)
    assert result["reason"] == "cast_hold" and executor.stops > 0
    assert all(c.kind == "POINTER" for c in executor.commands[before:])
    assert any(c.kind == "POINTER" for c in executor.commands[before:])
    assert agent.parallel_control.arbiter.snapshot(10.04)["LEGS"]["owner"] == "CAST_HOLD"
    payload, vision = control_sample(agent, 10.08, 2, .65)
    payload[field] = False
    agent.parallel_control.tick(payload, 10.08, vision, 10.08)
    assert any(c.binding in {"MOVEFORWARD", "TURNLEFT", "TURNRIGHT"}
               for c in executor.commands[before:])
    assert all(lease["owner"] != "CAST_HOLD"
               for lease in agent.parallel_control.arbiter.snapshot(10.08).values())


def test_cast_still_runs_the_existing_object_verifier_without_sending_a_new_key():
    from wowbot.agent.active_skill_supervision import ActiveSkillSupervisionStep
    agent, executor = setup("OBJECT_USE")
    verified = []
    def verify(*args, **kwargs):
        verified.append(args[2].state["is_casting"])
        return ActiveSkillSupervisionStep(commands=(Command("BIND", "INTERACTTARGET"),))
    agent.active_skill_supervisor.step = verify
    payload, vision = control_sample(agent, 10.04, 1)
    payload["is_casting"] = True
    result = agent.parallel_control.tick(payload, 10.04, vision, 10.04)
    assert verified == [True] and result["reason"] == "cast_hold"
    assert not any(c.binding == "INTERACTTARGET" for c in executor.commands)


@pytest.mark.parametrize("field", ["is_casting", "is_channeling"])
def test_real_object_verifier_does_not_mark_an_undispatched_click_sent_during_cast(field):
    from wowbot.skills.object_use import ObjectUseSkill
    agent, executor = setup("OBJECT_USE")
    params = {"x": .55, "y": .6, "object_id": 77, "mouseover_tooltip": "Campfire", "quest_ids": [10]}
    agent.active_skill.state.intent.parameters.update(params)
    payload, vision = control_sample(agent, 10., 1)
    payload.update(mouseover={"object_id": 77, "tooltip": "Campfire", "quest_related": True, "quest_id": 10},
                   mouseover_sample_time=10., cursor_sample_time=10., cursor_position={"nx": .55, "ny": .6})
    ObjectUseSkill().begin(agent.active_skill.state, control_view(agent.world.state, payload, vision, 10.))
    context = agent.active_skill.state.skill_context["object_use"]
    payload.update(monotonic_time=10.1, fast_sequence=2, mouseover_sample_time=10.1, cursor_sample_time=10.1)
    payload[field] = True
    agent.parallel_control.tick(payload, 10.1, vision, 10.1)
    assert context["click_sent_at"] is None and context.get("used_at") is None
    assert not executor.commands
    payload.update(monotonic_time=10.2, fast_sequence=3, mouseover_sample_time=10.2, cursor_sample_time=10.2)
    payload[field] = False
    agent.parallel_control.tick(payload, 10.2, vision, 10.2)
    assert context["click_sent_at"] == 10.2
    assert [(c.kind, c.button) for c in executor.commands] == [("CLICK", "RIGHT")]


def test_item_use_hover_confirm_commands_are_not_lost_at_the_supervisor_boundary(monkeypatch):
    from wowbot.runtime import SkillResult, SkillStatus
    agent, executor = setup("USE_ON_TARGET")
    monkeypatch.setattr(agent.m0_skills, "verify", lambda *args: SkillResult(
        SkillStatus.RUNNING, commands=(Command("CLICK_CURRENT_CURSOR", button="RIGHT"),)))
    payload, vision = control_sample(agent, 10.04, 1)
    agent.parallel_control.tick(payload, 10.04, vision, 10.04)
    assert any(c.kind == "CLICK_CURRENT_CURSOR" for c in executor.commands)


def test_fast_owner_does_not_hide_inspection_verification_or_an_expired_deadline():
    agent, _ = setup()
    payload, vision = control_sample(agent, 10.04, 1)
    agent.parallel_control.tick(payload, 10.04, vision, 10.04)
    assert agent.parallel_control.drives(agent.pending, 10.05)
    assert agent.parallel_control.drives(agent.pending, 10.03)  # caller clock preceded the pump
    assert not agent.parallel_control.drives(agent.pending, 11.)
    agent.pending.deadline = 10.05
    assert not agent.parallel_control.drives(agent.pending, 10.05)
    agent.pending.deadline = 40.
    agent.pending.proposal = agent.pending.proposal.make("INSPECT", "inspect", {})
    assert not agent.parallel_control.drives(agent.pending, 10.05)


def test_medium_fuses_observations_without_repeating_the_fast_owned_fsm(monkeypatch):
    agent, executor = setup()
    agent.set_goal("Questelj", 10.)
    agent.pending = attempt("VISUAL_APPROACH", {"guid": "henry", "track_id": "WORLD3D:npc"})
    agent.visual_approach_skill.begin(agent.active_skill.state, agent.world.state, "v0", 10.)
    payload, vision = control_sample(agent, 10.04, 1)
    agent.parallel_control.tick(payload, 10.04, vision, 10.04)
    calls = []
    original = agent.active_skill_supervisor.step
    monkeypatch.setattr(agent.active_skill_supervisor, "step", lambda *a, **kw: calls.append(kw) or original(*a, **kw))
    agent.tick(payload, 10.05)
    assert agent.world.latest.payload["fast_sequence"] == 1
    assert calls == []
    assert agent.pending is not None and agent.pending.action_id == "a"


@pytest.mark.parametrize("ui", ["vendor_ui", "taxi_ui", "loot_ui"])
def test_unrelated_modal_ui_stops_an_approach(ui):
    agent, executor = setup()
    payload, vision = control_sample(agent, 10.04, 1)
    payload[ui] = {"open": True}
    result = agent.parallel_control.tick(payload, 10.04, vision, 10.04)
    assert result["force_medium"] and executor.stops > 0
    assert not any(c.kind == "POINTER" for c in executor.commands)


def test_sensor_peek_never_consumes_medium_transition_mailbox():
    sensor = BufferedPixelSensor(SimpleNamespace())
    value = {"frame_id": "f", "monotonic_time": 10.}
    sensor.pending = sensor.latest_payload = (value, 10.)
    for _ in range(3):
        assert sensor.peek_latest(10.1)[0]["frame_id"] == "f"
    assert sensor.poll(10.1)["frame_id"] == "f"
    assert sensor.peek_latest(10.1) is not None
    assert sensor.peek_latest(10.6) is None
    sensor.close()
    assert sensor.peek_latest(10.1) is None


def test_atomic_resources_allow_legs_plus_attention_but_not_two_mouse_owners():
    arbiter = ResourceArbiter()
    assert arbiter.request("move", [Resource.LEGS], 40, 10.)
    assert arbiter.request("hover", [Resource.MOUSE], 20, 10.)
    assert arbiter.request("use", [Resource.MOUSE], 60, 10.01)
    assert not arbiter.request("hover", [Resource.MOUSE, Resource.ACTION_KEYS], 20, 10.02)
    assert "ACTION_KEYS" not in arbiter.snapshot(10.02)
    assert arbiter.snapshot(10.02)["LEGS"]["owner"] == "move"
    arbiter.revoke_all(10.03, "stop")
    assert arbiter.snapshot(10.03) == {}


def test_slow_advisory_recognition_never_blocks_lookup_or_returns_a_previous_epoch():
    entered, release = threading.Event(), threading.Event()
    def recognize(*args, **kwargs):
        entered.set()
        release.wait(2.)
        return [{"identity_key": "npc:42", "status": "CANDIDATE"}]
    worker = VisualRecognitionWorker(SimpleNamespace(recognize_visual=recognize), max_pending=2)
    worker.start()
    try:
        assert worker.lookup({"signature_id": "s"}, track_id="one", epoch=1, now=time.monotonic()) == []
        assert entered.wait(1.)
        for index in range(8):
            assert worker.lookup({"signature_id": "s"}, track_id=str(index), epoch=1, now=time.monotonic()) == []
        assert worker.snapshot()["pending"] <= 2
        assert worker.lookup({"signature_id": "s"}, track_id="one", epoch=2, now=time.monotonic()) == []
        release.set()
        deadline = time.monotonic()+1.
        while worker.snapshot()["completed"] < 2 and time.monotonic() < deadline:
            time.sleep(.005)
        assert all(key[0] == 2 for key in worker._cache)
    finally:
        release.set()
        worker.close()


@pytest.mark.parametrize("sensor_stack", ["direct", "hub", "buffered_hub"])
def test_control_pump_keeps_advancing_while_medium_observation_work_is_blocked(sensor_stack):
    start = time.monotonic()
    agent, executor = setup(now=start)
    agent.pending.started_at = start
    agent.pending.deadline = start+10.
    class Sensor:
        def __init__(self): self.sequence = 0
        def peek_latest(self, now):
            self.sequence += 1
            payload, _ = control_sample(agent, now, self.sequence)
            return payload, now
    vision_source = SimpleNamespace(peek_control=lambda now: control_sample(agent, now, int(now*1000))[1])
    source = Sensor()
    sensor = source
    if sensor_stack == "hub":
        sensor = SensorHub.for_primary(source)
    elif sensor_stack == "buffered_hub":
        pixel_source = SimpleNamespace(poll=lambda now: source.peek_latest(now)[0],
                                       health="streaming", frame=None)
        sensor = SensorHub.for_primary(BufferedPixelSensor(pixel_source, interval=.01))
    runtime = SimpleNamespace(agent=agent, executor=executor, sensor=sensor, perception=vision_source,
                              test_deadline=None, test_dialog_grace_deadline=None)
    pump = ParallelRuntimePump(runtime)
    entered, release = threading.Event(), threading.Event()
    def medium_work():
        entered.set()
        release.wait(2.)
    slow = threading.Thread(target=medium_work)
    slow.start()
    try:
        if hasattr(sensor, "start"):
            sensor.start()
        assert entered.wait(1.)
        assert pump.start()
        deadline = time.monotonic()+.4
        while agent.parallel_control.counts["VISUAL_APPROACH"] < 4 and time.monotonic() < deadline:
            time.sleep(.005)
        assert agent.parallel_control.counts["VISUAL_APPROACH"] >= 4
        assert not release.is_set()               # still blocked, control is not
        assert any(c.kind == "POINTER" for c in executor.commands)
        assert sum(c.binding == "MOVEFORWARD" for c in executor.commands) >= 2
    finally:
        pump.close()
        if hasattr(sensor, "close"):
            sensor.close()
        release.set()
        slow.join(1.)
    assert not pump.active and not agent.parallel_control.enabled


@pytest.mark.parametrize("boundary", ["foreground", "deadline", "sensor"])
def test_independent_pump_respects_safety_even_when_medium_does_not_run(boundary):
    agent, executor = setup()
    backend = SimpleNamespace(emergency_pressed=lambda: False,
                              is_selected_foreground=lambda: boundary != "foreground")
    executor.backend = backend
    payload, _ = control_sample(agent, 10., 1)
    runtime = SimpleNamespace(agent=agent, executor=executor,
        sensor=SimpleNamespace(peek_latest=lambda now: None if boundary == "sensor" else (payload, 10.)),
        perception=None, test_deadline=10. if boundary == "deadline" else None, test_dialog_grace_deadline=None)
    pump = ParallelRuntimePump(runtime)
    pump.step(10.1)
    assert executor.stops > 0 and not any(c.kind == "POINTER" for c in executor.commands)
    assert pump.wake_medium.is_set()
