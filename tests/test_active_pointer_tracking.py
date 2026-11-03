"""Pointer following shares active-skill ownership, not its movement budget."""
import pytest

from test_agent_core import state
from wowbot.agent.engine import AutonomousAgent
from wowbot.agent.executor import RecordingExecutor
from wowbot.agent.models import Attempt, Command, Observation, Outcome, Prediction, Proposal
from wowbot.agent.pointer_tracking import follow_pointer
from wowbot.agent.visual_approach import VisualApproachController
from wowbot.agent.vision_seek import SeekVisualCueController, SeekVisualCuePhase


def box(now=10., x=.55, **extra):
    return {"source": "WORLD3D", "track_id": "WORLD3D:npc", "observed_at": now,
            "x": x, "y": .6, "confidence": .8, "lifecycle": "ACTIVE",
            "detector_kind": "unknown_subject_candidate", "bbox_height_fraction": .06,
            "stable_frames": 5, "visual_relations": [{"type": "ABOVE", "belief": "SUPPORTED"}],
            **extra}


def scene(now=10., x=.55, **extra):
    return state(now, target={"guid": "henry", "attackable": False},
                 visual_candidates=[box(now, x)], cursor_position={"nx": .2, "ny": .3}, **extra)


def attempt(skill, params):
    return Attempt("a", Proposal.make(skill, "pointer test", params), {}, "o", 10., 40., (),
                   Prediction("p", "a", "pointer test", 10., 40., "o"))


def test_servo_can_follow_and_steer_on_every_distinct_frame():
    controller = VisualApproachController()
    controller.start({"guid": "henry", "purpose": "INTERACT", "track_id": "WORLD3D:npc"},
                     scene(), "v0", 10.)
    for index in range(12):
        now, x = 10.+index*.04, .55+index*.004
        current = scene(now, x)
        controller.observe(current, f"v{index+1}", now)
        pointer = controller.follow_pointer_command(current, now)
        assert pointer.kind == "POINTER" and pointer.x == x
        commands = controller.command(current, f"v{index+1}", now)
        assert any(command.binding == "MOVEFORWARD" for command in commands)
    assert controller.pointer_hovers == 12


def test_pointer_is_limited_to_thirty_hz_and_deduplicates_delayed_cursor_samples():
    context = {}
    assert follow_pointer(context, scene(), "WORLD3D:npc", 10.) is not None
    assert follow_pointer(context, scene(10.01, .6), "WORLD3D:npc", 10.01) is None
    assert follow_pointer(context, scene(10.04, .6), "WORLD3D:npc", 10.04).x == .6
    assert follow_pointer(context, scene(10.08, .6), "WORLD3D:npc", 10.08) is None


@pytest.mark.parametrize("change", [
    {"observed_at": 9.}, {"observed_at": 11.}, {"observed_at": None},
    {"coasting": True}, {"lifecycle": "OCCLUDED"}, {"lifecycle": "LOST_TEMPORARY"},
    {"self_player_avatar": True}, {"visual_identity": {"kind": "SELF_PLAYER"}},
    {"x": .99}, {"x": float("nan")}, {"track_id": "WORLD3D:other"},
])
def test_pointer_does_not_follow_invalid_or_other_tracks(change):
    current = scene()
    current["visual_candidates"] = [box(**change)]
    assert follow_pointer({}, current, "WORLD3D:npc", 10.) is None


@pytest.mark.parametrize("blocked", [
    {"quest_ui_open": True}, {"quest_ui": {"open": True}}, {"gossip_open": True},
    {"gossip_ui": {"open": True}}, {"world_map_open": True}, {"loading": True},
    {"input_blocked": True}, {"player_present": False}, {"is_dead": True}, {"is_ghost": True},
])
def test_no_world_pointer_over_an_open_ui_or_unsafe_client(blocked):
    assert follow_pointer({}, scene(**blocked), "WORLD3D:npc", 10.) is None


@pytest.mark.parametrize("skill", ["MOVE", "FOLLOW", "REACH_OBJECT", "REACH_LOCATION", "INSPECT"])
def test_engine_tracks_only_the_explicit_active_skill_target(skill):
    executor = RecordingExecutor()
    agent = AutonomousAgent(executor)
    agent.pending = attempt(skill, {"source": "WORLD3D", "track_id": "WORLD3D:npc"})
    agent.world.state = scene()
    agent._steer_object_lock(10.)
    agent.world.state = scene(10.04, .58)
    agent._steer_object_lock(10.04)
    assert [(c.kind, c.x) for c in executor.commands] == [("POINTER", .55), ("POINTER", .58)]
    assert executor.stops == 0


def test_engine_uses_the_canonical_per_attempt_servo_not_a_second_mouse_owner():
    executor = RecordingExecutor()
    agent = AutonomousAgent(executor)
    params = {"guid": "henry", "track_id": "WORLD3D:npc", "purpose": "INTERACT"}
    agent.pending = attempt("VISUAL_APPROACH", params)
    active = agent.active_skill.state
    agent.visual_approach_skill.begin(active, scene(), "v0", 10.)
    agent.world.state = scene(10.04, .58)
    agent._steer_object_lock(10.04)
    assert executor.commands[-1].kind == "POINTER" and executor.commands[-1].x == .58
    active.skill_context["visual_approach_controller"].observe(agent.world.state, "v1", 10.04)
    commands = active.skill_context["visual_approach_controller"].command(agent.world.state, "v1", 10.04)
    assert any(command.binding == "MOVEFORWARD" for command in commands)


@pytest.mark.parametrize("skill,key", [("INTERACT", "interaction"), ("TALK", "interaction"), ("LOOT", "loot")])
def test_nested_navigation_approach_keeps_its_own_target_under_the_pointer(skill, key):
    executor = RecordingExecutor()
    agent = AutonomousAgent(executor)
    agent.pending = attempt(skill, {"guid": "henry", "track_id": "WORLD3D:npc"})
    agent.active_skill.state.skill_context[key] = {"approach_request": {"kind": "WORLD_ENTITY"}}
    agent.world.state = scene()
    agent._steer_object_lock(10.)
    assert executor.commands[-1].kind == "POINTER" and executor.commands[-1].x == .55


def test_selected_guid_change_or_combat_stops_following_friendly_npc():
    executor = RecordingExecutor()
    agent = AutonomousAgent(executor)
    agent.pending = attempt("MOVE", {"guid": "henry", "track_id": "WORLD3D:npc"})
    current = scene()
    current["target"] = {"guid": "kee-la"}
    assert agent._active_target_pointer(current, 10.) == (True, None)
    assert agent._active_target_pointer(scene(is_in_combat=True), 10.) == (True, None)
    assert not executor.commands


def test_continuous_pointer_does_not_hide_a_late_contradictory_guid():
    controller = VisualApproachController()
    controller.start({"guid": "henry", "purpose": "INTERACT", "track_id": "WORLD3D:npc"},
                     scene(), "v0", 10.)
    controller.follow_pointer_command(scene(), 10.)
    current = scene(10.2, .58)
    controller.follow_pointer_command(current, 10.2)  # do not reset the feedback window here
    current.update(mouseover={"guid": "kee-la"}, mouseover_sample_time=10.18,
                   cursor_position={"nx": .58, "ny": .6}, cursor_sample_time=10.18)
    result = controller.observe(current, "v1", 10.2)
    assert result.reason == "pointer_identity_names_another_unit"
    assert controller.follow_pointer_command(current, 10.24) is None


def test_npc_seek_follows_its_committed_box_while_waiting_for_mouseover():
    seek = SeekVisualCueController()
    def near(now=10., x=.55):
        current = scene(now, x)
        current["visual_candidates"][0]["bbox_height_fraction"] = .12
        return current
    seek.begin({"track_id": "WORLD3D:npc"}, near(), 10.)
    assert seek.observe(near(), "v0", 10.).phase == SeekVisualCuePhase.CANDIDATE_READY
    assert seek.command(near(), "v0", 10.)[0].kind == "HOVER"
    assert seek.observe(near(10.04, .58), "v1", 10.04).phase == SeekVisualCuePhase.CANDIDATE_READY
    assert seek.command(near(10.04, .58), "v1", 10.04)[0].x == .58
    stale = scene(10.08, .61)
    stale["visual_candidates"][0]["lifecycle"] = "OCCLUDED"
    assert seek.command(stale, "v2", 10.08) == ()


def test_inspect_verifies_the_current_follow_point_not_its_old_starting_pixel():
    from wowbot.agent.skills import SkillRegistry
    from wowbot.agent.world import WorldModel
    world = WorldModel()
    first = scene()
    world.ingest(Observation.create(first, 10.))
    inspection = attempt("INSPECT", {"source": "WORLD3D", "track_id": "WORLD3D:npc", "x": .55, "y": .6})
    inspection.baseline = first
    inspection.observation_id = world.latest.observation_id
    inspection.commands = (Command("HOVER", x=.55, y=.6),)
    inspection.pointer_follow = {"point": (.62, .6), "started_at": 10.1, "sent_at": 10.1}
    current = scene(10.2, .62)
    current.update(cursor_position={"nx": .62, "ny": .6}, mouseover={"tooltip": "Thick Cocoon"},
                   mouseover_sample_time=10.2)
    world.ingest(Observation.create(current, 10.2))
    assert SkillRegistry().verify(inspection, world, 10.2)[0] is Outcome.SUCCESS
    world.state["mouseover_sample_time"] = 10.
    assert SkillRegistry().verify(inspection, world, 10.2)[0] is Outcome.PENDING


def test_hover_confirmation_follows_without_a_click_or_resetting_its_retry_budget():
    from wowbot.skills.hover_confirm import hover_confirm_step
    context = {"hovered_at": 10., "hovers": 1, "track_id": "WORLD3D:npc", "hover_point": (.52, .6)}
    current = scene(10.04, .58)
    # Fresh EMPTY feedback permits following the moved box. Missing feedback
    # must instead give the initial HOVER its bounded acknowledgement window.
    current.update(mouseover={}, mouseover_sample_time=10.01)
    outcome, commands = hover_confirm_step(context, current, 10.04, expected_guid="henry", deadline=12.)
    assert outcome == "HOVER" and commands[0].kind == "POINTER" and commands[0].x == .58
    assert context["hovers"] == 1 and context["hovered_at"] == 10.
    current.update(mouseover={"guid": "henry"}, mouseover_sample_time=10.02)
    assert not any(c.kind.startswith("CLICK") for c in hover_confirm_step(
        context, current, 10.05, expected_guid="henry", deadline=12.)[1])
    current["mouseover_sample_time"] = 10.08
    assert hover_confirm_step(context, current, 10.08, expected_guid="henry", deadline=12.)[0] == "CLICK"
    assert hover_confirm_step(context, scene(12., .7), 12., expected_guid="henry", deadline=12.) == ("FAILED", ())


def test_hover_confirmation_stops_when_the_followed_box_names_another_guid():
    from wowbot.skills.hover_confirm import hover_confirm_step
    context = {"hovered_at": 10., "hovers": 1, "track_id": "WORLD3D:npc"}
    hover_confirm_step(context, scene(10.04, .58), 10.04, expected_guid="henry")
    current = scene(10.08, .6)
    current.update(mouseover={"guid": "kee-la"}, mouseover_sample_time=10.08)
    assert hover_confirm_step(context, current, 10.08, expected_guid="henry") == ("FAILED", ())


def test_object_use_follows_the_same_confirmed_outline_then_needs_a_new_hover_sample():
    from test_m1_object_use_skill import _active
    from wowbot.skills.object_use import ObjectUseSkill
    from wowbot.runtime import SkillStatus
    skill, active = ObjectUseSkill(), _active()
    def object_scene(now, x, cursor, sample):
        return {"monotonic_time": now, "mouseover_sample_time": sample, "cursor_sample_time": sample,
                "mouseover": {"object_id": 77, "tooltip": "Campfire", "quest_related": True, "quest_id": 10},
                "cursor_position": {"nx": cursor, "ny": .6},
                "visual_candidates": [box(now, x, candidate_labels=["quest_object_like"],
                                          bbox_width_fraction=.06, bbox_height_fraction=.1)]}
    first = object_scene(1., .4, .4, 1.)
    assert skill.begin(active, first).commands[0].kind == "HOVER"
    assert active.skill_context["object_use"]["track_id"] == "WORLD3D:npc"
    moved = object_scene(1.1, .46, .4, 1.)
    followed = skill.verify(active, moved, 1.1)
    assert followed.status is SkillStatus.RUNNING
    assert [(c.kind, c.x) for c in followed.commands] == [("POINTER", .46)]
    # Cursor arrived but its tooltip is still the pre-follow sample: no click.
    assert not skill.verify(active, object_scene(1.2, .46, .46, 1.), 1.2).commands
    confirmed = skill.verify(active, object_scene(1.3, .46, .46, 1.3), 1.3)
    assert [(c.kind, c.button) for c in confirmed.commands] == [("CLICK", "RIGHT")]


def test_interact_hover_follows_the_selected_npc_then_waits_for_a_post_follow_guid():
    from test_m0_interact_skill import active
    from wowbot.skills import InteractSkill
    skill, current = InteractSkill(), active()
    first = scene(1.)
    first["target"] = {"guid": "npc-1", "visual_track_id": "WORLD3D:npc",
                       "screen_position": {"x": .55, "y": .6}}
    assert skill.begin(current, first).commands[0].kind == "HOVER"
    moved = {**scene(1.04, .58), "target": first["target"]}
    assert skill.verify(current, moved, 1.04).commands[0].kind == "POINTER"
    moved.update(mouseover={"guid": "npc-1"}, mouseover_sample_time=1.01,
                 cursor_position={"nx": .58, "ny": .6})
    assert not skill.verify(current, moved, 1.05).commands
    moved["mouseover_sample_time"] = 1.08
    assert skill.verify(current, moved, 1.08).commands[0].binding == "INTERACTTARGET"


def test_following_repeated_moving_boxes_never_releases_the_real_scheduler_forward_lease(tmp_path):
    from test_input_scheduler import Backend
    from wowbot.agent.bindings import BindingsCache
    from wowbot.agent.executor import InputExecutor
    path = tmp_path / "bindings-cache.wtf"
    path.write_text('bind "W" "MOVEFORWARD"\n', encoding="utf-8")
    backend, context = Backend(), {}
    executor = InputExecutor(42, BindingsCache(path), backend)
    try:
        for index in range(12):
            now, x = 10.+index*.04, .55+index*.005
            executor.execute_movement((Command("BIND", "MOVEFORWARD", .08),))
            executor.execute((follow_pointer(context, scene(now, x), "WORLD3D:npc", now),))
            assert backend.down["W"] is True
        assert ("W", False) not in backend.calls
    finally:
        executor.close()


def test_object_lock_retains_identity_but_does_not_aim_a_stale_box():
    from test_quest_object_lock_20261014 import _box, _state
    from wowbot.agent.quest_object_lock import QuestObjectLock
    lock = QuestObjectLock()
    lock.update(_state([_box()]), 10.)
    assert lock.active
    assert lock.pointer_command(_state([], now=10.5), 10.5, "MOVE") is None
    assert lock.active                        # identity persistence is not stale aiming authority
