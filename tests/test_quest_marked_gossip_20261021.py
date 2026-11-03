"""19:00 live regression: the quest row can be third and share no objective words."""
from copy import deepcopy
from types import SimpleNamespace

import pytest

from wowbot.agent.models import Goal, Observation
from wowbot.agent.packet_entity_facts import kill_objective_entries
from wowbot.agent.planner import Planner
from wowbot.agent.quest_dialog_planning import QuestDialogPlanningPolicy
from wowbot.agent.server_npc_planning import ServerNpcInteractionPolicy, objective_npc_entries
from wowbot.agent.skills import SkillRegistry
from wowbot.agent.tdb_knowledge import TDBKnowledgeProvider
from wowbot.agent.world import WorldModel
from wowbot.runtime import SkillStatus
from wowbot.skills.quest_dialog import QuestDialogSkill
from test_m0_combat_loot_skills import active
from test_talk_ride_credits_20261021 import unit


SELISTRA = "Creature-0-3769-2444-47-193372-00005824C4"
OPTIONS = [
    {"id": 55870, "name": "I'm confused. Are you a dragon or a vulpera?", "available": True, "x": .08, "y": .70},
    {"id": 55871, "name": 'What does a "majordomo" do?', "available": True, "x": .08, "y": .68},
    {"id": 55872, "name": "|cFF0000FF(Quest)|r How can I help defend against the djaradin?", "available": True, "x": .08, "y": .66},
]


def reference(description="Orders received from Majordomo Selistra"):
    def rows(query, params):
        if "WHERE name=?" in query:
            # The live variant is deliberately beyond named_creatures' six-row cap.
            return [{"entry": value, "name": "Majordomo Selistra"} for value in
                    (186767, 186795, 187129, 187267, 187278, 190109, 193372)] if params == ("Majordomo Selistra",) else []
        if "WHERE entry=?" in query:
            return [{"name": "Kill Credit: Orders Received [DNT]"}]
        return []
    catalog = SimpleNamespace(raw=SimpleNamespace(tables={"creature_template"}, rows=rows),
        quest=lambda _: {"quest_id": 69914, "template": {"VerifiedBuild": 69497},
            "objectives_text": "Receive your orders from Majordomo Selistra.",
            "objectives": [{"raw_type": 0, "credit_object_id": 194042,
                "objective_id": 429418, "description": description}]})
    return TDBKnowledgeProvider(catalog).quest(69914)


def state():
    return {"monotonic_time": 100., "state_age": .3, "map_id": 2022,
        "player_world_position": {"x": 0., "y": 0., "z": 91., "instance_id": 2444}, "orientation": 0.,
        "target": False, "packet_entities": {SELISTRA: unit(SELISTRA, 3., 0., 3)},
        "active_quests": [{"quest_id": 69914, "is_complete": False, "objectives": [
            {"description": "0/1 Orders received from Majordomo Selistra", "current": 0,
             "required": 1, "is_complete": False, "type": "KILL"}]}],
        "reference_knowledge": {"quests": {"69914": reference()}},
        "quest_ui": {"open": True, "npc_guid": SELISTRA, "action": "", "quest_id": 0,
                     "gossip_options": deepcopy(OPTIONS)}}


def test_receive_orders_is_a_conversation_with_exact_templates_not_a_proxy_to_attack():
    (objective,) = reference()["objectives"]
    assert objective["credit_action"] == "TALK"
    assert any(row["entry"] == 193372 for row in objective["talk_creatures"])
    assert "193372" in objective_npc_entries(state())
    assert "194042" not in objective_npc_entries(state())
    assert kill_objective_entries(state()) == {}


@pytest.mark.parametrize("position", [0, 1, 2])
def test_the_quest_marked_row_wins_independent_of_its_position(position):
    live = state()
    quest = live["quest_ui"]["gossip_options"].pop()
    live["quest_ui"]["gossip_options"].insert(position, quest)
    proposal = QuestDialogPlanningPolicy._talk_gossip(live, True)
    assert proposal is not None
    assert proposal.parameters["gossip_option_id"] == 55872
    assert proposal.parameters["target_guid"] == SELISTRA
    assert proposal.parameters["gossip_selection_basis"] == "UNIQUE_QUEST_MARKED_OPTION"
    skill = QuestDialogSkill()
    context = active("QUEST_DIALOG", proposal.parameters, live)
    begun = skill.begin(context, live)
    assert begun.status is SkillStatus.RUNNING
    assert [(c.kind, c.x, c.y) for c in begun.commands] == [("CLICK", .08, .66)]
    assert skill.verify(context, live, 2.).status is SkillStatus.RUNNING
    credited = deepcopy(live)
    credited["active_quests"][0]["objectives"][0].update(current=1, is_complete=True)
    assert skill.verify(context, credited, 3.).status is SkillStatus.SUCCESS


@pytest.mark.parametrize("bad", ["two_marked", "unavailable", "bad_point", "wrong_quest_id",
    "other_owner", "unknown_owner", "stale", "completed", "two_related_quests"])
def test_unknown_ambiguous_or_unusable_quest_markers_do_not_fall_back_to_lore(bad):
    live = state()
    option = live["quest_ui"]["gossip_options"][-1]
    if bad == "two_marked":
        live["quest_ui"]["gossip_options"][0]["name"] = "(Quest) A different action."
    elif bad == "unavailable":
        option["available"] = False
    elif bad == "bad_point":
        option["x"] = float("nan")
    elif bad == "wrong_quest_id":
        option["quest_id"] = 999
    elif bad == "other_owner":
        live["quest_ui"]["npc_guid"] = "Creature-0-3769-2444-47-999-00005824C4"
    elif bad == "unknown_owner":
        live["quest_ui"]["npc_guid"] = False
    elif bad == "stale":
        live["state_age"] = 2.1
    elif bad == "completed":
        live["active_quests"][0]["objectives"][0]["is_complete"] = True
    else:
        another = deepcopy(live["active_quests"][0])
        another["quest_id"] = 69915
        live["active_quests"].append(another)
        live["reference_knowledge"]["quests"]["69915"] = deepcopy(reference())
    assert QuestDialogPlanningPolicy._talk_gossip(live, True) is None


def test_explicit_option_quest_id_disambiguates_two_actor_related_active_quests():
    live = state()
    another = deepcopy(live["active_quests"][0])
    another["quest_id"] = 69915
    live["active_quests"].append(another)
    live["reference_knowledge"]["quests"]["69915"] = deepcopy(reference())
    live["quest_ui"]["gossip_options"][-1]["quest_id"] = 69914
    proposal = QuestDialogPlanningPolicy._talk_gossip(live, True)
    assert proposal is not None and proposal.parameters["quest_id"] == 69914


@pytest.mark.parametrize("identifier", [True, 0, -1, 55872.5, float("inf"), "track:55872"])
def test_a_quest_prefix_does_not_authorize_an_invalid_api_option_id(identifier):
    live = state()
    live["quest_ui"]["gossip_options"][-1]["id"] = identifier
    assert QuestDialogPlanningPolicy._talk_gossip(live, True) is None


@pytest.mark.parametrize("prefix", ["(Quest)", " (qUeSt)", "|cffffffff(Quest)|r"])
def test_the_api_prefix_is_case_insensitive_and_independent_of_color(prefix):
    live = state()
    live["quest_ui"]["gossip_options"][-1]["name"] = prefix + " How can I help?"
    proposal = QuestDialogPlanningPolicy._talk_gossip(live, True)
    assert proposal is not None and proposal.parameters["gossip_option_id"] == 55872


def test_the_word_quest_inside_lore_is_not_an_explicit_quest_prefix():
    live = state()
    live["quest_ui"]["gossip_options"][-1]["name"] = "Tell me what (Quest) means."
    assert QuestDialogPlanningPolicy._talk_gossip(live, True) is None


def test_an_npc_quest_marker_alone_cannot_bind_unrelated_objective_or_unknown_template():
    live = state()
    live["reference_knowledge"]["quests"]["69914"] = reference("Supplies gathered from Majordomo Selistra")
    assert QuestDialogPlanningPolicy._talk_gossip(live, True) is None
    ref = reference("Orders received from Someone Unknown")
    assert "credit_action" not in ref["objectives"][0]


def test_orders_npc_stays_server_approachable_without_a_quest_giver_marker():
    live = state()
    live["quest_ui"] = {"open": False}
    live["packet_entities"][SELISTRA]["position"]["x"] = 30.
    (move,) = ServerNpcInteractionPolicy().propose(live)
    assert move.parameters["server_entity_guid"] == SELISTRA
    assert move.parameters["quest_id"] == "69914"


def test_shared_planner_does_not_return_modal_wait_when_the_third_quest_row_is_usable():
    live = state()
    world = WorldModel()
    world.ingest(Observation.create(live, 100.))
    world.state.update(live)
    proposal = Planner(SkillRegistry()).candidates(Goal.parse("Questelj", 1), world, 100.)[0]
    assert proposal.skill == "QUEST_DIALOG" and proposal.parameters["gossip_option_id"] == 55872
