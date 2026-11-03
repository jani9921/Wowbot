"""Planner use of server-side quest markers and entity positions (offline).

Live 2026-10-19 14:47:51-14:48:48 (PID 21600, Ymir 70448): after two
accepts at Henry Garrick the server sent QuestGiverStatus 0x20000 (only an
in-progress quest left). The agent re-opened his window from a remembered
offer list, got a CONTINUE panel with no button point, and waited 55 s until
focus left WoW and the runtime demoted to MANUAL. Synthetic states below;
offline evidence only.
"""
from types import SimpleNamespace

from wowbot.agent.map_poi_planning import MapPoiPlanningPolicy, PACKET_GIVER_SOURCE
from wowbot.agent.quest_dialog_planning import QuestDialogPlanningPolicy
from wowbot.agent.quest_giver_evidence import friendly_npc_relevant, quest_search_allows_npc
from wowbot.agent.turnin_resolver import TurnInLocationKind, TurnInResolver

HENRY = "Creature-0-3768-2175-23933-156859-000055F3E4"
KEELA = "Creature-0-3768-2175-23933-156860-000055F3E4"
BJORN = "Creature-0-3768-2175-23933-154300-000055F3E4"


def marker(available=False, reward=False, incomplete=False, age=1.):
    return {"quest_available": available, "reward_ready": reward, "quest_incomplete": incomplete,
            "trivial_available": False, "future_quest": False, "status_flags": 0, "age": age}


def unit(guid, *, giver=None, x=None, npc_flags=None):
    value = {"guid": guid, "kind": "CREATURE", "entry_id": int(guid.split("-")[5]), "map_id": 2175}
    if giver is not None:
        value["quest_giver"] = giver
    if x is not None:
        value["position"] = {"x": x, "y": 0., "z": 10., "source": "PACKET_CREATE_MOVEMENT", "age": 30.}
    if npc_flags is not None:
        value["info"] = {"object_kind": "UNIT", "npc_flags": npc_flags}
    return value


def state(*entities, **changes):
    return {"monotonic_time": 100., "map_id": 1409, "active_quests": [],
            "player_world_position": {"x": 0., "y": 0., "z": 10., "instance_id": 2175,
                                      "coordinate_space": "WORLD_YARDS"},
            "packet_entities": {e["guid"]: e for e in entities}, **changes}


def target(guid, name="Henry Garrick"):
    return {"guid": guid, "name": name, "attackable": False, "dead": False}


def test_remembered_offer_is_dropped_when_the_server_shows_none_left():
    policy = QuestDialogPlanningPolicy()
    policy.pending_offers = {"guid": HENRY, "quest_ids": {"55881", "55763", "55764"}, "at": 90.}
    live = state(unit(HENRY, giver=marker(incomplete=True, age=2.)), target=target(HENRY),
                 active_quests=[{"quest_id": 55881}, {"quest_id": 55763}])
    assert policy._pending_offer_interact(live) is None and policy.pending_offers is None


def test_a_marker_older_than_the_offer_memory_does_not_decide():
    policy = QuestDialogPlanningPolicy()
    policy.pending_offers = {"guid": HENRY, "quest_ids": {"55881", "55764"}, "at": 98.}
    live = state(unit(HENRY, giver=marker(incomplete=True, age=5.)), target=target(HENRY),
                 active_quests=[{"quest_id": 55881}])
    proposal = policy._pending_offer_interact(live)
    assert proposal is not None and proposal.skill == "INTERACT"


def test_turn_in_follow_up_talks_again_only_when_the_server_shows_a_new_quest():
    for giver, expected in ((marker(available=True), "INTERACT"), (marker(), None)):
        policy = QuestDialogPlanningPolicy()
        policy.turned_in_at = {"guid": HENRY, "quest_id": "55196", "at": 95., "left": False}
        proposal = policy._follow_up_interact(state(unit(HENRY, giver=giver), target=target(HENRY)),
                                              False, "")
        assert (proposal.skill if proposal else None) == expected


def test_server_marker_decides_npc_relevance_over_vision_and_pins():
    live = state(unit(HENRY, giver=marker(available=True)), unit(BJORN, giver=marker()))
    assert quest_search_allows_npc(live, HENRY) is True
    assert quest_search_allows_npc(live, BJORN) is False
    questing = {**live, "active_quests": [{"quest_id": 55881, "is_complete": False}]}
    assert friendly_npc_relevant(questing, HENRY, ["INTERACT_OBJECT_ONLY"]) is True
    assert friendly_npc_relevant(questing, BJORN, ["INTERACT_OBJECT_ONLY"]) is False
    ready = state(unit(KEELA, giver=marker(reward=True)),
                  active_quests=[{"quest_id": 55764, "is_complete": True}])
    assert friendly_npc_relevant(ready, KEELA, []) is True


def test_npc_without_the_questgiver_flag_is_never_a_quest_npc():
    live = state(unit(BJORN, npc_flags=0x80))       # vendor only
    assert quest_search_allows_npc(live, BJORN) is False
    unknown = state()                                # Ymir off: previous evidence chain
    assert quest_search_allows_npc(unknown, BJORN) is False  # no pin, no symbol, no memory


def test_server_giver_replaces_its_pin_with_the_exact_unit_position():
    pin = {"quest_id": 55881, "is_campaign": True, "coordinate_space": "WORLD_YARDS",
           "world_position": {"coordinate_space": "WORLD_YARDS", "x": 60., "y": 20., "instance_id": 2175}}
    live = state(unit(HENRY, giver=marker(available=True), x=40.),
                 map_pois={"available_quests": [pin]},
                 reference_knowledge={"quests": {"55881": {"quest_roles": [
                     {"npc_id": 156859, "quest_id": 55881, "role": "QUEST_STARTER"}]}}})
    moves = MapPoiPlanningPolicy().quest_giver_moves(SimpleNamespace(state=live), now=100.)
    assert len(moves) == 1
    params = moves[0].parameters
    assert params["server_entity_guid"] == HENRY and params["location_source"] == PACKET_GIVER_SOURCE
    assert "target_guid" not in params     # navigation would treat it as a selected-unit approach
    assert (params["x"], params["z"], params["is_campaign"]) == (40., 10., True)


def test_server_giver_without_any_pin_is_a_pickup_when_the_log_is_empty():
    live = state(unit(HENRY, giver=marker(available=True), x=40.))
    (move,) = MapPoiPlanningPolicy().quest_giver_moves(SimpleNamespace(state=live), now=100.)
    assert move.skill == "MOVE" and move.parameters["server_entity_guid"] == HENRY


def test_selected_unit_with_a_server_quest_is_spoken_to():
    live = state(unit(HENRY, giver=marker(available=True), x=8.), target={**target(HENRY), "npc_id": 156859})
    (proposal,) = MapPoiPlanningPolicy().quest_giver_moves(SimpleNamespace(state=live), now=100.)
    assert proposal.skill == "INTERACT" and proposal.parameters["guid"] == HENRY


def test_turn_in_resolver_uses_the_server_yellow_marker_for_the_known_ender():
    live = state(unit(KEELA, giver=marker(reward=True), x=30.), unit(HENRY, giver=marker(reward=True), x=5.),
                 active_quests=[{"quest_id": 55764, "is_complete": True},
                                {"quest_id": 55196, "is_complete": True}],
                 reference_knowledge={"quests": {"55764": {"quest_roles": [
                     {"npc_id": 156860, "quest_id": 55764, "role": "QUEST_ENDER"}]}}})
    resolution = TurnInResolver().locate(SimpleNamespace(quest_id="55764", known_locations=()), live)
    assert resolution.kind is TurnInLocationKind.TURN_IN_LOCATION and resolution.entity_guid == KEELA
    # 3 yd + facing: the Interact key (4 yd) reaches the ender on arrival.
    assert resolution.location["x"] == 30. and resolution.location["stop_distance"] == 3.
    assert resolution.location["face_on_arrival"] is True
    # Two finished quests, two yellow units, no known ender: never guessed.
    unknown = TurnInResolver().locate(SimpleNamespace(quest_id="55196", known_locations=()), live)
    assert unknown.entity_guid is None


def test_unambiguous_single_turn_in_needs_no_reference():
    live = state(unit(HENRY, giver=marker(reward=True), x=12.),
                 active_quests=[{"quest_id": 55196, "is_complete": True}])
    resolution = TurnInResolver().locate(SimpleNamespace(quest_id="55196", known_locations=()), live)
    assert resolution.entity_guid == HENRY


def _planner_world(t, sample, ui):
    from wowbot.agent.models import Observation
    from wowbot.agent.world import WorldModel
    world = WorldModel()
    world.ingest(Observation.create({
        "session_id": "s", "timestamp": t, "frame_id": f"f{t}", "monotonic_time": t, "map_id": 1409,
        "orientation": 0., "position": {"x": .5, "y": .5}, "player_present": True,
        "player_world_position": {"x": 0., "y": 0., "instance_id": 2175, "coordinate_space": "WORLD_YARDS"},
        "active_quests": [], "world_map_open": False, "target": target(HENRY),
        "quest_ui": ui, "quest_ui_open": True, "state_sample_time": sample}, t))
    return world


def test_continue_panel_without_a_button_point_is_closed_not_waited_on():
    from wowbot.agent.models import Goal
    from wowbot.agent.planner import Planner
    from wowbot.agent.skills import SkillRegistry
    ui = {"open": True, "action": "CONTINUE", "quest_id": 0, "entries": [], "x": 0, "y": 0}
    planner, goal = Planner(SkillRegistry()), Goal.parse("Questelj", 1.)
    assert [p.skill for p in planner.candidates(goal, _planner_world(1., 1., ui), 1.)] == ["WAIT"]
    late = planner.candidates(goal, _planner_world(7.5, 7., ui), 7.5)
    assert [p.skill for p in late] == ["CLOSE_DIALOG"]
    clickable = {**ui, "x": .5, "y": .7}
    held = planner.candidates(goal, _planner_world(7.5, 7., clickable), 7.5)
    assert "CLOSE_DIALOG" not in [p.skill for p in held]


def test_focus_loss_records_what_took_the_foreground_and_the_demotion():
    from wowbot.agent.models import Mode
    from wowbot.agent.runtime_safety_phase import enforce_runtime_safety
    modes = []
    runtime = SimpleNamespace(agent=SimpleNamespace(mode=Mode.FULL_AI), _foreground_suspended=False,
                              _not_foreground_since=None, executor=SimpleNamespace(stop_movement=lambda: None),
                              mode=modes.append)
    backend = SimpleNamespace(emergency_pressed=lambda: False, is_selected_foreground=lambda: False,
                              foreground_owner=lambda: {"pid": 14688, "process": "explorer.exe",
                                                        "window_present": True})
    enforce_runtime_safety(runtime, backend, 10.)
    assert runtime.foreground_loss == {"at": 10., "demoted": False, "pid": 14688,
                                       "process": "explorer.exe", "window_present": True}
    enforce_runtime_safety(runtime, backend, 12.)
    enforce_runtime_safety(runtime, backend, 25.5)
    assert modes == ["MANUAL"] and runtime.foreground_loss["demoted"] is True
