"""DB2 + TDB directed self-item handoff, with no quest-specific identifiers."""
from copy import deepcopy
import importlib.util
import json
import math
from pathlib import Path
import sqlite3
from types import SimpleNamespace

import pytest

from wowbot.agent.directed_item_facts import PURPOSE, aim_state, ready_for_use, credit_window
from wowbot.agent.directed_item_planning import DirectedItemPolicy
from wowbot.agent.models import Attempt, Command, Goal, Observation, Prediction, Proposal
from wowbot.agent.quest_item_knowledge import annotate_items
from wowbot.agent.quest_planning import QuestDomain
from wowbot.agent.quest_tool_resolver import QuestToolResolver
from wowbot.agent.skills import SkillRegistry
from wowbot.agent.world import WorldModel
from wowbot.quests.client_supplement import ClientSupplement
from wowbot.quests.item_spell_hits import spell_hit_credits
from wowbot.runtime import ActiveSkillRuntime, Intent, SkillStatus, FailureReason
from wowbot.runtime.skill_identity import check_command_identity
from wowbot.skills.quest_item import UseItemSkill

spec = importlib.util.spec_from_file_location("directed_supplement_builder",
    Path(__file__).parents[1] / "tools/build_client_supplement.py")
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)

NOW, Q, ITEM, ROOT, HIT, CREDIT, ENTRY = 10., 71, 441, 701, 702, 903, 904
GUID = "Creature-0-1-0-1-904-0000000001"
GUID2 = "Creature-0-1-0-1-904-0000000002"


class Provider:
    def __init__(self, db):
        self.db = db
        self.catalog = SimpleNamespace(raw=self)
        self.tables = {"conditions", "smart_scripts"}

    def rows(self, sql, params=()):
        return [dict(row) for row in self.db.execute(sql, params)]


@pytest.fixture
def provider():
    with sqlite3.connect(":memory:") as db:
        db.row_factory = sqlite3.Row
        db.executescript("""
            CREATE TABLE smart_scripts(entryorguid INTEGER, source_type INTEGER, id INTEGER,
                link INTEGER, event_type INTEGER, event_phase_mask INTEGER, event_chance INTEGER,
                event_param1 INTEGER, action_type INTEGER, action_param1 INTEGER, target_type INTEGER);
            CREATE TABLE conditions(SourceTypeOrReferenceId INTEGER, SourceGroup INTEGER,
                SourceEntry INTEGER, SourceId INTEGER, ElseGroup INTEGER,
                ConditionTypeOrReference INTEGER, ConditionTarget INTEGER,
                ConditionValue1 INTEGER, ConditionValue2 INTEGER, ConditionValue3 INTEGER,
                ConditionStringValue1 TEXT, NegativeCondition INTEGER, ScriptName TEXT);
        """)
        db.execute("INSERT INTO smart_scripts VALUES (?,0,2,3,8,1,100,?,33,?,7)", (ENTRY, HIT, CREDIT))
        db.execute("INSERT INTO conditions VALUES (13,1,?,0,0,31,0,3,?,0,'',0,'')", (HIT, ENTRY))
        yield Provider(db)


@pytest.fixture
def supplement(tmp_path):
    path = tmp_path / "directed.sqlite3"
    with sqlite3.connect(path) as db:
        db.executescript(builder.SCHEMA)
        db.execute("PRAGMA user_version=1")
        db.execute("INSERT INTO items VALUES (?,'Mist emitter','',0)", (ITEM,))
        db.execute("INSERT INTO item_effects VALUES (1,?,0,0,0,8000,-1,0,0,0)", (ROOT,))
        db.execute("INSERT INTO item_effect_links VALUES (1,?,1)", (ITEM,))
        db.execute("INSERT INTO spell_effects VALUES (10,?,0,6,23,?,0,0,1,0)", (ROOT, HIT))
        db.execute("INSERT INTO spell_effects VALUES (11,?,0,3,0,0,0,0,60,0)", (HIT,))
        db.execute("INSERT INTO spell_targets VALUES (20,?,0,0,0)", (HIT,))
        db.execute("INSERT INTO spell_misc VALUES (30,?,0,0)", (ROOT,))
        for table, key, value in [
            ("SpellEffect", 11, {"EffectIndex": 0, "EffectRadiusIndex": [18, 0]}),
            ("SpellRadius", 18, {"Radius": 15., "RadiusPerLevel": 0., "RadiusMax": 15.}),
            ("SpellTargetRestrictions", 20, {"ConeDegrees": 60.}),
            ("SpellMisc", 30, {"DurationIndex": 28}),
            ("SpellDuration", 28, {"Duration": 5000}),
        ]:
            db.execute("INSERT INTO db2_rows VALUES (?,?,?)", (table, key, json.dumps(value)))
    return ClientSupplement(path)


def payload(supplement, provider):
    ref = {"quest_id": Q, "items": {"start_item_id": ITEM}, "objectives": [{
        "objective_id": 1001, "order": 0, "raw_type": 0, "credit_kind": "CREATURE_CREDIT",
        "credit_object_id": CREDIT, "credit_name": "Trigger credit", "description": "Targets sprayed",
        "amount": 3, "named_creatures": []}]}
    annotate_items(ref, supplement, spell_hits=lambda spell: spell_hit_credits(provider, spell))
    return {"session_id": "directed:test", "timestamp": NOW, "monotonic_time": NOW,
        "player_present": True, "health": 100, "max_health": 100,
        "map_id": 425, "orientation": 0., "movement": {"moving": False, "speed": 0},
        "player_world_position": {"x": 0., "y": 0., "z": 70., "z_known": True,
            "z_observed": True, "instance_id": 0, "sample_time": NOW, "coordinate_space": "WORLD_YARDS"},
        "target": None, "actionbar": [], "bags_open": True,
        "inventory": {"items": [{"item_id": ITEM, "bag": 0, "slot": 4, "is_locked": False,
            "x": .8, "y": .2, "coordinate_space": "CLIENT_BOTTOM_LEFT"}]},
        "quest_item_target": {"guid": None, "sample_time": NOW, "items": [{
            "quest_id": Q, "item_id": ITEM, "is_usable": True,
            "cooldown_remaining": 0., "in_range": None}]},
        "active_quests": [{"quest_id": Q, "is_complete": False, "special_item": {"item_id": ITEM},
            "objectives": [{"objective_id": f"{Q}:0", "type": "KILL", "description": "Targets sprayed",
                "current": 0, "required": 3, "is_complete": False}]}],
        "reference_knowledge": {"quests": {str(Q): ref}},
        "packet_entities": {GUID: {"guid": GUID, "kind": "CREATURE", "entry_id": ENTRY,
            "map_id": 0, "unit": {"health": 1, "unit_flags": 33555200},
            "position": {"x": 8., "y": 0., "z": 70., "age": 0., "source": "PACKET_CREATE_MOVEMENT"}}},
    }


def modeled(value):
    world = WorldModel()
    world.ingest(Observation.create(value, NOW))
    world.quest_model.apply_reference_knowledge(value["reference_knowledge"])
    return world


def planned(value, domain=None):
    domain = domain or QuestDomain()
    world = modeled(value)
    results = []
    domain._propose_objectives(world, world.state, NOW, world.quest_model.records,
                               str(Q), f"{Q}:0", False, results)
    return results


def runtime(value, proposal, deadline=NOW+8):
    attempt = Attempt("directed", proposal, deepcopy(value), "obs", NOW, deadline, (),
        Prediction("p", "directed", "credit", NOW, deadline, "obs"))
    return ActiveSkillRuntime().start(intent=Intent("USE_ON_TARGET", proposal.parameters,
        objective_ref=f"{Q}:0"), attempt=attempt, now=NOW, before_snapshot=deepcopy(value))


def use_profile(value):
    return value["reference_knowledge"]["quests"][str(Q)]["items"]["use_profiles"][str(ITEM)]["uses"][0]


def test_db2_emitter_and_tdb_spellhit_form_a_conditional_link(supplement, provider):
    value = payload(supplement, provider)
    use = use_profile(value)
    assert use["delivery"] == {"mode": "FORWARD_CONE", "status": "RESOLVED", "spell_id": HIT,
        "effect_id": 11, "effect_index": 0, "spell_chain": [ROOT, HIT], "radius": 15.,
        "cone_degrees": 60., "duration_ms": 5000}
    link, = use["credit_links"]
    assert (link["subject_entry"], link["id"], link["hit_spell_id"]) == (ENTRY, CREDIT, HIT)
    assert link["conditional"] and link["script"]["event_phase_mask"] == 1
    assert modeled(value).quest_model.records[Q].objectives[0].type == "USE_ITEM_ON_TARGET"
    assert value["active_quests"][0]["objectives"][0]["current"] == 0


@pytest.mark.parametrize("mutation", ["radius", "duration", "mixed_child", "nonperiodic", "effect_index"])
def test_unknown_or_different_geometry_cannot_activate(supplement, provider, mutation):
    with sqlite3.connect(supplement.path) as db:
        if mutation in {"radius", "duration"}:
            db.execute("DELETE FROM db2_rows WHERE table_name=?",
                       ("SpellRadius" if mutation == "radius" else "SpellDuration",))
        elif mutation == "mixed_child":
            db.execute("INSERT INTO spell_effects VALUES (12,?,0,3,0,0,0,0,6,0)", (HIT,))
        elif mutation == "nonperiodic":
            db.execute("UPDATE spell_effects SET aura=0 WHERE spell_id=?", (ROOT,))
        else:
            db.execute("UPDATE db2_rows SET record_json=? WHERE table_name='SpellEffect'",
                       (json.dumps({"EffectIndex": None, "EffectRadiusIndex": [18, 0]}),))
    value = payload(supplement, provider)
    assert use_profile(value)["delivery"]["status"] != "RESOLVED"
    assert [p.skill for p in planned(value)] == ["WAIT"]


@pytest.mark.parametrize("change", ["negative", "extra_condition", "smart_condition", "wrong_entry", "wrong_target", "missing_table", "value3"])
def test_unsupported_or_ambiguous_tdb_evidence_provides_no_link(provider, change):
    if change == "negative":
        provider.db.execute("UPDATE conditions SET NegativeCondition=1")
    elif change == "extra_condition":
        provider.db.execute("INSERT INTO conditions SELECT * FROM conditions")
    elif change == "smart_condition":
        provider.db.execute("INSERT INTO conditions VALUES (22,3,?,0,0,1,0,0,0,0,'',0,'')", (ENTRY,))
    elif change == "wrong_entry":
        provider.db.execute("UPDATE conditions SET ConditionValue2=999")
    elif change == "wrong_target":
        provider.db.execute("UPDATE smart_scripts SET target_type=1")
    elif change == "missing_table":
        provider.tables.remove("conditions")
    else:
        provider.db.execute("UPDATE conditions SET ConditionValue3=1")
    assert spell_hit_credits(provider, HIT) == []


def test_common_move_faces_server_subject_then_bag_use_without_tab_or_f7(supplement, provider):
    value = payload(supplement, provider)
    value["packet_entities"][GUID]["position"]["x"] = 30.
    move, = planned(value)
    assert move.skill == "MOVE" and move.parameters["server_entity_guid"] == GUID
    assert move.parameters["face_on_arrival"] and move.parameters["require_navmesh"]
    value["packet_entities"][GUID]["position"]["x"] = 8.
    value["orientation"] = math.pi
    assert planned(value)[0].skill == "MOVE"
    value["orientation"] = 0.
    value["bags_open"] = False
    assert planned(value)[0].skill == "OPEN_BAGS"
    value["bags_open"] = True
    proposal, = planned(value)
    assert proposal.skill == "USE_ON_TARGET" and proposal.parameters["target_required"] is False
    assert "guid" not in proposal.parameters
    assert SkillRegistry().available(proposal, modeled(value))
    result = UseItemSkill().begin(runtime(value, proposal), value)
    assert result.status is SkillStatus.RUNNING
    assert result.commands == (Command("CLICK", x=.8, y=.2, button="RIGHT"),)


@pytest.mark.parametrize("change", ["pose_stale", "item_stale", "cooldown", "unusable", "unknown", "other_floor",
    "wrong_guid", "removed", "dead", "instance", "moving", "combat", "mount", "cast", "bags", "slot", "button",
    "quest_complete", "objective_complete", "credit_mismatch", "effect_mask"])
def test_begin_and_final_boundary_recheck_current_pose_context_and_button(supplement, provider, change):
    value = payload(supplement, provider)
    proposal, = planned(value)
    bad = deepcopy(value)
    unit = bad["packet_entities"][GUID]
    row = bad["quest_item_target"]["items"][0]
    if change == "pose_stale": bad["player_world_position"]["sample_time"] = 0.
    elif change == "item_stale": bad["quest_item_target"]["sample_time"] = 0.
    elif change == "cooldown": row["cooldown_remaining"] = 3.
    elif change == "unusable": row["is_usable"] = False
    elif change == "unknown": row["cooldown_remaining"] = None
    elif change == "other_floor": unit["position"]["z"] += 10
    elif change == "wrong_guid": unit["guid"] = GUID2
    elif change == "removed": unit["removed"] = True
    elif change == "dead": unit["unit"]["health"] = 0
    elif change == "instance": unit["map_id"] = 1
    elif change == "moving": bad["movement"]["moving"] = True
    elif change == "combat": bad["is_in_combat"] = True
    elif change == "mount": bad["is_mounted"] = True
    elif change == "cast": bad["is_casting"] = True
    elif change == "bags": bad["bags_open"] = False
    elif change == "slot": bad["inventory"]["items"][0]["slot"] = 5
    elif change == "button": bad["inventory"]["items"][0]["x"] = .7
    elif change == "quest_complete": bad["active_quests"][0]["is_complete"] = True
    elif change == "objective_complete": bad["active_quests"][0]["objectives"][0]["current"] = 3
    elif change == "credit_mismatch": use_profile(bad)["credit_links"][0]["id"] = 999
    else: use_profile(bad)["credit_links"][0]["target_conditions"][0]["SourceGroup"] = 2
    result = UseItemSkill().begin(runtime(value, proposal), bad)
    assert not result.commands and result.status in {SkillStatus.BLOCKED, SkillStatus.FAILURE}
    assert not check_command_identity("USE_ON_TARGET", proposal.parameters, {}, bad,
        (Command("CLICK", x=.8, y=.2, button="RIGHT"),), NOW)


def test_actionbar_uses_only_selected_cache_and_self_readiness_is_not_interact_permission(supplement, provider):
    value = payload(supplement, provider)
    value["actionbar"] = [{"kind": "item", "id": ITEM, "action": "ACTIONBUTTON7",
                           "is_usable": True, "cooldown_remaining": 0.}]
    proposal, = planned(value)
    assert proposal.parameters["activation_source"] == "ACTIONBAR"
    assert QuestToolResolver.self_ready(QuestToolResolver.self_state(value, ITEM, [Q], now=NOW))
    assert not QuestToolResolver.can_interact(value, ITEM, GUID, [Q], now=NOW)
    for allowed, expected in [(True, SkillStatus.RUNNING), (False, SkillStatus.FAILURE)]:
        skill = UseItemSkill(SimpleNamespace(contains=lambda action: allowed and action == "ACTIONBUTTON7"))
        result = skill.begin(runtime(value, proposal), value)
        assert result.status is expected
        assert all(c.binding == "ACTIONBUTTON7" for c in result.commands)
    assert not check_command_identity("USE_ON_TARGET", proposal.parameters, {}, value,
        (Command("BIND", "INTERACTTARGET"),), NOW)


def test_one_activation_waits_for_scoped_credit_then_moves_to_next_subject(supplement, provider):
    value = payload(supplement, provider)
    value["packet_entities"][GUID2] = deepcopy(value["packet_entities"][GUID])
    value["packet_entities"][GUID2]["guid"] = GUID2
    domain = QuestDomain()
    proposal, = planned(value, domain)
    assert proposal.parameters["item_aim_guid"] == GUID
    skill, active = UseItemSkill(), runtime(value, proposal)
    assert len(skill.begin(active, value).commands) == 1
    no_credit = deepcopy(value)
    no_credit["packet_entities"].pop(GUID)
    no_credit["quest_item_target"]["items"][0]["cooldown_remaining"] = 5.
    no_credit["events"] = [{"event_type": "ITEM_USED", "payload": {"item_id": ITEM}}]
    no_credit["is_casting"] = True
    for when in (NOW+.5, NOW+3, NOW+6):
        result = skill.verify(active, no_credit, when)
        assert result.status is SkillStatus.RUNNING and not result.commands
    credited = deepcopy(no_credit)
    credited["active_quests"][0]["objectives"][0]["current"] = 1
    result = skill.verify(active, credited, NOW+6.1)
    assert result.status is SkillStatus.SUCCESS and result.evidence == (f"objective_changed:{Q}:0",)
    domain.note_object_interaction_result({"skill": "USE_ON_TARGET", "outcome": "SUCCESS"}, value, proposal.parameters)
    assert planned(value, domain)[0].parameters["item_aim_guid"] == GUID2


@pytest.mark.parametrize("change", ["stage", "quest_flag", "different_objective", "different_quest", "session"])
def test_unrelated_progress_or_session_change_never_credits_item(supplement, provider, change):
    value = payload(supplement, provider)
    value["active_quests"][0]["stage"] = 1
    value["active_quests"][0]["objectives"].append({"objective_id": f"{Q}:1", "current": 0, "required": 1})
    value["active_quests"].append({"quest_id": 99, "objectives": [{"objective_id": "99:0", "current": 0, "required": 1}]})
    proposal, = planned(value)
    skill, active = UseItemSkill(), runtime(value, proposal)
    assert skill.begin(active, value).commands
    after = deepcopy(value)
    if change == "stage": after["active_quests"][0]["stage"] = 2
    elif change == "quest_flag": after["active_quests"][0]["is_complete"] = True
    elif change == "different_objective": after["active_quests"][0]["objectives"][1]["current"] = 1
    elif change == "different_quest": after["active_quests"][1]["objectives"][0]["current"] = 1
    else:
        after["session_id"] = "other:session"
        after["active_quests"][0]["objectives"][0]["current"] = 1
    result = skill.verify(active, after, NOW+1)
    assert result.status is not SkillStatus.SUCCESS and not result.commands
    if change == "session": assert result.reason is FailureReason.IDENTITY_UNCERTAIN
    else:
        result = skill.verify(active, after, NOW+8)
        assert result.reason is FailureReason.QUEST_CREDIT_NOT_RECEIVED


def test_failures_are_bounded_and_failed_movement_does_not_retry_same_trigger_immediately(supplement, provider):
    value = payload(supplement, provider)
    proposal, = planned(value)
    policy = DirectedItemPolicy()
    params = proposal.parameters
    policy.note_result({"skill": "MOVE", "outcome": "FAILURE"}, value, params)
    key = (value["session_id"], f"{Q}:0", GUID)
    assert policy.visits[key] == {"attempts": 1, "until": NOW+45}
    policy.note_result({"skill": "USE_ON_TARGET", "outcome": "FAILURE"}, value, params)
    assert policy.visits[key] == {"attempts": 2, "until": NOW+600}
    assert credit_window(value, params) == 8.


def test_executor_preserves_periodic_effect_window_when_learned_timings_are_short(supplement, provider):
    from wowbot.runtime import SkillExecutor
    value = payload(supplement, provider)
    proposal, = planned(value)
    executor = SkillExecutor(registry=SkillRegistry(), navigation=SimpleNamespace(), target_skill=None,
        interact_skill=None, m0_skills=None, search_skill=None, visual_approach_skill=None)
    memory = SimpleNamespace(learning_context=lambda *a: None, verification_window=lambda *a:
        {"earliest": .01, "likely_start": .1, "likely_end": .2, "deadline": .5})
    attempt = executor.create_attempt(proposal, (), world=SimpleNamespace(state=value,
        latest=SimpleNamespace(observation_id="obs")), goal=SimpleNamespace(domain="quest"),
        current_plan=SimpleNamespace(plan_id="plan"), timeouts=SimpleNamespace(resolve=lambda *a: .5),
        memory=memory, now=NOW)
    assert attempt.deadline == NOW+8


def test_stationary_create_position_stays_valid_until_removal_like_shared_server_projection(supplement, provider):
    value = payload(supplement, provider)
    proposal, = planned(value)
    value["packet_entities"][GUID]["position"]["age"] = 1800.
    assert ready_for_use(value, proposal.parameters, NOW)
    value["packet_entities"][GUID]["position"]["source"] = "PACKET_SPLINE_START"
    assert not ready_for_use(value, proposal.parameters, NOW)


@pytest.mark.parametrize("message,expected", [("Out of range.", FailureReason.OUT_OF_RANGE),
    ("Target not in line of sight", FailureReason.LINE_OF_SIGHT),
    ("You are facing the wrong way!", FailureReason.FACING_FAILED)])
def test_client_range_facing_or_los_errors_end_the_attempt_without_another_activation(supplement, provider, message, expected):
    value = payload(supplement, provider)
    proposal, = planned(value)
    skill, active = UseItemSkill(), runtime(value, proposal)
    assert skill.begin(active, value).commands
    after = deepcopy(value)
    after["events"] = [{"event_type": "UI_ERROR_MESSAGE", "sequence": 1,
                        "payload": {"message": message, "timestamp": NOW+.2}}]
    result = skill.verify(active, after, NOW+.3)
    assert result.status is SkillStatus.FAILURE and result.reason is expected and not result.commands
