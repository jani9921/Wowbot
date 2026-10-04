"""Live 2026-10-04: riding the Giant Boar (Ride of the Scientifically Enhanced
Boar), the boar's own abilities replace the main bar and "0/8 Monstrous
Cadaver slain" must be done by charging with its first ability.  The agent
WAITed as a passenger (in_vehicle) and the exported bar showed the player's
own unusable spells."""
from wowbot.agent.models import Goal, Observation
from wowbot.agent.planner import Planner
from wowbot.agent.skills import SkillRegistry
from wowbot.agent.world import WorldModel

QUEST = {"quest_id": 55879, "title": "Ride of the Scientifically Enhanced Boar", "is_complete": False,
         "objectives": [{"description": "1/1 Ride the Giant Boar", "type": "KILL", "raw_type": "monster",
                         "current": 1, "required": 1, "is_complete": True},
                        {"description": "0/8 Monstrous Cadaver slain", "type": "KILL", "raw_type": "monster",
                         "current": 0, "required": 8, "is_complete": False}]}
PLAYER_BAR = [{"action": "ACTIONBUTTON1", "slot": 1, "id": 100, "name": "Charge", "kind": "spell",
               "is_usable": False, "is_harmful": True}]
BOAR_BAR = {"page": 18, "kind": "OVERRIDE", "actions": [
    {"action": "ACTIONBUTTON1", "slot": 205, "index": 1, "id": 305831, "name": "Boar Charge", "kind": "spell",
     "is_usable": True, "is_harmful": True, "in_range": True, "cooldown_remaining": 0, "source": "VEHICLE_BAR"}]}


def _world(**extra):
    world = WorldModel()
    world.ingest(Observation.create({
        "session_id": "v", "timestamp": 1., "frame_id": "f", "monotonic_time": 1., "map_id": 1409,
        "orientation": 0., "position": {"x": .6, "y": .6}, "player_present": True,
        "player_world_position": {"x": 0., "y": 0., "instance_id": 2175, "coordinate_space": "WORLD_YARDS"},
        "active_quests": [QUEST], "actionbar": PLAYER_BAR, "in_vehicle": True, "world_map_open": False,
        **extra}, 1.))
    return world


def test_vehicle_bar_becomes_the_actionbar():
    state = _world(vehicle_bar=BOAR_BAR).state
    assert state["vehicle_controls"] is True
    assert [a["name"] for a in state["actionbar"]] == ["Boar Charge"]
    assert state["player_actionbar"][0]["name"] == "Charge"


def test_controllable_vehicle_is_driven_not_waited_in():
    planner = Planner(SkillRegistry())
    proposals = planner.candidates(Goal.parse("Questelj", 1.), _world(vehicle_bar=BOAR_BAR), 1.)
    assert not (len(proposals) == 1 and proposals[0].reason.startswith("Járműben"))
    passenger = planner.candidates(Goal.parse("Questelj", 1.), _world(), 1.)
    assert [p.skill for p in passenger] == ["WAIT"]


def test_stale_vehicle_bar_is_dropped_once_out_of_the_vehicle():
    state = _world(vehicle_bar=BOAR_BAR, in_vehicle=False).state
    assert state["vehicle_controls"] is False and state["actionbar"][0]["name"] == "Charge"


def test_fast_range_refresh_lands_on_the_vehicle_ability():
    # The fast lane follows the vehicle page (addon 0.9.49): its entry for the
    # boar's charge must update the projected vehicle action, not be dropped.
    stale = {**BOAR_BAR, "actions": [{**BOAR_BAR["actions"][0], "in_range": False}]}
    state = _world(vehicle_bar=stale, actionbar_fast=[[305831, True, True, 0]]).state
    assert state["actionbar"][0]["name"] == "Boar Charge" and state["actionbar"][0]["in_range"] is True


TRAMPLE_BAR = {"page": 18, "kind": "OVERRIDE", "actions": [
    {"action": "ACTIONBUTTON1", "slot": 205, "index": 1, "id": 305556, "name": "Trample", "kind": "spell",
     "is_usable": True, "max_range": 0, "cooldown_remaining": 0, "source": "VEHICLE_BAR"}]}
CADAVER = {"guid": "ClientActor-3-4-2127", "name": "Monstrous Cadaver", "attackable": False, "dead": False}


def _combat(world):
    planner = Planner(SkillRegistry())
    return planner.combat_policy.propose(world.planning_snapshot(1.), Goal.parse("Questelj", 1.), 1.,
                                         planner.quest).proposals


def test_far_cadaver_is_driven_at_then_trampled_when_close():
    # Trample's name reads as a forward lunge: aim (turn only) at an
    # off-centre cadaver, use the ability once it is on the centre line.
    far = {**CADAVER, "screen_position": {"x": .85, "y": .40, "source": "BOUND_WORLD3D_TRACK",
                                          "coordinate_space": "CLIENT_BOTTOM_LEFT", "sample_time": 1.,
                                          "bbox_height_fraction": .04, "track_id": "WORLD3D:9"}}
    proposals = _combat(_world(vehicle_bar=TRAMPLE_BAR, target=far))
    assert [p.skill for p in proposals] == ["VISUAL_APPROACH"]
    assert proposals[0].parameters["purpose"] == "VEHICLE_AIM"
    ahead = {**far, "screen_position": {**far["screen_position"], "x": .51}}
    proposals = _combat(_world(vehicle_bar=TRAMPLE_BAR, target=ahead))
    assert [p.skill for p in proposals] == ["VEHICLE_ABILITY"]
    assert proposals[0].parameters["binding"] == "ACTIONBUTTON1"
    assert proposals[0].parameters["use_mode"] == "FORWARD_DASH"
    assert SkillRegistry().available(proposals[0], _world(vehicle_bar=TRAMPLE_BAR, target=ahead))
    assert SkillRegistry().commands(proposals[0], _world(vehicle_bar=TRAMPLE_BAR, target=ahead))[0].binding         == "ACTIONBUTTON1"


def test_hovered_cadaver_is_selected_while_riding():
    world = _world(vehicle_bar=TRAMPLE_BAR, mouseover=CADAVER, target={},
                   cursor_position={"nx": .6, "ny": .5, "sample_time": 1.})
    proposals = Planner(SkillRegistry()).candidates(Goal.parse("Questelj", 1.), world, 1.)
    assert any(p.skill == "TARGET" and p.parameters.get("guid") == CADAVER["guid"] for p in proposals)


def test_dismounted_vehicle_is_ridden_again_while_the_quest_is_open():
    # Live 2026-10-04 14:15: after leaving the world the boar was gone,
    # "1/1 Ride the Giant Boar" stayed complete and the agent WAITed.
    from wowbot.agent.quest_model import remount_quests
    quests = [QUEST]
    reopened = remount_quests(quests, in_vehicle=False)
    ride = reopened[0]["objectives"][0]
    assert ride["is_complete"] is False and ride["remount_required"] is True
    assert remount_quests(quests, in_vehicle=True) is quests
    done = {**QUEST, "is_complete": True}
    assert remount_quests([done], in_vehicle=False)[0]["objectives"][0]["is_complete"] is True
    world = _world(in_vehicle=False)
    ready = [obj.description for obj in world.quest_model.ready()]
    assert "1/1 Ride the Giant Boar" in ready
    # Mounting on the FAST lane closes it again at once.
    world.ingest(Observation.create({
        "session_id": "v", "timestamp": 2., "frame_id": "g", "monotonic_time": 2.,
        "transport_kind": "FAST", "telemetry_lane": "FAST_STATE", "in_vehicle": True}, 2.))
    assert "1/1 Ride the Giant Boar" not in [obj.description for obj in world.quest_model.ready()]


def test_single_use_vehicle_quest_is_not_reopened():
    from wowbot.agent.quest_model import remount_quests
    scout = {"quest_id": 55193, "is_complete": False, "objectives": [
        {"description": "1/1 Use Scout-o-Matic 5000 to scout the area", "raw_type": "monster",
         "type": "KILL", "current": 1, "required": 1, "is_complete": True}]}
    assert remount_quests([scout], in_vehicle=False)[0]["objectives"][0]["is_complete"] is True


STAGE_DONE = {**QUEST, "objectives": [
    {"description": "1/1 Ride the Giant Boar", "type": "KILL", "raw_type": "monster",
     "current": 1, "required": 1, "is_complete": True},
    {"description": "8/8 Monstrous Cadaver slain", "type": "KILL", "raw_type": "monster",
     "current": 8, "required": 8, "is_complete": True},
    {"description": "0/1 Torgok slain", "type": "KILL", "raw_type": "monster",
     "current": 0, "required": 1, "is_complete": False}]}


def _full(world, at, **extra):
    world.ingest(Observation.create({
        "session_id": "v", "timestamp": at, "frame_id": f"f{at}", "monotonic_time": at, "map_id": 1409,
        "orientation": 0., "position": {"x": .6, "y": .6}, "player_present": True,
        "player_world_position": {"x": 0., "y": 0., "instance_id": 2175, "coordinate_space": "WORLD_YARDS"},
        "actionbar": PLAYER_BAR, "world_map_open": False, **extra}, at))


def test_scripted_dismount_after_a_stage_is_not_ridden_again():
    # Live 2026-10-04 18:20 (user): 8/8 cadavers -> "0/1 Torgok slain"; the
    # server script took the player off the boar and the boar vanished.  The
    # agent must go on to Torgok, not look for the boar.
    world = WorldModel()
    _full(world, 1., active_quests=[QUEST], in_vehicle=True, vehicle_bar=BOAR_BAR)
    _full(world, 20., active_quests=[STAGE_DONE], in_vehicle=True, vehicle_bar=BOAR_BAR)
    _full(world, 38., active_quests=[STAGE_DONE], in_vehicle=False)
    ready = [obj.description for obj in world.quest_model.ready()]
    assert "1/1 Ride the Giant Boar" not in ready and "0/1 Torgok slain" in ready


def test_dismount_without_stage_progress_is_ridden_again():
    world = WorldModel()
    _full(world, 1., active_quests=[QUEST], in_vehicle=True, vehicle_bar=BOAR_BAR)
    _full(world, 60., active_quests=[QUEST], in_vehicle=False)     # logout / death
    assert "1/1 Ride the Giant Boar" in [obj.description for obj in world.quest_model.ready()]


def test_complete_vehicle_quest_leaves_the_vehicle():
    done = {**STAGE_DONE, "is_complete": True, "objectives": [
        {**objective, "is_complete": True, "current": objective["required"]}
        for objective in STAGE_DONE["objectives"]]}
    world = _world(vehicle_bar=BOAR_BAR, active_quests=[done])
    proposals = Planner(SkillRegistry()).candidates(Goal.parse("Questelj", 1.), world, 1.)
    assert [p.skill for p in proposals] == ["EXIT_VEHICLE"]
    assert SkillRegistry().available(proposals[0], world)
    assert SkillRegistry().commands(proposals[0], world)[0].binding == "VEHICLEEXIT"


def test_vehicle_is_left_when_no_script_takes_the_player_off_after_a_stage():
    # User 2026-10-04: some quests do not dismount the player by themselves.
    world = WorldModel()
    _full(world, 1., active_quests=[QUEST], in_vehicle=True, vehicle_bar=BOAR_BAR)
    _full(world, 20., active_quests=[STAGE_DONE], in_vehicle=True, vehicle_bar=BOAR_BAR)
    planner = Planner(SkillRegistry())
    _full(world, 30., active_quests=[STAGE_DONE], in_vehicle=True, vehicle_bar=BOAR_BAR)
    assert "EXIT_VEHICLE" not in [p.skill for p in planner.candidates(Goal.parse("Questelj", 30.), world, 30.)]
    _full(world, 61., active_quests=[STAGE_DONE], in_vehicle=True, vehicle_bar=BOAR_BAR)
    assert [p.skill for p in planner.candidates(Goal.parse("Questelj", 61.), world, 61.)] == ["EXIT_VEHICLE"]
    # When the local LLM read the rest as on-foot work, the grace is short.
    world2 = WorldModel()
    _full(world2, 1., active_quests=[QUEST], in_vehicle=True, vehicle_bar=BOAR_BAR)
    world2.quest_model.semantic_hints = {("55879", "torgok slain"): {"action": "TALK", "target": "Torgok"}}
    _full(world2, 20., active_quests=[STAGE_DONE], in_vehicle=True, vehicle_bar=BOAR_BAR)
    _full(world2, 29., active_quests=[STAGE_DONE], in_vehicle=True, vehicle_bar=BOAR_BAR)
    assert [p.skill for p in planner.candidates(Goal.parse("Questelj", 29.), world2, 29.)] == ["EXIT_VEHICLE"]


def test_fresh_start_after_the_vehicle_stage_does_not_look_for_the_vehicle():
    # Live 2026-10-04 18:25: agent started after the scripted dismount.
    world = _world(active_quests=[STAGE_DONE], in_vehicle=False)
    ready = [obj.description for obj in world.quest_model.ready()]
    assert ready == ["0/1 Torgok slain"]


def test_corpse_of_a_unique_kill_target_means_wait_for_its_respawn():
    # User 2026-10-04: "0/1 Torgok slain" -- if it is dead (someone killed
    # it), wait there for the respawn instead of wandering off.
    world = WorldModel()
    _full(world, 1., active_quests=[STAGE_DONE], in_vehicle=False)
    corpse = {"guid": "Creature-0-1-2175-1-162817-0000AAAA", "name": "Torgok", "is_dead": True,
              "is_attackable": False, "npc_id": 162817}
    _full(world, 2., active_quests=[STAGE_DONE], in_vehicle=False, mouseover=corpse,
          mouseover_sample_time=2., cursor_position={"nx": .5, "ny": .6, "sample_time": 2.},
          cursor_sample_time=2.)
    assert "55879:2" in world.respawn_watch
    planner = Planner(SkillRegistry())
    waits = [p for p in _combat(world) if p.skill == "WAIT"]
    assert waits and waits[0].parameters["waiting_for"] == ["UNIQUE_TARGET_RESPAWN"] and waits[0].priority == 82
    world.last_received += 181.
    assert not [p for p in _combat(world) if p.skill == "WAIT"]
    # Seen alive again: the watch is cleared and the normal hunt resumes.
    alive = {**corpse, "is_dead": False, "is_attackable": True}
    _full(world, 300., active_quests=[STAGE_DONE], in_vehicle=False, mouseover=alive,
          mouseover_sample_time=300., cursor_position={"nx": .5, "ny": .6, "sample_time": 300.},
          cursor_sample_time=300.)
    assert "55879:2" not in world.respawn_watch
