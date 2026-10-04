from wowbot.agent.location_fallback import reference_destination
from wowbot.agent.movement_controller import ReachMovementController


def scene():
    row = dict(source="TDB_REFERENCE", source_sha256="test", npc_id=156626,
               world_map_id=2175, x=10., y=0., z=0., spawn_id=1, context={"PhaseId": "13845"},
               coordinate_space="WORLD_YARDS")
    return dict(target={"guid": "jaina", "npc_id": 156626}, orientation=0.,
                player_world_position={"x": 0., "y": 0., "z": 0., "instance_id": 2175},
                spawn_reference_candidates=[row]), row


def test_reference_requires_unique_local_identity_context():
    state, row = scene()
    assert reference_destination(state) == row
    state["spawn_reference_candidates"].append(dict(row, spawn_id=2))
    assert reference_destination(state) is None
    state["spawn_reference_candidates"] = [row]
    state["phase"] = 5
    assert reference_destination(state) is None
    del state["phase"]
    state["player_world_position"]["instance_id"] = 1609
    assert reference_destination(state) is None


def test_reference_reach_preserves_guid_and_does_not_invent_live_position():
    state, row = scene()
    controller = ReachMovementController()
    controller.start(dict(row, target_guid="jaina"), state, "1", 1)
    assert controller.command(state, "1", 1)[0].binding == "MOVEFORWARD"
    state["player_world_position"]["x"] = 7.
    assert controller.observe(state, "2", 2).success
    assert "world_position" not in state["target"]
    state["target"]["guid"] = "other"
    assert controller.observe(state, "3", 3).terminal
    assert not controller.command(state, "3", 3)


def test_map_location_precedes_db_fallback():
    from wowbot.agent.planner import QuestDomain
    from wowbot.agent.models import Goal
    from wowbot.agent.world import WorldModel
    state, row = scene()
    state.update(map_id=1609, session_id="test", ui_error="out of range",
                 quest_locations=[{"map_id":1609,"x":.5,"y":.6}], monotonic_time=1)
    state["target"].update(attackable=False, name="Jaina")
    world = WorldModel()
    world.state = state
    domain = QuestDomain()
    proposals = domain.propose(world, None)
    assert any(p.skill == "MOVE" for p in proposals)
    assert not any(p.parameters.get("source") == "TDB_REFERENCE" for p in proposals)
    domain.failed_map_locations.update(p.key for p in proposals if p.skill == "MOVE")
    domain.allow_db_fallback = True
    failed_proposals = domain.propose(world, None)
    assert any(p.parameters.get("source") == "TDB_REFERENCE" for p in failed_proposals)
    state["quest_locations"] = []
    proposals = domain.propose(world, None)
    assert any(p.skill == "REACH_OBJECT" and p.parameters.get("source") == "TDB_REFERENCE" for p in proposals)


def test_discovery_order_is_world3d_then_current_map_scan_then_db():
    from wowbot.agent.planner import Planner
    from wowbot.agent.models import Goal
    from wowbot.agent.skills import SkillRegistry
    from wowbot.agent.world import WorldModel
    state, row = scene()
    state.update(session_id="test:player-1", map_id=1409, ui_error="out of range",
                 world_map_open=False, monotonic_time=1, active_quests=[],
                 remembered_locations=[{"map_id": 1409, "x": .62, "y": .83,
                     "semantic_type": "QUEST_GIVER", "source": "WORLD_POINT_MEMORY",
                     "provenance": {"session_id":"test:player-1", "marker_associated":True,
                                    "observed_monotonic": .5}}])
    state["target"].update(attackable=False, dead=False, name="Jaina")
    model = WorldModel()
    model.state, model.session_id = state, state["session_id"]
    planner, goal = Planner(SkillRegistry()), Goal.parse("Questelj", 1.)
    first = planner.candidates(goal, model, 1.)
    assert first[0].skill == "OPEN_MAP"
    assert not any(p.parameters.get("source") == "TDB_REFERENCE" for p in first)

    state["world_map_open"] = True
    assert planner.candidates(goal, model, 2.)[0].skill == "WAIT"
    close = planner.candidates(goal, model, 20.)
    assert close[0].skill == "CLOSE_MAP"
    assert planner.map_inspection_status()["map_search_exhausted"] is True

    state["world_map_open"] = False
    fallback = planner.candidates(goal, model, 21.)
    assert fallback[0].skill == "REACH_OBJECT"
    assert fallback[0].parameters["source"] == "TDB_REFERENCE"
    assert planner.map_inspection_status()["search_stage"] == "DB_FALLBACK"


def test_identity_free_order_is_world3d_then_map_then_role_location_fallback():
    from wowbot.agent.planner import Planner
    from wowbot.agent.models import Goal
    from wowbot.agent.skills import SkillRegistry
    from wowbot.agent.world import WorldModel
    reference = dict(source="TDB_REFERENCE", source_sha256="digest", world_map_id=2175,
        x=10., y=0., z=0., distance_yards=10., coordinate_space="WORLD_YARDS",
        spawn_ids=[1, 2], npc_ids=[156626, 166782], quest_ids=[54951, 59929],
        role_hypothesis="QUEST_STARTER", identity_confirmed=False)
    state = dict(session_id="test:new", map_id=1409, target={}, active_quests=[],
        world_map_open=False, monotonic_time=1., orientation=0., is_in_combat=False,
        is_casting=False, state_age=0., position={"x": .5, "y": .5},
        player_world_position={"x": 0., "y": 0., "z": 0., "instance_id": 2175},
        quest_role_reference_candidates=[reference])
    model = WorldModel()
    model.state, model.session_id = state, state["session_id"]
    planner, goal = Planner(SkillRegistry()), Goal.parse("Questelj", 1.)
    assert planner.candidates(goal, model, 1.)[0].skill == "SEEK_VISUAL_CUE"
    planner.camera_search_step = 4
    assert planner.candidates(goal, model, 1.5)[0].skill == "OPEN_MAP"
    state["world_map_open"] = True
    assert planner.candidates(goal, model, 2.)[0].skill == "WAIT"
    assert planner.candidates(goal, model, 20.)[0].skill == "CLOSE_MAP"
    state["world_map_open"] = False
    fallback = planner.candidates(goal, model, 21.)[0]
    assert fallback.skill == "REACH_LOCATION"
    assert fallback.parameters["npc_ids"] == [156626, 166782]
    assert fallback.parameters["identity_confirmed"] is False


def test_map_that_scanned_empty_twice_is_not_reopened_on_every_context_reset():
    """Live 2026-10-01: the World Map CV found nothing on map 2175, yet each
    quest-progress context reset reopened the map 30 s later (~15 s lost per
    OPEN/WAIT/CLOSE cycle).  After two empty scans the map is not reopened."""
    from wowbot.agent.planner import Planner
    from wowbot.agent.models import Goal
    from wowbot.agent.skills import SkillRegistry
    from wowbot.agent.world import WorldModel
    state = dict(session_id="test:new", map_id=1409, target={}, active_quests=[],
        world_map_open=False, monotonic_time=1., orientation=0., is_in_combat=False,
        is_casting=False, state_age=0., position={"x": .5, "y": .5},
        player_world_position={"x": 0., "y": 0., "z": 0., "instance_id": 2175},
        quest_state_revision=1)
    model = WorldModel()
    model.state, model.session_id = state, state["session_id"]
    planner, goal = Planner(SkillRegistry()), Goal.parse("Questelj", 1.)
    opened = 0
    t = 1.
    for scan in range(3):
        state["quest_state_revision"] = scan + 1          # quest progress resets context
        t += 40.
        state["monotonic_time"] = t
        planner.candidates(goal, model, t)               # new search context
        planner.camera_search_step = 4                   # local sweep exhausted
        t += .5
        state["monotonic_time"] = t
        if not any(p.skill == "OPEN_MAP" for p in planner.candidates(goal, model, t)):
            break
        opened += 1
        state["world_map_open"] = True
        planner.candidates(goal, model, t + 1.)
        assert planner.candidates(goal, model, t + 20.)[0].skill == "CLOSE_MAP"
        state["world_map_open"] = False
        t += 21.
        state["monotonic_time"] = t
        planner.candidates(goal, model, t)               # map closed: scan terminated
    assert opened == 2
    assert planner.map_search_policy.state.empty_scans.get(1409) == 2
