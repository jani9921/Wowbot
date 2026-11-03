from copy import deepcopy
import sqlite3
from types import SimpleNamespace

import pytest

from wowbot.agent.combat_planning import CombatPlanningPolicy
from wowbot.agent.gossip_topics import quest_topic_option
from wowbot.agent.models import Goal, Observation
from wowbot.agent.planner import Planner
from wowbot.agent.quest_dialog_planning import QuestDialogPlanningPolicy
from wowbot.agent.quest_planning import QuestDomain
from wowbot.agent.quest_semantics import npc_name_matches, speak_target_matches
from wowbot.agent.server_npc_planning import ServerNpcInteractionPolicy
from wowbot.agent.skills import SkillRegistry
from wowbot.agent.tdb_knowledge import TDBKnowledgeProvider
from wowbot.agent.world import WorldModel
from wowbot.runtime import SkillStatus
from wowbot.skills.quest_dialog import QuestDialogSkill
from test_m0_combat_loot_skills import active
from test_talk_ride_credits_20261021 import unit


EDRESS = "Creature-0-1463-2444-47-193456-0000616821"
LEFT = "Creature-0-1463-2444-47-191710-0000616823"


def edress():
    value = {"session_id": "two-topic-test", "monotonic_time": 100., "state_age": .1,
        "map_id": 2022, "orientation": 0., "is_in_combat": False,
        "player_world_position": {"x": 0., "y": 0., "z": 383., "instance_id": 2444},
        "target": {"guid": EDRESS, "npc_id": 193456, "name": "Archivist Edress", "attackable": False},
        "packet_entities": {EDRESS: unit(EDRESS, 3., 0., 3)},
        "quest_ui": {"open": True, "npc_guid": EDRESS, "action": "", "gossip_options": [
            {"id": 55564, "name": "What can you tell me about Sabellian?", "available": True,
             "icon": 132053, "flags": 0, "quest_label_prepend": False, "x": .08, "y": .75},
            {"id": 55565, "name": "What can you tell me about Wrathion?", "available": True,
             "icon": 132053, "flags": 0, "quest_label_prepend": False, "x": .08, "y": .74}]},
        "active_quests": [], "reference_knowledge": {"quests": {}}}
    for qid, role, role_entry in ((66780, "Wrathion", 187495), (66779, "Sabellian", 185894)):
        value["active_quests"].append({"quest_id": qid, "is_complete": False, "objectives": [
            {"description": "0/1 Speak with Archivist Edress", "is_complete": False,
             "type": "KILL", "current": 0, "required": 1},
            {"description": "0/1 Another conversation", "is_complete": False, "current": 0, "required": 1}]})
        value["reference_knowledge"]["quests"][str(qid)] = {
            "objectives_text": f"Speak with {role}'s followers.",
            "quest_roles": [{"npc_id": role_entry, "name": role, "role": "QUEST_STARTER"}],
            "objectives": [{"objective_id": qid+100, "description": "Speak with Archivist Edress",
                "credit_action": "TALK", "mechanism": "TALK",
                "credit_name": f"Kill Credit: Talk to {role}'s People 03 [DNT]",
                "talk_creatures": [{"entry": 193456, "name": "Archivist Edress"}]}]}
    return value


def modeled(value):
    world = WorldModel()
    world.ingest(Observation.create(value, 100.))
    world.state.update(value)
    world.quest_model.apply_reference_knowledge(value.get("reference_knowledge") or {})
    return world


def credit(value, quest_id):
    result = deepcopy(value)
    quest = next(q for q in result["active_quests"] if q["quest_id"] == quest_id)
    quest["objectives"][0].update(current=1, is_complete=True)
    return result


def test_two_unmarked_topics_are_selected_one_at_a_time_and_only_own_credit_verifies():
    value = edress()
    first = QuestDialogPlanningPolicy._talk_gossip(value, True)
    assert first.parameters["gossip_option_id"] == 55564 and first.parameters["quest_id"] == 66779
    assert first.parameters["gossip_selection_basis"] == "QUEST_TOPIC_ROLE_MATCH"
    skill = QuestDialogSkill()
    run = active("QUEST_DIALOG", first.parameters, value)
    begun = skill.begin(run, value)
    assert [(c.kind, c.x, c.y) for c in begun.commands] == [("CLICK", .08, .75)]
    assert skill.verify(run, value, 2.).status is SkillStatus.RUNNING
    assert skill.verify(run, credit(value, 66780), 2.5).status is SkillStatus.RUNNING
    first_done = credit(value, 66779)
    assert skill.verify(run, first_done, 3.).status is SkillStatus.SUCCESS
    second = QuestDialogPlanningPolicy._talk_gossip(first_done, True)
    assert second.parameters["gossip_option_id"] == 55565 and second.parameters["quest_id"] == 66780
    run = active("QUEST_DIALOG", second.parameters, first_done)
    assert skill.begin(run, first_done).status is SkillStatus.RUNNING
    assert skill.verify(run, credit(first_done, 66780), 3.).status is SkillStatus.SUCCESS
    assert QuestDialogPlanningPolicy._talk_gossip(credit(first_done, 66780), True) is None


@pytest.mark.parametrize("reverse", [False, True])
def test_topic_selection_uses_actual_row_identity_and_coordinates_in_either_ui_order(reverse):
    value = edress()
    if reverse:
        value["quest_ui"]["gossip_options"].reverse()
    selected = QuestDialogPlanningPolicy._talk_gossip(value, True)
    first = value["quest_ui"]["gossip_options"][0]
    assert selected.parameters["gossip_option_id"] == first["id"]
    assert selected.parameters["y"] == first["y"]


@pytest.mark.parametrize("bad", ["no_topic", "duplicate_topic", "wrong_owner", "stale", "completed", "bad_points", "foreign_quest"])
def test_unmarked_rows_still_require_a_unique_active_topic_and_fresh_owned_ui(bad):
    value = edress()
    if bad == "no_topic":
        for ref in value["reference_knowledge"]["quests"].values(): ref["quest_roles"] = []
    elif bad == "duplicate_topic":
        value["quest_ui"]["gossip_options"][1]["name"] = "What can you tell me about Sabellian?"
    elif bad == "wrong_owner":
        value["quest_ui"]["npc_guid"] = "Creature-0-1463-2444-47-999-0000616821"
    elif bad == "stale":
        value["state_age"] = 2.1
    elif bad == "completed":
        value = credit(credit(value, 66779), 66780)
    elif bad == "foreign_quest":
        for row in value["quest_ui"]["gossip_options"]: row["quest_id"] = 999
    else:
        for row in value["quest_ui"]["gossip_options"]: row["x"] = float("nan")
    assert QuestDialogPlanningPolicy._talk_gossip(value, True) is None


@pytest.mark.parametrize("change", ["service", "cost", "coded", "confirm", "word_fragment"])
def test_topic_fallback_does_not_authorize_services_payment_or_a_similar_word(change):
    value = edress()
    ref = value["reference_knowledge"]["quests"]["66779"]
    options = [deepcopy(value["quest_ui"]["gossip_options"][0])]
    row = options[0]
    if change == "service": row["icon"] = 132060
    elif change == "cost": row["cost"] = 123
    elif change == "coded": row["box_coded"] = True
    elif change == "confirm": row["confirm"] = "Pay now?"
    else: row["name"] = "What can you tell me about Sabellianette?"
    assert quest_topic_option([(66779, ref["objectives"][0])], options,
        value["reference_knowledge"]["quests"], value["target"]) is None


def test_dispatch_rejects_a_changed_topic_row_or_owner_after_planning():
    value = edress()
    selected = QuestDialogPlanningPolicy._talk_gossip(value, True)
    for altered in ("row", "owner"):
        later = deepcopy(value)
        if altered == "row": later["quest_ui"]["gossip_options"][0]["name"] = "Something else"
        else: later["quest_ui"]["npc_guid"] = "Creature-0-1463-2444-47-999-0000616821"
        result = QuestDialogSkill().begin(active("QUEST_DIALOG", selected.parameters, value), later)
        assert result.status is not SkillStatus.RUNNING and not result.commands


def test_shared_planner_prefers_the_unmarked_quest_conversation_to_an_unrelated_offer():
    value = edress()
    value["quest_ui"]["entries"] = [{"kind": "AVAILABLE", "quest_id": 72135,
        "title": "Neltharus: Secrets Within", "acceptable": True, "x": .08, "y": .78}]
    selected = Planner(SkillRegistry()).candidates(Goal.parse("Questelj", 1.), modeled(value), 100.)[0]
    assert selected.skill == "QUEST_DIALOG" and selected.parameters["gossip_option_id"] == 55564


@pytest.mark.parametrize("expected,actual,result", [
    ("Left and Right", "Left", True), ("Left and Right", "Right", True),
    ("Left and Right", "Left Shark", False), ("Left and Right", "Someone Right", False),
    ("Bazentus", "Forgemaster Bazentus", True), ("Bazentus", "Another Bazentus", False),
    ("Captain", "Captain Someone", False), ("Left and Right", "Foreign NPC", False)])
def test_spoken_names_allow_explicit_groups_and_titles_without_loosening_combat_identity(expected, actual, result):
    assert npc_name_matches(expected, actual) is result


def test_coordinated_objective_does_not_override_an_explicit_wrong_entry():
    objective = {"description": "Speak with Left and Right", "type": "TALK_TO",
        "target_entity": {"npc_id": 999}}
    target = {"guid": LEFT, "npc_id": 191710, "name": "Left", "attackable": False}
    assert not speak_target_matches(objective, target)
    objective.pop("target_entity")
    objective["entity_candidates"] = [{"name": "Left"}, {"name": "Right"}]
    assert speak_target_matches(objective, target)


def test_cached_tdb_talk_lookup_finds_short_and_titled_templates():
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.execute("CREATE TABLE creature_template(entry INTEGER, name TEXT)")
    db.executemany("INSERT INTO creature_template VALUES (?,?)", [
        (191710, "Left"), (191711, "Right"), (193464, "Forgemaster Bazentus"),
        (999, "Another Bazentusson"), (998, "Left Shark")])
    calls = []
    def rows(sql, params):
        calls.append((sql, params))
        return [dict(row) for row in db.execute(sql, params)]
    provider = TDBKnowledgeProvider(SimpleNamespace(raw=SimpleNamespace(tables={"creature_template"}, rows=rows)))
    try:
        assert provider.creatures_addressed("left") == [{"entry": 191710, "name": "Left"}]
        assert provider.creatures_addressed("right") == [{"entry": 191711, "name": "Right"}]
        assert provider.creatures_addressed("bazentus") == [{"entry": 193464, "name": "Forgemaster Bazentus"}]
        count = len(calls)
        provider.creatures_addressed("bazentus")
        assert len(calls) == count
    finally:
        db.close()


def left_state(*, opened=True):
    value = edress()
    value["target"] = {"guid": LEFT, "npc_id": 191710, "name": "Left", "attackable": False, "classification": "elite"}
    value["packet_entities"] = {LEFT: unit(LEFT, 3., 0., 1)}
    value["active_quests"] = [{"quest_id": 66780, "is_complete": False, "objectives": [
        {"description": "0/1 Speak with Left and Right", "type": "KILL", "current": 0, "required": 1, "is_complete": False}]}]
    value["reference_knowledge"]["quests"]["66780"]["objectives"] = [{
        "objective_id": 428080, "description": "Speak with Left and Right", "credit_action": "TALK", "mechanism": "TALK",
        "talk_creatures": [{"entry": 191710, "name": "Left"}, {"entry": 191711, "name": "Right"}]}]
    option = {"id": 55355, "name": "What can you tell me about Wrathion?", "icon": 132053,
        "quest_label_prepend": False, "flags": 0, "x": .08, "y": .80, "available": True}
    value["quest_ui"] = {"open": opened, "npc_guid": LEFT, "action": "GOSSIP_OPTION_SELECT" if opened else "",
        "gossip_options": [option] if opened else [], "gossip_option": option if opened else {}}
    return value


def test_friendly_elite_can_have_a_quest_conversation_without_attack_authorization():
    value = left_state()
    selected = Planner(SkillRegistry()).candidates(Goal.parse("Questelj", 1.), modeled(value), 100.)[0]
    assert selected.skill == "QUEST_DIALOG" and selected.parameters["gossip_option_id"] == 55355
    assert selected.parameters["gossip_transition"] == "QUEST_PROGRESS"


@pytest.mark.parametrize("attackable", [False, True, None])
def test_elite_attack_guard_only_blocks_a_potential_combat_target(attackable):
    value = left_state(opened=False)
    value["target"]["attackable"] = attackable
    result = CombatPlanningPolicy(SkillRegistry()).propose(modeled(value), Goal.parse("Questelj", 1.), 100., QuestDomain())
    blocked = any(p.parameters.get("reason") == "unverified_elite_target" for p in result.proposals)
    assert blocked is (attackable is not False)
    assert not any(p.skill in {"COMBAT", "DEFEND"} for p in result.proposals)


def test_current_server_talk_variant_is_approached_without_hover_or_a_hard_target():
    value = left_state(opened=False)
    value["target"] = False
    value["packet_entities"][LEFT]["position"]["x"] = 30.
    selected = ServerNpcInteractionPolicy().propose(value)[0]
    assert selected.skill == "MOVE" and selected.parameters["server_entity_guid"] == LEFT


def test_talk_actor_relation_binds_the_playbook_among_multiple_open_objectives():
    from wowbot.agent.quest_playbooks import context_for

    value = left_state()
    value["active_quests"][0]["objectives"].append({"description": "Speak with Talonstalker Kavia", "is_complete": False})
    value["reference_knowledge"]["quests"]["66780"]["objectives"].append({
        "objective_id": 428079, "description": "Speak with Talonstalker Kavia", "mechanism": "TALK",
        "talk_creatures": [{"entry": 191600, "name": "Talonstalker Kavia"}]})
    chosen = QuestDialogPlanningPolicy._talk_gossip(value, True)
    context = context_for(chosen, value)
    assert context.quest_id == "66780" and context.objective_id == "66780:0"
    assert context.book.mechanism == "TALK"


def test_one_topic_credit_reopens_the_same_npc_for_the_other_without_waiting_45_seconds():
    value = edress()
    value["quest_ui"] = {"open": False}
    value["soft_targets"] = [{"guid": EDRESS, "source_unit": "softinteract"}]
    value["soft_targets_sample_time"] = 100.
    policy = ServerNpcInteractionPolicy()
    assert policy.propose(value)[0].skill == "INTERACT"
    policy.note_dispatched(EDRESS, 100.)
    policy.note_interaction(EDRESS, 100.)
    unchanged = deepcopy(value)
    unchanged.update(monotonic_time=101., soft_targets_sample_time=101.)
    assert policy.propose(unchanged) == []
    changed = credit(unchanged, 66779)
    assert policy.propose(changed) == []  # own quest credit does not erase the short press throttle
    changed.update(monotonic_time=105., soft_targets_sample_time=105.)
    selected = policy.propose(changed)[0]
    assert selected.skill == "INTERACT" and selected.parameters["quest_id"] == "66780"
