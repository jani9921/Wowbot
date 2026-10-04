"""Live 2026-10-04 (Giant Boar, user): the own boar + rider box (y .32-.59)
was not recognised as "self" -- the fixed lower-centre band only fits the
default on-foot camera -- so the selected Monstrous Cadaver's box became the
own boar, Trample fired at nothing and steering never faced the cadaver.
The avatar must be known "regardless of everything" (zoom, mount, vehicle)
without masking a unit standing in front of it.  Also: every quest vehicle
differs, so the ability use mode is generic (learned > tooltip > range)."""
from wowbot.agent.models import Goal, Observation, Proposal
from wowbot.agent.planner import Planner
from wowbot.agent.self_avatar import SelfAvatarIdentifier, is_self_avatar_box
from wowbot.agent.skills import SkillRegistry
from wowbot.agent.vehicle_abilities import (CLOSE, FORWARD_DASH, TARGETED, ability_mode,
                                            choose_attack_action, learn_effect)
from wowbot.agent.visual_approach import VisualApproachController
from wowbot.agent.world import WorldModel


def box(track, left, top, right, bottom, *, at=1., lifecycle="ACTIVE", kind="unknown_subject_candidate"):
    """A state World3D candidate from a top-left normalised box."""
    return {"track_id": track, "source": "WORLD3D", "kind": kind, "detector_kind": kind,
            "x": (left+right)/2, "y": 1-(top+bottom)/2, "bbox_width_fraction": right-left,
            "bbox_height_fraction": bottom-top, "observed_at": at, "lifecycle": lifecycle,
            "confidence": .7, "inspectable": True, "appearance": {},
            "bbox": {"left": left*843, "top": top*475, "right": right*843, "bottom": bottom*475}}


def state(*candidates, orientation=0., **extra):
    return {"visual_candidates": list(candidates), "orientation": orientation,
            "character_name": "Hero", "character_guid": "Player-1", "monotonic_time": 10., **extra}


# ------------------------------------------------------------------ self avatar
def test_boar_and_zoomed_out_avatar_are_self_by_focus_geometry():
    boar = box("WORLD3D:1", .445, .324, .552, .585)          # live vehicle camera
    small = box("WORLD3D:2", .487, .47, .513, .58)            # zoomed far out
    for avatar in (boar, small):
        current = state(avatar)
        assert SelfAvatarIdentifier().update(current) == [avatar["track_id"]]
        assert is_self_avatar_box(avatar) and avatar["inspectable"] is False


def test_unit_standing_in_front_stays_visible():
    avatar = box("WORLD3D:1", .461, .474, .536, .735)         # on foot, default zoom
    npc = box("WORLD3D:7", .482, .366, .521, .448)            # in front: drawn above the focus
    SelfAvatarIdentifier().update(state(avatar, npc))
    assert is_self_avatar_box(avatar)
    assert not is_self_avatar_box(npc) and npc["inspectable"] is True


def test_screen_fixed_box_under_turning_is_self_and_a_moving_one_is_vetoed():
    identifier = SelfAvatarIdentifier()
    # Over-shoulder camera: the avatar is right of centre, off the default focus.
    for step in range(4):
        avatar = box("WORLD3D:3", .60, .50, .66, .70, at=1.+step*.2)
        npc = box("WORLD3D:8", .20+step*.15, .40, .24+step*.15, .48, at=1.+step*.2)
        current = state(avatar, npc, orientation=step*.3)
        marked = identifier.update(current)
    assert marked == ["WORLD3D:3"]
    assert identifier.spot_source == "EGO_ROTATION_SCREEN_FIXED"
    assert "WORLD3D:8" in identifier.vetoed and not is_self_avatar_box(npc)


def test_hover_naming_the_player_confirms_the_box_and_it_follows_zoom():
    identifier = SelfAvatarIdentifier()
    avatar = box("WORLD3D:4", .58, .45, .66, .75)
    hovered = state(avatar, mouseover={"guid": "Player-1", "name": "Hero"},
                    cursor_position={"nx": .62, "ny": .40}, mouseover_sample_time=10.)
    assert identifier.update(hovered) == ["WORLD3D:4"]
    assert identifier.spot_source == "ADDON_MOUSEOVER_SELF"
    # Zooming out shrinks the box around the same spot; a new track id.
    zoomed = box("WORLD3D:9", .595, .52, .645, .70, at=2.)
    assert identifier.update(state(zoomed)) == ["WORLD3D:9"]


def test_hover_naming_another_unit_vetoes_a_focus_box():
    identifier = SelfAvatarIdentifier()
    npc = box("WORLD3D:5", .45, .40, .55, .70)
    identifier.update(state(npc, mouseover={"guid": "Creature-0-1-2-3-4-5", "name": "Guard"},
                            cursor_position={"nx": .50, "ny": .45}, mouseover_sample_time=10.))
    assert not is_self_avatar_box(npc)


def _world(*candidates, **extra):
    world = WorldModel()
    world.ingest(Observation.create({
        "session_id": "s", "timestamp": 1., "frame_id": "f", "monotonic_time": 1., "map_id": 1409,
        "orientation": 0., "position": {"x": .6, "y": .6}, "player_present": True,
        "character_guid": "Player-1", "character_name": "Hero", **extra}, 1.))
    world.projections["WORLD3D_TEST"] = {"visual_candidates": list(candidates)}
    world._state_projector.rebuild(world)
    return world


def test_selected_cadaver_box_is_never_the_own_boar_below_it():
    boar = box("WORLD3D:1", .445, .324, .552, .585)
    cadaver = box("WORLD3D:20", .49, .20, .52, .26)
    world = WorldModel()
    world.ingest(Observation.create({
        "session_id": "s", "timestamp": 1., "frame_id": "f", "monotonic_time": 1., "map_id": 1409,
        "orientation": 0., "position": {"x": .6, "y": .6}, "player_present": True,
        "character_guid": "Player-1", "target": {"guid": "ClientActor-3-1-79", "name": "Monstrous Cadaver"}}, 1.))
    world.last_target_boxes["ClientActor-3-1-79"] = {"track_id": "WORLD3D:20"}
    world.projections["WORLD3D_TEST"] = {"visual_candidates": [boar, cadaver]}
    world._state_projector.rebuild(world)
    anchor = world.state["target"]["screen_position"]
    assert anchor["track_id"] == "WORLD3D:20"
    assert abs(anchor["bbox_height_fraction"]-.06) < 1e-6
    # The cadaver's box vanishes: no fallback onto the boar below.
    world.projections["WORLD3D_TEST"] = {"visual_candidates": [box("WORLD3D:1", .445, .324, .552, .585, at=2.)]}
    world.state["target"].pop("screen_position", None)
    world._state_projector.rebuild(world)
    assert (world.state["target"].get("screen_position") or {}).get("track_id") != "WORLD3D:1"


# ------------------------------------------------------------- vehicle abilities
def test_use_mode_comes_from_learned_effect_then_text_then_range():
    dash = {"id": 1, "name": "Trample", "description": "Command the giant boar to charge forward."}
    aoe = {"id": 2, "name": "Stomp", "description": "Stomps the ground, damaging enemies within 8 yards."}
    bolt = {"id": 3, "name": "Arcane Bolt", "description": "Hurls a bolt.", "max_range": 30}
    plain = {"id": 4, "name": "Strike", "max_range": 0}
    assert [ability_mode(a) for a in (dash, aoe, bolt, plain)] == [FORWARD_DASH, CLOSE, TARGETED, CLOSE]
    learned = {}
    before = {"orientation": 0., "player_world_position": {"x": 0., "y": 0.}}
    after = {"player_world_position": {"x": 25., "y": 1.}}
    assert learn_effect(learned, 4, before, after) == FORWARD_DASH
    assert ability_mode(plain, learned) == FORWARD_DASH
    # Knocked back (moved backwards) is not a dash.
    assert learn_effect({}, 5, before, {"player_world_position": {"x": -15., "y": 0.}}) is None


def test_utility_buttons_are_not_attacks():
    state = {"vehicle_controls": True, "actionbar": [
        {"action": "ACTIONBUTTON1", "id": 9, "name": "Eject Passenger", "source": "VEHICLE_BAR"},
        {"action": "ACTIONBUTTON2", "id": 8, "name": "Cannon", "is_harmful": True, "source": "VEHICLE_BAR"}]}
    assert choose_attack_action(state)["id"] == 8


QUEST = {"quest_id": 55879, "title": "Ride of the Scientifically Enhanced Boar", "is_complete": False,
         "objectives": [{"description": "0/8 Monstrous Cadaver slain", "type": "KILL", "raw_type": "monster",
                         "current": 0, "required": 8, "is_complete": False}]}
TRAMPLE_BAR = {"page": 18, "kind": "OVERRIDE", "actions": [
    {"action": "ACTIONBUTTON1", "slot": 205, "index": 1, "id": 305556, "name": "Trample", "kind": "spell",
     "description": "Command the giant boar to charge forward, increasing its speed and sending any undead "
                    "in its way flying into the air.",
     "is_usable": True, "max_range": 0, "cooldown_remaining": 0, "source": "VEHICLE_BAR"}]}


def _riding(*candidates, **extra):
    return _world(*candidates, active_quests=[QUEST], vehicle_bar=TRAMPLE_BAR, in_vehicle=True,
                  world_map_open=False,
                  player_world_position={"x": 0., "y": 0., "instance_id": 2175,
                                         "coordinate_space": "WORLD_YARDS"}, **extra)


def _combat(world):
    planner = Planner(SkillRegistry())
    return planner.combat_policy.propose(world.planning_snapshot(1.), Goal.parse("Questelj", 1.), 1.,
                                         planner.quest).proposals


def test_nearer_hovered_cadaver_is_aimed_before_the_far_selected_one():
    far = box("WORLD3D:30", .30, .30, .32, .34)
    near = box("WORLD3D:31", .62, .30, .70, .45)
    world = _riding(box("WORLD3D:1", .445, .324, .552, .585), far, near,
                    target={"guid": "ClientActor-3-1-79", "name": "Monstrous Cadaver", "attackable": False})
    world.last_target_boxes["ClientActor-3-1-79"] = {"track_id": "WORLD3D:30"}
    world.mouseover_screen_anchors["ClientActor-3-1-80"] = {
        "guid": "ClientActor-3-1-80", "name": "Monstrous Cadaver", "x": .66, "y": .62,
        "track_id": "WORLD3D:31", "observed_at": 1., "sample_time": 1.}
    world._state_projector.rebuild(world)
    proposals = _combat(world)
    assert [p.skill for p in proposals] == ["VISUAL_APPROACH"]
    params = proposals[0].parameters
    assert params["purpose"] == "VEHICLE_AIM" and params["track_id"] == "WORLD3D:31"
    assert params["aim_guid"] == "ClientActor-3-1-80" and params["guid"] is None
    assert SkillRegistry().available(proposals[0], world)


def test_unit_right_ahead_is_lunged_through_but_the_own_boar_is_not():
    boar = box("WORLD3D:1", .445, .324, .552, .585)
    world = _riding(boar, target={"guid": "ClientActor-3-1-79", "name": "Monstrous Cadaver",
                                  "attackable": False})
    assert not any(p.skill == "VEHICLE_ABILITY" for p in _combat(world))
    blocker = box("WORLD3D:40", .46, .25, .54, .40)
    world = _riding(boar, blocker, target={"guid": "ClientActor-3-1-79", "name": "Monstrous Cadaver",
                                           "attackable": False})
    proposals = _combat(world)
    assert [p.skill for p in proposals] == ["VEHICLE_ABILITY"] and proposals[0].priority == 105


def test_lunge_verifies_the_vehicle_ability_and_is_learned():
    world = _riding()
    registry = SkillRegistry()
    proposal = Proposal.make("VEHICLE_ABILITY", "test", {
        "binding": "ACTIONBUTTON1", "spell_id": 305556, "quest_ids": [55879]}, priority=104)

    class Attempt:
        pass
    attempt = Attempt()
    attempt.proposal, attempt.baseline = proposal, {**world.state, "orientation": 0.}
    attempt.observation_id, attempt.started_at, attempt.deadline = "old", 0., 3.
    attempt.commands = ()
    world.ingest(Observation.create({
        "session_id": "s", "timestamp": 2., "frame_id": "g", "monotonic_time": 2., "map_id": 1409,
        "orientation": 0., "position": {"x": .6, "y": .6}, "player_present": True, "in_vehicle": True,
        "vehicle_bar": TRAMPLE_BAR, "active_quests": [QUEST],
        "events": [{"event_type": "SPELLCAST_FAILED", "sequence": 9,
                    "payload": {"spell_id": 305556, "unit": "player"}}],
        "player_world_position": {"x": 0., "y": 0., "instance_id": 2175}}, 2.))
    outcome, _ = registry.verify(attempt, world, 1.)
    assert outcome.value != "SUCCESS"          # a player FAILED event alone proves nothing
    world.ingest(Observation.create({
        "session_id": "s", "timestamp": 3., "frame_id": "h", "monotonic_time": 3., "map_id": 1409,
        "orientation": 0., "position": {"x": .6, "y": .6}, "player_present": True, "in_vehicle": True,
        "vehicle_bar": TRAMPLE_BAR, "active_quests": [QUEST],
        "player_world_position": {"x": 24., "y": 2., "instance_id": 2175}}, 3.))
    outcome, _ = registry.verify(attempt, world, 1.5)
    assert outcome.value == "SUCCESS"
    assert world.vehicle_ability_effects["305556"]["mode"] == FORWARD_DASH


def test_vehicle_aim_turns_in_place_then_hands_over():
    controller = VisualApproachController()
    target = box("WORLD3D:50", .70, .30, .76, .45)
    current = {"visual_candidates": [target], "monotonic_time": 1., "target": {}, "actionbar": []}
    assessment = controller.start({"purpose": "VEHICLE_AIM", "track_id": "WORLD3D:50"}, current, "o1", 1.)
    assert not assessment.terminal
    commands = controller.command(current, "o1", 1.)
    assert commands and all(c.binding != "MOVEFORWARD" for c in commands)
    aligned = {**current, "visual_candidates": [box("WORLD3D:50", .48, .30, .54, .45, at=1.2)]}
    assessment = controller.observe(aligned, "o2", 1.2)
    assert assessment.terminal and assessment.success and assessment.reason == "vehicle_attack_aligned"


def test_vehicle_actions_are_not_blocked_by_a_target_commitment():
    # Live 2026-10-04 17:40: 161 s of WAIT -- the TARGET commitment to one
    # cadaver rejected VEHICLE_ABILITY (not a TARGET skill).
    from wowbot.agent.autonomy_loop import AutonomousLoop
    from wowbot.agent.models import Proposal
    world = _riding(target={"guid": "ClientActor-3-1-79", "name": "Monstrous Cadaver", "attackable": False})
    loop = AutonomousLoop.__new__(AutonomousLoop)
    loop.commitment = type("C", (), {"kind": "TARGET", "target_guid": "ClientActor-3-1-79",
                                     "objective_refs": (), "reference": None})()
    lunge = Proposal.make("VEHICLE_ABILITY", "t", {"guid": None, "binding": "ACTIONBUTTON1"}, priority=105)
    aim = Proposal.make("VISUAL_APPROACH", "t", {"guid": None, "purpose": "VEHICLE_AIM", "track_id": "W:1"},
                        priority=103)
    other = Proposal.make("INSPECT", "t", {"track_id": "W:9"}, priority=86)
    assert loop._matching(lunge, world) and loop._matching(aim, world)
    assert not loop._matching(other, world)


def test_dash_fires_within_hysteresis_and_on_prototype_look_alikes():
    boar = box("WORLD3D:1", .445, .324, .552, .585)
    # 1.4x the aim tolerance off-centre: VEHICLE_AIM stopped turning, fire anyway.
    near_centre = box("WORLD3D:60", .522, .30, .562, .42)   # error .042, tolerance .03
    world = _riding(boar, near_centre,
                    target={"guid": "ClientActor-3-1-79", "name": "Monstrous Cadaver", "attackable": False})
    world.last_target_boxes["ClientActor-3-1-79"] = {"track_id": "WORLD3D:60"}
    world._state_projector.rebuild(world)
    assert [p.skill for p in _combat(world)] == ["VEHICLE_ABILITY"]
    # A never-hovered box that looks like confirmed cadavers is an aim.
    look_alike = box("WORLD3D:61", .75, .30, .79, .40)
    world = _riding(boar, look_alike)
    world._state_projector.rebuild(world)
    for item in world.state["visual_candidates"]:
        if item["track_id"] == "WORLD3D:61":
            item["appearance"]["prototype_lift"] = .9
    proposals = _combat(world)
    assert [p.skill for p in proposals] == ["VISUAL_APPROACH"]
    assert proposals[0].parameters["track_id"] == "WORLD3D:61"
    assert proposals[0].parameters["purpose"] == "VEHICLE_AIM"


def test_vehicle_action_preempts_an_unexecutable_target_retry_and_waits_out_the_cooldown():
    # Live 17:58: TARGET "click retry" of a dead committed cadaver for 11 s;
    # and a second press 0.5 s after the first ("Spell is not ready yet").
    from wowbot.agent.autonomy_loop import AutonomousLoop
    from wowbot.agent.models import Goal, Proposal
    boar = box("WORLD3D:1", .445, .324, .552, .585)
    ahead = box("WORLD3D:70", .48, .30, .52, .42)
    world = _riding(boar, ahead, target={"guid": "ClientActor-3-1-79", "name": "Monstrous Cadaver",
                                         "attackable": False})
    world.last_target_boxes["ClientActor-3-1-79"] = {"track_id": "WORLD3D:70"}
    world._state_projector.rebuild(world)
    proposals = _combat(world)
    assert [p.skill for p in proposals] == ["VEHICLE_ABILITY"]
    retry = Proposal.make("TARGET", "retry", {"guid": "ClientActor-3-1-79"}, priority=80)
    loop = AutonomousLoop()
    chosen = loop.choose([retry, *proposals], retry, Goal.parse("Questelj", 1.), world, 1.)
    assert chosen.skill == "VEHICLE_ABILITY"
    SkillRegistry().commands(proposals[0], world)        # press recorded
    assert [p.skill for p in _combat(world)] == ["WAIT"]
    world.last_received += 1.5
    assert [p.skill for p in _combat(world)] == ["VEHICLE_ABILITY"]


def test_vehicle_aim_refinds_a_flickering_low_confidence_target_after_a_turn():
    # Live 2026-10-04: a 14x26 px cadaver at 0.25 confidence came back under a
    # new track id while the boar turned; the >=0.30 rebind rule lost it.
    controller = VisualApproachController()
    first = box("WORLD3D:8", .60, .28, .62, .34)
    first["confidence"] = .25
    state = {"visual_candidates": [first], "monotonic_time": 1., "target": {}, "actionbar": [],
             "orientation": 1.0}
    controller.start({"purpose": "VEHICLE_AIM", "track_id": "WORLD3D:8"}, state, "o1", 1.)
    # Turned right by 0.1 rad: the world panned ~0.064 left; new id, low confidence.
    moved = box("WORLD3D:31", .536, .28, .556, .34, at=1.3)
    moved["confidence"] = .2
    decoy = box("WORLD3D:32", .30, .40, .35, .55, at=1.3)
    turned = {**state, "visual_candidates": [moved, decoy], "orientation": .9}
    assessment = controller.observe(turned, "o2", 1.3)
    assert assessment.reason != "visual_track_lost"
    assert controller.intent["track_id"] == "WORLD3D:31" and controller.track_rebindings == 1


def test_weak_box_exactly_where_a_confident_one_was_keeps_any_approach():
    # User 2026-10-04: a box below 0.30 at the same place as the previous
    # 0.60 box (camera moving / running) is the same target; a weak box
    # elsewhere is not.
    def run(new_left, new_conf):
        controller = VisualApproachController()
        first = box("WORLD3D:20", .40, .40, .46, .60)
        first["confidence"] = .6
        state = {"visual_candidates": [first], "monotonic_time": 1., "target": {}, "actionbar": [],
                 "orientation": 2.0}
        controller.start({"purpose": "IDENTIFY", "track_id": "WORLD3D:20"}, state, "o1", 1.)
        weak = box("WORLD3D:21", new_left, .40, new_left+.06, .60, at=1.2)
        weak["confidence"] = new_conf
        controller.observe({**state, "visual_candidates": [weak]}, "o2", 1.2)
        return controller.intent["track_id"]

    assert run(.405, .15) == "WORLD3D:21"        # same spot, same size, weak -> inherited
    assert run(.48, .15) == "WORLD3D:20"         # 0.08 away and weak -> not taken over


def test_after_a_range_error_a_huge_box_must_really_be_approached():
    # Live 2026-10-04 (Wrathion, a dragon): his box reached the screen bottom
    # from afar, VISUAL_APPROACH declared range at once, INTERACT answered
    # "You need to be closer" again and again.
    huge = box("WORLD3D:90", .40, .30, .62, .97)
    huge["confidence"] = .8
    state = {"visual_candidates": [huge], "monotonic_time": 1., "target": {"guid": "Creature-W"},
             "actionbar": []}
    fresh = VisualApproachController()
    assessment = fresh.start({"purpose": "INTERACT", "guid": "Creature-W", "track_id": "WORLD3D:90",
                              "ready_bbox_height": .13}, state, "o1", 1.)
    assert assessment.success                      # no range error yet: the old shortcut stands
    after_error = VisualApproachController()
    assessment = after_error.start({"purpose": "INTERACT", "guid": "Creature-W", "track_id": "WORLD3D:90",
                                    "ready_bbox_height": .5, "range_failures": 1}, state, "o1", 1.)
    assert not assessment.terminal
    commands = after_error.command(state, "o1", 1.)
    assert any(c.binding == "MOVEFORWARD" for c in commands)


def test_range_error_steps_follow_the_user_schedule():
    controller = VisualApproachController()
    assert controller.RANGE_ERROR_STEPS == (5, 3, 2)
    near = box("WORLD3D:91", .47, .30, .53, .70)
    near["confidence"] = .8
    state = {"visual_candidates": [near], "monotonic_time": 1., "target": {"guid": "Creature-W"}, "actionbar": []}
    controller.start({"purpose": "INTERACT", "guid": "Creature-W", "track_id": "WORLD3D:91",
                      "ready_bbox_height": .13, "range_failures": 2}, state, "o1", 1.)
    controller.forward_commands_total = 2
    assert not controller.observe({**state, "visual_candidates": [box("WORLD3D:91", .47, .30, .53, .70, at=1.1)]},
                                  "o2", 1.1).terminal
    controller.forward_commands_total = 3
    assert controller.observe({**state, "visual_candidates": [box("WORLD3D:91", .47, .30, .53, .70, at=1.2)]},
                              "o3", 1.2).success
