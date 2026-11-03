"""Technical credit -> named actor -> exact owned gossip -> real quest credit."""
from copy import deepcopy
from types import SimpleNamespace

import pytest

from wowbot.agent.packet_entity_facts import kill_objective_entries
from wowbot.agent.quest_dialog_planning import QuestDialogPlanningPolicy
from wowbot.agent.server_npc_planning import ServerNpcInteractionPolicy, objective_npc_entries
from wowbot.agent.tdb_knowledge import TDBKnowledgeProvider
from wowbot.agent.models import Goal, Observation
from wowbot.agent.planner import Planner
from wowbot.agent.skills import SkillRegistry
from wowbot.agent.world import WorldModel
from wowbot.runtime import SkillStatus
from wowbot.skills.quest_dialog import QuestDialogSkill
from test_m0_combat_loot_skills import active
from test_talk_ride_credits_20261021 import SENDRAX, unit


def reference(*, text="Convince Sendrax to fire her emergency signal flare to alert the dragons of your arrival.",
              actor="Sendrax", extra_objective=None):
    def rows(query, params):
        if "WHERE name=?" in query:
            return [{"entry": 193362, "name": actor}] if params == (actor,) else []
        if "WHERE entry=?" in query:
            return [{"name": "Kill Credit: Send Up Flare [DNT]"}]
        return []
    objectives = [{"objective_id": 429414, "raw_type": 0, "credit_object_id": 193989,
                   "description": "Signal flare sent"},
                  {"objective_id": 429415, "raw_type": 0, "credit_object_id": 193990,
                   "description": "Wait for the dragons' arrival"}]
    if extra_objective:
        objectives.append(extra_objective)
    catalog = SimpleNamespace(raw=SimpleNamespace(tables={"creature_template"}, rows=rows),
        quest=lambda _: {"quest_id": 69912, "template": {"VerifiedBuild": 69497},
            "objectives_text": text, "objectives": deepcopy(objectives)})
    return TDBKnowledgeProvider(catalog).quest(69912)


def live(*, dialog=False, selected=False, **changes):
    ref = reference()
    data = {"monotonic_time": 100., "state_age": .2, "orientation": 0., "map_id": 2022,
        "player_world_position": {"x": 0., "y": 0., "z": 91., "instance_id": 2444},
        "active_quests": [{"quest_id": 69912, "is_complete": False, "objectives": [
            {"description": "0/1 Signal flare sent", "current": 0, "required": 1,
             "is_complete": False, "type": "KILL"}]}],
        "reference_knowledge": {"quests": {"69912": ref}},
        "packet_entities": {SENDRAX: unit(SENDRAX, 30., 0., 3)}, "target": {},
        "soft_targets": [], "target_sample_time": 100.}
    if dialog:
        data["quest_ui"] = {"open": True, "action": "", "npc_guid": SENDRAX,
            "gossip_options": [
                {"id": 55637, "available": True, "name": "|cFF0000FF(Quest)|r Send the signal flare to alert the dragons of our arrival.", "x": .08, "y": .64},
                {"id": 55638, "available": True, "name": "Have you not seen a human before?", "x": .08, "y": .62},
                {"id": 64028, "available": True, "name": "So this used to be an Embassy for mortals?", "x": .08, "y": .60}]}
    if selected:
        data["target"] = {"guid": SENDRAX, "name": "Sendrax", "attackable": False}
    return {**data, **changes}


def test_tdb_instruction_links_the_actual_named_actor_not_the_proxy_credit():
    first, wait = reference()["objectives"]
    assert first["credit_action"] == "TALK"
    assert first["talk_creatures"] == [{"entry": 193362, "name": "Sendrax"}]
    assert first["conversation_source"] == "TDB_OBJECTIVES_TEXT"
    assert "credit_action" not in wait
    assert objective_npc_entries(live()) == {"193362": "69912"}
    assert "193989" not in kill_objective_entries(live())


def test_hidden_empty_proxy_credit_does_not_become_a_physical_npc_candidate():
    state = live()
    state["reference_knowledge"]["quests"]["69912"]["objectives"].append({
        "credit_kind": "CREATURE_CREDIT", "credit_object_id": 194018,
        "credit_name": "Kill Credit: Ready for Dragons [DNT]", "description": ""})
    assert objective_npc_entries(state) == {"193362": "69912"}


def test_named_conversation_stays_proposed_after_the_quest_marker_clears():
    state = live()
    state["packet_entities"][SENDRAX]["quest_giver"] = {"quest_available": False, "reward_ready": False}
    (move,) = ServerNpcInteractionPolicy().propose(state)
    assert move.parameters["server_entity_guid"] == SENDRAX and move.parameters["quest_id"] == "69912"
    assert move.parameters["face_on_arrival"] is True
    state["active_quests"][0]["objectives"][0]["is_complete"] = True
    state["active_quests"][0]["objectives"].append({"description": "Wait for the dragons' arrival", "is_complete": False})
    assert ServerNpcInteractionPolicy().propose(state) == []


@pytest.mark.parametrize("text", ["Convince Unknown Person to fire the signal flare.",
    "Find Sendrax after the signal flare has been sent.",
    "Convince Sendrax to collect apples."])
def test_unresolved_or_unrelated_instruction_does_not_manufacture_talk_identity(text):
    assert "credit_action" not in reference(text=text)["objectives"][0]


def test_equal_objective_matches_are_ambiguous_not_silently_first():
    ref = reference(extra_objective={"objective_id": 2, "raw_type": 0,
        "credit_object_id": 3, "description": "Signal flare launched"})
    assert all(row.get("credit_action") != "TALK" for row in ref["objectives"])


@pytest.mark.parametrize("selected", [False, True])
def test_exact_owned_dialog_can_select_grounded_option_without_hard_target(selected):
    state = live(dialog=True, selected=selected)
    row = QuestDialogPlanningPolicy._talk_gossip(state, True)
    assert row is not None and row.parameters["gossip_option_id"] == 55637
    assert row.parameters["target_guid"] == SENDRAX
    skill = QuestDialogSkill()
    context = active("QUEST_DIALOG", row.parameters, state)
    result = skill.begin(context, state)
    assert result.status is SkillStatus.RUNNING
    assert [(c.kind, c.x, c.y) for c in result.commands] == [("CLICK", .08, .64)]
    pending = skill.verify(context, state, 2.)
    assert pending.status is SkillStatus.RUNNING and not pending.commands
    credited = deepcopy(state)
    credited["active_quests"][0]["objectives"][0].update(current=1, is_complete=True)
    done = skill.verify(context, credited, 3.)
    assert done.status is SkillStatus.SUCCESS and not done.commands


@pytest.mark.parametrize("bad", ["other_owner", "missing_identity", "stale", "removed"])
def test_wrong_unknown_stale_or_removed_dialog_actor_never_authorizes_option(bad):
    state = live(dialog=True)
    if bad == "other_owner":
        state["quest_ui"]["npc_guid"] = "Creature-0-3769-2444-47-999-00005824C1"
    elif bad == "missing_identity":
        state["quest_ui"]["npc_guid"] = False
    elif bad == "stale":
        state["state_age"] = 2.1
    else:
        state["packet_entities"][SENDRAX]["removed"] = True
    assert QuestDialogPlanningPolicy._talk_gossip(state, True) is None


def test_equal_scoring_gossip_rows_are_not_arbitrarily_selected():
    state = live(dialog=True)
    state["quest_ui"]["gossip_options"].append({"id": 77, "available": True,
        "name": "(Quest) Send the signal flare now.", "x": .08, "y": .58})
    assert QuestDialogPlanningPolicy._talk_gossip(state, True) is None


def test_a_lore_row_with_the_same_words_cannot_outrank_the_unique_quest_marker():
    state = live(dialog=True)
    state["quest_ui"]["gossip_options"].insert(0, {"id": 77, "available": True,
        "name": "Send the signal flare now.", "x": .08, "y": .58})
    proposal = QuestDialogPlanningPolicy._talk_gossip(state, True)
    assert proposal.parameters["gossip_option_id"] == 55637
    assert proposal.parameters["gossip_selection_basis"] == "UNIQUE_QUEST_MARKED_OPTION"


def test_unmarked_equal_scoring_rows_still_require_disambiguation():
    state = live(dialog=True)
    state["quest_ui"]["gossip_options"][0]["name"] = "Send the signal flare now."
    state["quest_ui"]["gossip_options"].append({"id": 77, "available": True,
        "name": "Send the signal flare please.", "x": .08, "y": .58})
    assert QuestDialogPlanningPolicy._talk_gossip(state, True) is None


def test_ui_owner_swap_after_planning_sends_no_click():
    state = live(dialog=True)
    row = QuestDialogPlanningPolicy._talk_gossip(state, True)
    assert row is not None
    state["quest_ui"]["npc_guid"] = "Creature-0-3769-2444-47-999-00005824C1"
    started = QuestDialogSkill().begin(active("QUEST_DIALOG", row.parameters, state), state)
    assert started.status in {SkillStatus.FAILURE, SkillStatus.BLOCKED} and not started.commands


@pytest.mark.parametrize("clock", [None, float("nan"), float("inf")])
def test_live_dialog_without_a_valid_clock_does_not_authorize_a_row(clock):
    state = live(dialog=True, monotonic_time=clock, transport_kind="PIXEL_STRIP")
    assert QuestDialogPlanningPolicy._talk_gossip(state, True) is None


def test_conflicting_selected_numeric_identity_blocks_a_previously_planned_click():
    state = live(dialog=True, selected=True)
    row = QuestDialogPlanningPolicy._talk_gossip(state, True)
    assert row is not None
    state["target"]["npc_id"] = 999
    result = QuestDialogSkill().begin(active("QUEST_DIALOG", row.parameters, state), state)
    assert result.status is SkillStatus.FAILURE and not result.commands


def test_shared_planner_admits_the_grounded_gossip_instead_of_modal_wait():
    state = live(dialog=True)
    world = WorldModel()
    world.ingest(Observation.create(state, 100.))
    # The saved canonical snapshot's reference/packet fields have already
    # passed their own source boundary; the test does not create a sensor.
    world.state.update(state)
    planner = Planner(SkillRegistry())
    rows = planner.candidates(Goal.parse("Questelj", 1), world, 100.)
    assert rows[0].skill == "QUEST_DIALOG"
    assert rows[0].parameters["gossip_option_id"] == 55637
    assert rows[0].parameters["target_guid"] == SENDRAX
