"""quest_creature_memory (user 2026-10-05): what the agent saw about each
quest's creatures -- givers, enders, objective creatures, the vehicle, their
looks, and how every objective counter rose -- kept per profile and used to
pick the right unit with fewer hovers."""
from types import SimpleNamespace

from wowbot.agent.models import Goal, Observation
from wowbot.agent.quest_creature_memory import (QuestCreatureMemory, npc_id_from_guid,
                                                remembered_creature)
from wowbot.agent.quest_turn_in import turn_in_from_text
from wowbot.agent.target_planning import TargetPlanningPolicy
from wowbot.agent.visual_inspection_planning import VisualInspectionPolicy
from wowbot.agent.world import WorldModel

HENRY = "Creature-0-3113-2175-63341-156799-0000C115E3"
COLE = "Creature-0-3113-2175-63341-156801-0000C115E3"
RICHTER = "Creature-0-3113-2175-63341-156800-0000C115E3"
GARRICK = "Creature-0-3113-2175-63341-245394-00004115E3"


def _pin(quest_id, x, y):
    return {"quest_id": quest_id, "is_campaign": True, "x": .5, "y": .5, "source": "QUESTLINE_API",
            "world_position": {"x": x, "y": y, "instance_id": 2175, "coordinate_space": "WORLD_YARDS"}}


def _frame(t, **values):
    frame = {"session_id": "s:1", "timestamp": t, "frame_id": f"f{t}", "monotonic_time": t,
             "map_id": 1409, "player_present": True, "active_quests": [],
             "player_world_position": {"x": 260., "y": -2332., "instance_id": 2175,
                                       "coordinate_space": "WORLD_YARDS"}}
    frame.update(values)
    return frame


def _world(memory, *frames):
    world = WorldModel()
    world.__dict__["quest_creature_memory"] = memory
    for frame in frames:
        world.ingest(Observation.create(frame, frame["monotonic_time"]))
    return world


def test_rows_are_kept_once_and_survive_a_restart(tmp_path):
    path = tmp_path / "quest_creature_memory.sqlite3"
    memory = QuestCreatureMemory(path)
    assert memory.record_role(55196, "GIVER", name="Henry Garrick", npc_id=156799,
                              position={"x": 267., "y": -2339., "instance_id": 2175})
    assert not memory.record_role(55196, "GIVER", name="Henry Garrick", npc_id=156799,
                                  position={"x": 268., "y": -2339., "instance_id": 2175})
    for _ in range(3):
        memory.record_progress(55879, 0, description="0/8 Monstrous Cadaver trampled",
                               skill="VEHICLE_ABILITY", spell_id=301234, in_vehicle=True,
                               target_name="Monstrous Cadaver", position={"x": 10., "y": 0.})
    memory.record_progress(55879, 0, description="", skill="VEHICLE_ABILITY", spell_id=301234,
                           in_vehicle=True, target_name="Monstrous Cadaver",
                           position={"x": 30., "y": 0.}, steps=1)
    memory.save_ability_effects({"301234": {"mode": "FORWARD_DASH", "hit": True, "samples": 3}},
                                {"301234": "Trample"})
    memory.close()
    again = QuestCreatureMemory(path)
    giver = again.roles(55196)["GIVER"][0]
    assert (giver["name"], giver["npc_id"], giver["x"]) == ("Henry Garrick", 156799, 267.)
    row = again.progress(55879)[0]
    assert (row["count"], row["in_vehicle"], row["spell_id"], row["x"], row["radius"]) == (
        4, 1, 301234, 15., 20.)
    assert again.ability_effects()["301234"]["mode"] == "FORWARD_DASH"
    assert again.save_ability_effects({"301234": {"mode": "FORWARD_DASH", "hit": True, "samples": 3}}) == 0
    again.close()


def test_npc_id_comes_from_the_creature_guid():
    assert npc_id_from_guid(HENRY) == 156799
    assert npc_id_from_guid("Player-1402-0B553B1F") is None
    assert npc_id_from_guid("ClientActor-3-3-1084") is None


def test_looks_keep_four_samples_per_creature():
    memory = QuestCreatureMemory()
    vectors = [[1., 0., 0.], [0., 1., 0.], [0., 0., 1.], [.6, .8, 0.], [0., .6, .8]]
    for at, vector in enumerate(vectors):
        assert memory.record_look(156799, vector, name="Henry Garrick", map_id=1409, at=at*100.)
    assert len(memory.looks(1409)[156799]) == 4
    assert not memory.record_look(156799, [1., 0., 0.], map_id=1409, at=410.)   # refreshed < 60 s ago


def test_dialog_giver_is_remembered_at_its_pin_and_ender_names_the_turn_in():
    memory = QuestCreatureMemory()
    _world(memory,
           _frame(1., map_pois={"available_quests": [_pin(55196, 267., -2339.)]}),
           _frame(2., quest_text={"quest_id": 55196, "giver_name": "Henry Garrick", "giver_guid": HENRY}),
           _frame(3., quest_text={"quest_id": 55194, "ender_name": "Captain Garrick", "ender_guid": GARRICK}))
    giver = memory.roles(55196)["GIVER"][0]
    assert (giver["npc_id"], giver["x"], giver["y"]) == (156799, 267., -2339.)
    # Next session: the finished quest's ender is known before any text or LLM.
    done = {"quest_id": 55194, "is_complete": True, "title": "Stocking Up on Supplies", "objectives": []}
    world = _world(memory, _frame(10., session_id="s:2", active_quests=[done]))
    assert world.state["quest_turn_in_names"]["55194"]["name"] == "Captain Garrick"
    assert world.state["quest_turn_in_names"]["55194"]["source"] == "QUEST_CREATURE_MEMORY"


def test_objective_progress_records_what_was_done_on_what_and_where():
    """User: 'megölt 8/8 ilyet ... felszállt a disznóra, chargeolt a zombira'."""
    memory = QuestCreatureMemory()
    quest = {"quest_id": 55879, "title": "Ride of the Scientifically Enhanced Boar", "objectives": [
        {"description": "0/8 Monstrous Cadaver trampled", "current": 0, "required": 8}]}
    boar = {"guid": "Vehicle-0-3113-2175-63341-156595-0000C115E3", "name": "Giant Boar", "npc_id": 156595}
    cadaver = {"guid": "ClientActor-3-3-1084", "name": "Monstrous Cadaver"}
    progressed = {**quest, "objectives": [{**quest["objectives"][0], "description": "2/8 Monstrous Cadaver trampled",
                                           "current": 2}]}
    world = _world(memory, _frame(1., active_quests=[quest], in_vehicle=False, target=boar),
                   _frame(2., active_quests=[quest], in_vehicle=True, target=boar))
    world.runtime_context = {"last_result": {"skill": "VEHICLE_ABILITY", "last_binding": "ACTIONBUTTON1"}}
    world.ingest(Observation.create(_frame(3., active_quests=[progressed], in_vehicle=True, target=None,
                                           mouseover=cadaver, combat_last_spell_id=301234,
                                           combat_last_cast_at=2.5), 3.))
    row = memory.progress(55879)[0]
    assert (row["count"], row["skill"], row["spell_id"], row["in_vehicle"], row["target_name"]) == (
        2, "VEHICLE_ABILITY", 301234, 1, "Monstrous Cadaver")
    assert (row["x"], row["y"]) == (260., -2332.)
    roles = memory.roles(55879)
    assert roles["OBJECTIVE"][0]["name"] == "Monstrous Cadaver"
    assert roles["VEHICLE"][0]["npc_id"] == 156595


def test_remembered_pin_giver_is_selected_without_a_detected_quest_symbol():
    """Live 2026-10-05 05:40: Henry Garrick was hovered at his pin, but his
    campaign "!" was not detected and a faint symbol elsewhere vetoed the
    "no symbol visible" rule; he was never selected."""
    memory = QuestCreatureMemory()
    memory.record_role(55196, "GIVER", name="Henry Garrick", npc_id=156799, source="QUEST_DETAIL_DIALOG")
    faint = {"source": "WORLD3D", "track_id": "WORLD3D:263", "kind": "unknown_symbol_candidate",
             "detector_kind": "unknown_symbol_candidate", "candidate_labels": ["learned_symbol_like"],
             "x": .2, "y": .7, "confidence": .03,
             "bbox": {"left": 360, "top": 200, "right": 380, "bottom": 220, "coordinate_space": "CLIENT_PIXELS"}}
    henry = {"guid": HENRY, "name": "Henry Garrick", "npc_id": 156799, "unit_type": "NPC", "is_attackable": False}
    world = _world(memory, _frame(1., map_pois={"available_quests": [_pin(55196, 267., -2339.)]},
                                  mouseover=henry, cursor_position={"nx": .5, "ny": .6},
                                  visual_candidates=[faint]))
    assert world.state["quest_creatures"]["pin_givers_known"] is True
    proposals = TargetPlanningPolicy().propose(
        world, Goal.parse("Questelj", 1.), target={}, cursor_matches_mouseover=True,
        state_time=1., mouse_time=1.)
    assert [p.parameters["guid"] for p in proposals if p.skill == "TARGET"] == [HENRY]
    # Without the memory the same frame selects nobody (the former behaviour).
    blank = _world(QuestCreatureMemory(), _frame(1., map_pois={"available_quests": [_pin(55196, 267., -2339.)]},
                                                 mouseover=henry, cursor_position={"nx": .5, "ny": .6},
                                                 visual_candidates=[faint]))
    assert not [p for p in TargetPlanningPolicy().propose(
        blank, Goal.parse("Questelj", 1.), target={}, cursor_matches_mouseover=True,
        state_time=1., mouse_time=1.) if p.skill == "TARGET"]


def test_known_pin_givers_spare_hovering_the_other_npcs_again():
    """User: 'ne legyen felesleges sok inspect'."""
    policy = VisualInspectionPolicy()
    creatures = {"pin_givers_known": True, "wanted": [],
                 "pin_givers": [{"role": "GIVER", "npc_id": 156801, "name": "Private Cole", "quest_id": 58914}]}

    def world(**extra):
        return SimpleNamespace(state={"player_world_position": {"x": 0., "y": 0.}, "orientation": 0.,
                                      "mouseover": {}, "target": {}, "active_quests": [],
                                      "quest_creatures": creatures, **extra},
                               runtime_context={"last_result": {}},
                               quest_model=SimpleNamespace(ready=lambda: []))

    for key, track, x, guid, name in (("k1", "WORLD3D:2", .6, RICHTER, "Quartermaster Richter"),
                                      ("k2", "WORLD3D:1", .4, COLE, "Private Cole")):
        policy.__dict__.setdefault("_inspect_points", {})[key] = {
            "x": x, "y": .5, "view": (0., 0., 0.), "track_id": track}
        done = SimpleNamespace(state={**world().state, "mouseover": {"guid": guid, "name": name}},
                               runtime_context={"last_result": {"skill": "INSPECT", "action_id": key, "key": key,
                                                                "reason": "expected_observation_verified"}},
                               quest_model=SimpleNamespace(ready=lambda: []))
        policy._note_inspect_outcome(done, 10.)
    assert policy._known_unneeded(world(), .6, .5, "WORLD3D:2")         # Richter: not a giver here
    assert not policy._known_unneeded(world(), .4, .5, "WORLD3D:1")      # Cole: the remembered giver
    unknown = {**creatures, "pin_givers_known": False}
    assert not policy._known_unneeded(world(quest_creatures=unknown), .6, .5, "WORLD3D:2")


def test_wanted_creature_look_is_probed_first():
    memory = QuestCreatureMemory()
    memory.record_role(55196, "GIVER", name="Henry Garrick", npc_id=156799)
    memory.record_look(156799, [1., 0., 0.], name="Henry Garrick", map_id=1409, at=0.)
    memory.record_look(156800, [0., 1., 0.], name="Quartermaster Richter", map_id=1409, at=0.)

    def box(track, embedding):
        return {"source": "WORLD3D", "track_id": track, "kind": "unknown_subject_candidate",
                "detector_kind": "unknown_subject_candidate", "x": .5, "y": .5,
                "visual_signature": {"embedding": embedding}}
    world = _world(memory, _frame(1., map_pois={"available_quests": [_pin(55196, 267., -2339.)]},
                                  visual_candidates=[box("WORLD3D:a", [.99, .1, 0.]), box("WORLD3D:b", [.1, .99, 0.])]))
    lifts = {item["track_id"]: item["appearance"]["creature_memory_lift"]
             for item in world.state["visual_candidates"]}
    assert lifts["WORLD3D:a"] > 0 > lifts["WORLD3D:b"]


def test_remembered_ender_is_a_relevant_friendly_unit():
    from wowbot.agent.quest_giver_evidence import friendly_npc_relevant
    state = {"active_quests": [{"quest_id": 55194, "is_complete": True}],
             "quest_creatures": {"wanted": [{"role": "ENDER", "npc_id": 245394, "name": "Captain Garrick",
                                             "quest_id": 55194}]}}
    assert friendly_npc_relevant(state, GARRICK, {"COLLECT"}, unit_name="Captain Garrick")
    assert remembered_creature(state, GARRICK, roles=("ENDER",))["quest_id"] == 55194
    assert not friendly_npc_relevant(state, RICHTER, {"COLLECT"}, unit_name="Quartermaster Richter")


def test_quest_log_completion_line_names_the_turn_in_npc():
    quest = {"quest_id": 55194, "is_complete": True,
             "completion_log_text": "Return to Captain Garrick at the Alliance camp."}
    found = turn_in_from_text(quest, {})
    assert (found["name"], found["source"]) == ("Captain Garrick", "QUEST_TEXT_PATTERN:QUEST_LOG_COMPLETION_TEXT")
