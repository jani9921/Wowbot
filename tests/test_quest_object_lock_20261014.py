"""User 2026-10-14: a found cocoon keeps the mouse -- tracked, never let go
except in combat (the attacker comes first).  Live 2026-10-14: SEEK found the
Thick Cocoon, the turn carried the cursor off it before the tooltip arrived,
and the search turned again."""
import math
from types import SimpleNamespace

from wowbot.agent.models import Proposal
from wowbot.agent.quest_object_lock import QuestObjectLock

QUEST = {"quest_id": 55639, "is_complete": False, "objectives": [
    {"objective_id": "55639:0", "description": "Trapped Expedition Member rescued from cocoons",
     "type": "INTERACT", "raw_type": "object", "current": 0, "required": 5, "is_complete": False}]}


def _box(track="WORLD3D:613", x=.6, y=.5, height=.39, observed_at=10.):
    return {"source": "WORLD3D", "track_id": track, "candidate_labels": ["quest_object_like"],
            "confidence": .8, "stable_frames": 5, "bbox_height_fraction": height,
            "x": x, "y": y, "observed_at": observed_at, "lifecycle": "ACTIVE"}


def _state(boxes=(), now=10., facing=1., **extra):
    return {"monotonic_time": now, "orientation": facing, "active_quests": [QUEST],
            "visual_candidates": list(boxes), "cursor_position": {"nx": .5, "ny": .5}, **extra}


def test_the_lock_takes_the_cocoon_and_keeps_the_same_track():
    lock = QuestObjectLock()
    lock.update(_state([_box()]), 10.)
    assert lock.active and lock.track_id == "WORLD3D:613"
    # A bigger box elsewhere does not steal the lock.
    lock.update(_state([_box("WORLD3D:700", height=.6), _box(x=.62)], 10.2), 10.2)
    assert lock.track_id == "WORLD3D:613" and lock.box["x"] == .62


def test_combat_releases_the_lock_and_it_comes_back_after():
    lock = QuestObjectLock()
    lock.update(_state([_box()]), 10.)
    lock.update(_state([_box()], is_in_combat=True), 11.)
    assert not lock.active and lock.release_reason == "combat"
    lock.update(_state([_box()], now=20.), 20.)
    assert lock.active


def test_a_lost_cocoon_is_released_after_two_seconds():
    lock = QuestObjectLock()
    lock.update(_state([_box()]), 10.)
    lock.update(_state([]), 11.5)
    assert lock.active                              # a short occlusion keeps it
    lock.update(_state([]), 12.1)
    assert not lock.active and lock.release_reason == "lost"


def test_no_lock_on_a_cocoon_the_spawns_say_is_not_at_hand():
    lock = QuestObjectLock()
    lock.update(_state([_box()]), 10., object_at_hand=lambda qid: False)
    assert not lock.active
    lock.update(_state([_box()]), 10., object_at_hand=lambda qid: None)
    assert lock.active


def test_a_credited_track_is_not_taken_again():
    lock = QuestObjectLock()
    lock.update(_state([_box()]), 10.)
    lock.release("credited", 10.5, spent=True)
    lock.update(_state([_box()]), 11.)
    assert not lock.active
    lock.update(_state([_box(), _box("WORLD3D:800", x=.3)]), 11.)
    assert lock.track_id == "WORLD3D:800"


def test_the_pointer_follows_the_box_and_compensates_the_turn():
    lock = QuestObjectLock()
    lock.update(_state([_box(x=.6, observed_at=10.)], facing=1.), 10.)
    command = lock.pointer_command(_state(facing=1.), 10., "MOVE")
    assert command.kind == "POINTER" and (command.x, command.y) == (.6, .5)
    # Rate limited.
    assert lock.pointer_command(_state(facing=1.), 10.01, "MOVE") is None
    # Turned left by 9 degrees since the box was seen: the world moved right.
    turned = lock.pointer_command(_state(facing=1.+math.radians(9.)), 10.2, "MOVE")
    assert abs(turned.x-(.6+.1)) < 1e-6
    # Not during skills that own the mouse.
    assert lock.pointer_command(_state(facing=1.), 11., "INSPECT") is None
    assert lock.pointer_command(_state(facing=1.), 11., "COMBAT") is None


def test_no_pointer_at_the_screen_edge_when_the_cocoon_turned_out_of_view():
    lock = QuestObjectLock()
    lock.update(_state([_box(x=.95, observed_at=10.)], facing=1.), 10.)
    assert lock.pointer_command(_state(facing=1.+math.radians(20.)), 10.2, "MOVE") is None


def test_other_hovers_and_camera_searches_wait_while_the_lock_holds():
    lock = QuestObjectLock()
    other = Proposal.make("INSPECT", "x", {"track_id": "WORLD3D:9"})
    mine = Proposal.make("SEEK_VISUAL_CUE", "cocoon", {"track_id": "WORLD3D:613"})
    sweep = Proposal.make("SEEK_VISUAL_CUE", "zone", {"purpose": "SEARCH_LOCAL_OBJECTIVE_AREA"})
    use = Proposal.make("OBJECT_USE", "use", {})
    move = Proposal.make("MOVE", "approach", {})
    assert not any(lock.holds_mouse(p) for p in (other, mine, sweep, use, move))
    lock.update(_state([_box()]), 10.)
    assert [lock.holds_mouse(p) for p in (other, mine, sweep, use, move)] == [True, False, True, False, False]


def test_the_engine_points_at_the_locked_cocoon_between_skills():
    from wowbot.agent.engine import AutonomousAgent
    from wowbot.agent.executor import RecordingExecutor
    executor = RecordingExecutor()
    agent = AutonomousAgent(executor)
    agent.world.state = _state([_box(x=.6)])
    agent._steer_object_lock(10.)               # no skill running (MOVE: the lock tests)
    assert [(c.kind, c.x, c.y) for c in executor.commands] == [("POINTER", .6, .5)]
    # A credit releases it (and the planner flow shares the same lock).
    flow = agent.planner.quest.location_policy.object_interaction
    assert flow.lock is agent.object_lock
    flow.note_result({"action_id": "u", "skill": "OBJECT_USE", "outcome": "SUCCESS"},
                     {**agent.world.state, "player_world_position": {"x": 1., "y": 2.}})
    assert not agent.object_lock.active and agent.object_lock.release_reason == "credited"


def test_seek_keeps_the_pointer_on_the_cocoon_and_waits_for_the_tooltip():
    from wowbot.agent.vision_seek import SeekVisualCueController
    seek = SeekVisualCueController()
    seek.begin({"purpose": "SEARCH_LOCAL_OBJECT", "search_capability": "SEARCH_LOCAL_OBJECT",
                "track_id": "WORLD3D:613", "quest_id": 55639,
                "expected_tooltips": ["cocoon"]}, _state([_box()]), 10.)
    state = _state([_box(observed_at=10.)])
    assert not seek.observe(state, "o1", 10.).terminal
    [hover] = seek.command(state, "o1", 10.)
    assert hover.kind == "HOVER" and (hover.x, hover.y) == (.6, .5)
    # The box slides (the character still turning): the pointer follows it.
    moved = _state([_box(x=.66, observed_at=10.2)], now=10.2)
    assert not seek.observe(moved, "o2", 10.2).terminal
    [follow] = seek.command(moved, "o2", 10.2)
    assert follow.kind == "POINTER" and follow.x == .66
    # 0.85 s used to end the search; the cocoon now gets 2.5 s for its tooltip.
    later = _state([_box(x=.66, observed_at=11.2)], now=11.2)
    assert not seek.observe(later, "o3", 11.2).terminal
    assert seek.observe(_state([_box(x=.66, observed_at=12.6)], now=12.6), "o4", 12.6).terminal


# --- "go there by the minimap, face it, soft target, then interact" -----------------

def _arrive(controller, facing, at, x=7.5):
    state = {"player_world_position": {"x": x, "y": 0.}, "orientation": facing,
             "monotonic_time": at}
    return controller.observe(state, f"o{at}", at), controller.command(state, f"o{at}", at)


def test_a_face_on_arrival_move_turns_toward_its_point_before_arriving():
    from wowbot.agent.movement_controller import ReachMovementController
    controller = ReachMovementController()
    destination = {"coordinate_space": "WORLD_YARDS", "x": 10., "y": 0., "stop_distance": 4.,
                   "face_on_arrival": True}
    controller.start(destination, {"player_world_position": {"x": 7., "y": 0.},
                                   "orientation": math.pi/2}, "o0", 0.)
    for at in (.1, .2, .3, .4, .5):
        result, commands = _arrive(controller, math.pi/2, at)
        if not result.terminal:
            break
    # Facing 90 deg left of the point: a right turn in place, never forward.
    assert not result.terminal and result.reason == "facing_destination_after_arrival"
    assert [c.binding for c in commands] == ["TURNRIGHT"]
    result, commands = _arrive(controller, .1, 1.)
    assert result.terminal and result.success


def test_without_face_on_arrival_or_at_an_intermediate_waypoint_it_arrives_at_once():
    from wowbot.agent.movement_controller import ReachMovementController
    for extra in ({}, {"face_on_arrival": True, "route_waypoint_final": False}):
        controller = ReachMovementController()
        controller.start({"coordinate_space": "WORLD_YARDS", "x": 10., "y": 0.,
                          "stop_distance": 4., **extra},
                         {"player_world_position": {"x": 7., "y": 0.}, "orientation": math.pi/2}, "o0", 0.)
        results = [_arrive(controller, math.pi/2, at)[0] for at in (.1, .2, .3, .4, .5)]
        assert any(r.terminal and r.success for r in results)
        assert not any(r.reason == "facing_destination_after_arrival" for r in results)


def test_facing_after_arrival_is_bounded():
    from wowbot.agent.movement_controller import ReachMovementController
    controller = ReachMovementController()
    controller.start({"coordinate_space": "WORLD_YARDS", "x": 10., "y": 0., "stop_distance": 4.,
                      "face_on_arrival": True},
                     {"player_world_position": {"x": 7., "y": 0.}, "orientation": math.pi}, "o0", 0.)
    results = [_arrive(controller, math.pi, at)[0] for at in (.1, .2, .3, .4, .5, 1., 2., 3.2)]
    assert results[-1].terminal and not results[-1].success
    assert results[-1].reason == "facing_failed"


def test_a_soft_interact_cocoon_is_used_with_the_interact_key_without_walking_closer():
    """User: face it, soft target, then interact.  6 yd from the cocoon's
    TDB spot the client already offers it as the soft-interact object."""
    from test_pit_run_20261014 import _pit_world
    from wowbot.agent.models import Goal
    from wowbot.agent.planner import Planner
    from wowbot.agent.skills import SkillRegistry
    from wowbot.query_ports import NavigationQueryPorts
    planner = Planner(SkillRegistry(), navigation_queries=NavigationQueryPorts(
        player_layer=lambda _state: 62.7))
    far = planner.quest.propose(_pit_world(81.8, -2272.2), Goal.parse("Questelj", 10.))
    approach = next(p for p in far if p.parameters.get("purpose") == "APPROACH_QUEST_OBJECT_SPAWN")
    assert approach.parameters["face_on_arrival"] is True
    cocoon = {"source_unit": "softinteract", "unit_type": "GAMEOBJECT", "name": "Thick Cocoon",
              "guid": "GameObject-0-1-2175-1-339568-1", "object_id": 339568}
    soft = planner.quest.propose(_pit_world(81.8, -2272.2, soft_targets=[cocoon]), Goal.parse("Questelj", 10.))
    assert not any(p.parameters.get("purpose") == "APPROACH_QUEST_OBJECT_SPAWN" for p in soft)
    use = next(p for p in soft if p.skill == "OBJECT_USE")
    assert use.parameters["binding"] == "INTERACTTARGET" and use.parameters["object_guid"] == cocoon["guid"]


# --- user: "before OBJECT_USE the mouse must be on the Thick Cocoon" ----------------

def test_the_lock_follows_a_moved_box_even_while_the_old_tooltip_names_the_cocoon():
    lock = QuestObjectLock()
    lock.update(_state([_box(x=.6)]), 10.)
    on_it = _state([_box(x=.62, observed_at=10.1)], now=10.1,
                   cursor_position={"nx": .6, "ny": .5},
                   mouseover={"quest_related": True, "quest_id": 55639})
    lock.update(on_it, 10.1)
    command = lock.pointer_command(on_it, 10.1, "WAIT")
    assert command.kind == "POINTER" and command.x == .62
    on_it["cursor_position"] = {"nx": .62, "ny": .5}
    assert lock.pointer_command(on_it, 10.2, "WAIT") is None


def _object_use_state(cursor, mouse):
    return {"monotonic_time": 10., "cursor_position": {"nx": cursor[0], "ny": cursor[1]},
            "cursor_sample_time": 10., "mouseover_sample_time": 10., "mouseover": mouse}


def test_object_use_follows_the_cursor_still_on_the_cocoon_instead_of_aborting():
    """The lock re-aimed the cursor on the same cocoon after planning: the
    use hovers the cursor's point (fresh tooltip still gates the click)."""
    from wowbot.skills.object_use import ObjectUseSkill
    from wowbot.runtime import SkillStatus
    params = {"x": .50, "y": .50, "object_id": 339568, "quest_ids": [55639], "mouseover_tooltip": "Thick Cocoon",
              "expected_tooltips": ["cocoon"]}
    state = SimpleNamespace(intent=SimpleNamespace(parameters=params, target_ref=None, objective_ref="55639:0"),
                            skill_type="OBJECT_USE", skill_context={}, started_at=10., phase=None)
    cocoon = {"tooltip": "Thick Cocoon", "object_id": 339568, "quest_related": True, "quest_id": 55639}
    result = ObjectUseSkill().begin(state, _object_use_state((.53, .51), cocoon))
    assert result.status is SkillStatus.RUNNING
    assert [(c.kind, c.x, c.y) for c in result.commands] == [("HOVER", .53, .51)]
    # The cursor moved off the cocoon: no use from a stale point.
    state.skill_context = {}
    stale = ObjectUseSkill().begin(state, _object_use_state((.53, .51), {"tooltip": "Rock"}))
    assert stale.status is SkillStatus.FAILURE


# --- user's manual test: F7 at the cocoon opens it (not facing away / no unit near) --

def _facing(x, y, tx=80.48, ty=-2279.52):
    return math.atan2(ty-y, tx-x) % math.tau


def test_the_interact_key_is_ready_at_the_spawn_facing_it_with_no_unit_soft_target():
    from test_pit_run_20261014 import _state as pit_state
    from wowbot.agent.object_interaction_flow import ObjectInteractionFlow
    flow = ObjectInteractionFlow()
    here = {**pit_state(x=81.5, y=-2277.5), "orientation": _facing(81.5, -2277.5)}
    spot = flow.tdb_use_spot(here, 55639, 62.7)
    assert flow.interact_key_ready(here, spot)
    # Facing away, a corpse/NPC as the soft-interact unit, or combat: no F7.
    away = ObjectInteractionFlow()
    assert not away.interact_key_ready({**here, "orientation": _facing(81.5, -2277.5)+math.pi}, spot)
    corpse = {"source_unit": "softinteract", "unit_type": "NPC", "name": "Barrow Spider", "is_dead": True}
    assert not ObjectInteractionFlow().interact_key_ready({**here, "soft_targets": [corpse]}, spot)
    assert not ObjectInteractionFlow().interact_key_ready({**here, "is_in_combat": True}, spot)
    # One attempt (8 s), then the mouse path for 30 s, then another try.
    assert flow.interact_key_ready({**here, "monotonic_time": 15.}, spot)
    assert not flow.interact_key_ready({**here, "monotonic_time": 25.}, spot)
    assert flow.interact_key_ready({**here, "monotonic_time": 49.}, spot)


def test_the_planner_presses_the_interact_key_at_the_cocoon_spawn():
    from test_pit_run_20261014 import _pit_world
    from wowbot.agent.models import Goal
    from wowbot.agent.planner import Planner
    from wowbot.agent.skills import SkillRegistry
    planner = Planner(SkillRegistry())
    world = _pit_world(81.5, -2277.5, orientation=_facing(81.5, -2277.5))
    proposals = planner.quest.propose(world, Goal.parse("Questelj", 10.))
    assert not any(p.parameters.get("activation_source") == "INTERACT_KEY_AT_SPAWN" for p in proposals)
    assert any(p.skill in {"INSPECT", "SEEK_VISUAL_CUE", "MOVE", "WAIT"} for p in proposals)


def test_the_skill_presses_the_interact_key_only_without_a_unit_soft_target():
    from wowbot.skills.object_use import ObjectUseSkill
    from wowbot.runtime import SkillStatus
    params = {"activation_source": "INTERACT_KEY_AT_SPAWN", "binding": "INTERACTTARGET",
              "quest_ids": [55639], "objective_id": "55639:0"}
    def begin(world):
        state = SimpleNamespace(intent=SimpleNamespace(parameters=params, objective_ref="55639:0"),
                                skill_context={}, started_at=10., phase=None)
        return ObjectUseSkill().begin(state, world)
    pressed = begin({"soft_targets": []})
    assert pressed.reason.value == "IDENTITY_UNCERTAIN" and not pressed.commands
    npc = {"source_unit": "softinteract", "unit_type": "NPC", "name": "Alaria"}
    assert begin({"soft_targets": [npc]}).status is SkillStatus.FAILURE
