"""Quest short names are hypotheses; live NPC IDs/GUIDs remain authority."""
from types import SimpleNamespace

import pytest

from wowbot.agent.entity_objective_flows import SpeakObjectiveFlow
from wowbot.agent.models import Goal, Observation
from wowbot.agent.planner import Planner, QuestDomain
from wowbot.agent.quest_semantics import talk_to_subject
from wowbot.agent.skills import SkillRegistry
from wowbot.agent.vision_seek import SeekVisualCueController
from wowbot.agent.world import WorldModel


def _objective(name="Meredy", npc_id=None):
    return SimpleNamespace(type="INTERACT_NPC", description=f"0/1 Ask {name} to perform a spell",
                           target_entity={"name": name, "npc_id": npc_id}, raw={},
                           completion_state="IN_PROGRESS", entity_candidates=())


def _npc(name="Meredy Huntswell", **extra):
    return {"guid": "Creature-Meredy", "npc_id": 156943, "name": name,
            "attackable": False, "dead": False, **extra}


@pytest.mark.parametrize("short,full", [("Meredy", "Meredy Huntswell"),
                                      ("Jaina", "Lady Jaina Proudmoore"),
                                      ("Alina", "Apprentice Alina Brightstar")])
def test_ask_clause_and_short_name_match_only_with_friendly_npc_evidence(short, full):
    obj = _objective(short)
    assert talk_to_subject({"description": obj.description}) == short.casefold()
    assert SpeakObjectiveFlow.matches_target(obj, _npc(full))
    seek = SeekVisualCueController()
    seek.intent = {"purpose": "LOCALIZE_SPEAK_NPC", "objective_type": "INTERACT_NPC",
                   "expected_name": short, "objective_description": obj.description}
    assert seek._mouseover_identifies_intent(_npc(full), {})


@pytest.mark.parametrize("short,full", [("Mer", "Meredy Huntswell"),
                                      ("Captain", "Captain Brightstar"),
                                      ("Jaina", "Notjaina Proudmoore"),
                                      ("Meredy Huntswell", "Meredy Othername")])
def test_fragments_titles_and_different_full_names_are_not_identity(short, full):
    assert not SpeakObjectiveFlow.matches_target(_objective(short), _npc(full))


@pytest.mark.parametrize("change", [{"npc_id": 9}, {"guid": "Player-other"},
                                    {"is_player": True}, {"dead": True},
                                    {"is_dead": True}, {"attackable": True}])
def test_wrong_explicit_id_player_dead_and_hostile_never_match(change):
    assert not SpeakObjectiveFlow.matches_target(_objective(npc_id=156943), _npc(**change))


def test_known_ambiguous_short_names_do_not_guess_between_different_npcs():
    obj = _objective()
    obj.entity_candidates = ({"npc_id": 156943, "name": "Meredy Huntswell"},
                             {"npc_id": 9, "name": "Meredy Brightstar"})
    assert not SpeakObjectiveFlow.matches_target(obj, _npc())
    # Multiple phase entries sharing the same full name are not name ambiguity.
    obj.entity_candidates = ({"npc_id": 156943, "name": "Meredy Huntswell"},
                             {"npc_id": 9, "name": "Meredy Huntswell"})
    assert SpeakObjectiveFlow.matches_target(obj, _npc())


def _world(*, dialog=False):
    state = {"session_id": "test", "monotonic_time": 2., "map_id": 1409,
             "target": _npc(), "active_quests": [{"quest_id": 55981, "objectives": [{
                 "type": "KILL", "raw_type": "monster", "description": _objective().description,
                 "current": 0, "required": 1}]}]}
    if dialog:
        option = {"id": 50819, "name": "I'm ready, transform me", "x": .24, "y": .71}
        state["quest_ui"] = {"open": True, "action": "GOSSIP_OPTION_SELECT", "gossip_option": option}
    world = WorldModel()
    world.ingest(Observation.create(state, 2.))
    return world


def test_monster_credit_ask_objective_is_speak_without_an_llm_then_proposes_talk():
    world = _world()
    obj = world.quest_model.ready()[0]
    assert obj.type == "TALK_TO"
    assert obj.target_entity["name"].casefold() == "meredy"
    proposals = Planner(SkillRegistry()).candidates(Goal.parse("Questelj", 2.), world, 2.)
    assert any(p.skill == "TALK" and p.parameters.get("quest_id") == 55981 for p in proposals)
    assert not any(p.skill == "COMBAT" for p in proposals)


def test_short_name_gossip_is_associated_with_only_the_correct_unfinished_quest():
    world = _world(dialog=True)
    dialogs = [p for p in QuestDomain().propose(world, Goal.parse("Questelj", 2.))
               if p.skill == "QUEST_DIALOG"]
    assert len(dialogs) == 1 and dialogs[0].parameters["quest_id"] == 55981
    # A generic conversation option is never enough for another NPC.
    world.state["target"] = _npc("Kee-La", npc_id=10)
    assert not any(p.skill == "QUEST_DIALOG" for p in QuestDomain().propose(world, None))


def test_fresh_hover_short_name_hands_off_the_exact_guid_before_selection():
    world = _world()
    world.state.update(target={}, mouseover=_npc(), cursor_position={"nx": .4, "ny": .6},
                       mouseover_sample_time=2., cursor_sample_time=2.)
    proposals = QuestDomain().propose(world, Goal.parse("Questelj", 2.))
    targets = [p for p in proposals if p.skill == "TARGET"]
    assert targets and targets[0].parameters["guid"] == "Creature-Meredy"
    assert SkillRegistry().available(targets[0], world)


def test_speak_search_exhaustion_cannot_turn_raw_monster_credit_into_kill_area():
    from wowbot.agent.visual_search_planning import VisualSearchPlanningPolicy
    world = _world()
    world.state.update(target={}, player_world_position={"instance_id": 2175, "x": 10., "y": 10.},
                       quest_locations=[{"quest_id": 55981, "world_position": {
                           "instance_id": 2175, "x": 12., "y": 12., "coordinate_space": "WORLD_YARDS"}}])
    assert VisualSearchPlanningPolicy.active_quest_area(world.state) is None


def test_area_search_uses_canonical_semantics_even_when_raw_credit_type_disagrees():
    from wowbot.agent.visual_search_planning import VisualSearchPlanningPolicy
    world = _world()
    world.state.update(target={}, player_world_position={"instance_id": 2175, "x": 10., "y": 10.},
                       quest_locations=[{"quest_id": 55981, "world_position": {
                           "instance_id": 2175, "x": 12., "y": 12., "coordinate_space": "WORLD_YARDS"}}])
    world.state["active_quests"][0]["objectives"][0]["description"] = "A creature credit counter"
    # The canonical model has the resolved TALK_TO; the source payload still says KILL.
    assert VisualSearchPlanningPolicy.active_quest_area(
        world.state, quest_model=world.quest_model) is None


def test_mixed_combat_text_does_not_override_explicit_kill_as_a_conversation():
    from wowbot.agent.quest_model import ObjectiveClassifier
    result = ObjectiveClassifier().classify({
        "type": "KILL", "raw_type": "monster",
        "description": "Talk to Meredy and kill three wolves"})
    assert result.type == "KILL"
