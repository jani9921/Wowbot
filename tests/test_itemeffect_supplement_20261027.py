"""DB2 provenance, item/credit association and command-boundary regressions."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import sqlite3
import struct

import pytest

from wowbot.agent.models import Attempt, Goal, Observation, Prediction, Proposal
from wowbot.agent.quest_item_knowledge import annotate_items, authorized_item
from wowbot.agent.quest_model import QuestModel
from wowbot.agent.quest_planning import QuestDomain
from wowbot.agent.quest_semantics import combat_subjects, use_on_subjects
from wowbot.agent.skills import SkillRegistry
from wowbot.agent.world import WorldModel
from wowbot.quests.client_supplement import ClientSupplement, target_profile
from wowbot.runtime import ActiveSkillRuntime, Intent, SkillStatus
from wowbot.skills.quest_item import UseItemSkill

spec = importlib.util.spec_from_file_location("supplement_builder",
    Path(__file__).parents[1]/"tools/build_client_supplement.py")
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)

GUID = "Creature-0-1-2175-1-901-0000000001"


@pytest.fixture
def supplement(tmp_path):
    path = tmp_path/"client_supplement.sqlite3"
    with sqlite3.connect(path) as db:
        db.executescript(builder.SCHEMA)
        db.execute("PRAGMA user_version=1")
        db.execute("INSERT INTO items VALUES (44,'Test Re-Sizer','',0)")
        db.execute("INSERT INTO item_effects VALUES (1,700,0,0,0,8000,-1,0,0,0)")
        db.execute("INSERT INTO item_effects VALUES (2,702,1,1,0,-1,-1,0,0,0)")
        db.execute("INSERT INTO item_effect_links VALUES (1,44,1)")
        db.execute("INSERT INTO item_effect_links VALUES (2,44,2)")
        db.execute("INSERT INTO spell_effects VALUES (10,700,0,64,0,701,0,0,6,0)")
        db.execute("INSERT INTO spell_effects VALUES (11,701,0,90,0,0,900,0,25,0)")
        # A different difficulty must not change the normal use or its credit.
        db.execute("INSERT INTO spell_effects VALUES (12,700,1,90,0,0,999,0,87,0)")
        db.execute("INSERT INTO spell_names VALUES (700,'Shrink')")
    return ClientSupplement(path)


def references(supplement):
    value = {"quests": {"7": {"quest_id": 7, "items": {"start_item_id": 44}, "objectives": [{
        "objective_id": 1001, "order": 0, "raw_type": 0, "credit_kind": "CREATURE_CREDIT",
        "credit_object_id": 900, "credit_name": "Kill Credit: Resize [DNT]",
        "named_creatures": [{"entry": 901, "name": "Wandering Boar"}],
        "description": "Boars resized", "amount": 2}]}}}
    annotate_items(value["quests"]["7"], supplement)
    return value


def payload(supplement):
    return {"session_id": "test:itemeffect", "monotonic_time": 1., "timestamp": 1.,
        "active_quests": [{"quest_id": 7, "is_complete": False, "special_item": {"item_id": 44},
            "objectives": [{"objective_id": "7:0", "type": "KILL", "description": "Boars resized",
                            "current": 0, "required": 2, "is_complete": False}]}],
        "reference_knowledge": references(supplement),
        "target": {"guid": GUID, "npc_id": 901, "name": "Wandering Boar", "attackable": True, "dead": False},
        "target_sample_time": 1., "actionbar": [{"kind": "item", "id": 44, "action": "ACTIONBUTTON7",
        "is_usable": True, "in_range": True, "cooldown_remaining": 0.}]}


class Bindings:
    def contains(self, name):
        return name == "ACTIONBUTTON7"


def active(value, **extra):
    params = {"guid": GUID, "npc_id": 901, "quest_ids": [7], "objective_ids": ["7:0"],
              "item_id": 44, "binding": "ACTIONBUTTON7", "item_spell_id": 700,
              "item_target_mode": "UNIT", **extra}
    if params.get("target_required") is False:
        params.pop("guid", None)
        params.pop("npc_id", None)
    proposal = Proposal.make("USE_ON_TARGET", "test", params)
    attempt = Attempt("item", proposal, value, "obs", 1., 5., (),
                      Prediction("p", "item", "credit", 1., 5., "obs"))
    return ActiveSkillRuntime().start(intent=Intent("USE_ON_TARGET", params, params.get("guid"), "7:0"),
                                     attempt=attempt, now=1., before_snapshot=value)


def test_real_link_on_use_filter_trigger_chain_and_difficulty(supplement):
    item = supplement.item(44)
    assert len(item["effects"]) == 2 and len(item["uses"]) == 1
    use = item["uses"][0]
    assert (use["spell_id"], use["target_mode"], use["cooldown_ms"]) == (700, "UNIT", 8000)
    assert use["credit_links"] == [{"kind": "CREATURE_CREDIT", "id": 900,
        "spell_chain": [700, 701], "effect_id": 11, "conditional": True}]
    assert not use["credit_search_truncated"]


@pytest.mark.parametrize("targets,mask,expected", [
    ([6], 0, "UNIT"), ([1], 0, "SELF"), ([87], 0, "GROUND"),
    ([23], 0, "GAMEOBJECT"), ([26], 0, "ITEM_OR_GAMEOBJECT"),
    ([1, 16], 0, "AREA"), ([999], 0, "UNKNOWN"),
    ([6, 21], 0, "MIXED"), ([6], 0x40, "MIXED"), ([1], 0x40, "GROUND"),
])
def test_selectors_do_not_turn_ground_area_unknown_or_object_into_unit_use(targets, mask, expected):
    rows = [{"target_a": n, "target_b": 0} for n in targets]
    assert target_profile(rows, [{"target_mask": mask}])["target_mode"] == expected


def test_quest_model_routes_exact_credit_to_item_without_attacking_proxy(supplement):
    value = payload(supplement)
    model = QuestModel()
    model.ingest(value["active_quests"], "obs", 1.)
    model.apply_reference_knowledge(value["reference_knowledge"])
    obj = model.records[7].objectives[0]
    assert obj.type == "USE_ITEM_ON_TARGET"
    assert obj.target_object["item_id"] == 44
    assert obj.target_entity["npc_id"] == 901  # actual subject, not credit proxy 900
    assert use_on_subjects(obj.raw) == ["Wandering Boar"]
    assert not combat_subjects(obj.raw)
    assert obj.current_count == 0
    model.apply_reference_knowledge({})
    assert obj.type == "KILL" and obj.target_object is None and obj.target_entity is None
    assert "db2_item_use" not in obj.raw


def test_ambiguous_items_and_collect_item_are_not_guessed(supplement):
    ref = references(supplement)
    row = ref["quests"]["7"]["objectives"][0]
    row["item_uses"].append({**row["item_uses"][0], "item_id": 45})
    value = payload(supplement)
    value["active_quests"][0].pop("special_item")
    model = QuestModel()
    model.ingest(value["active_quests"], "obs", 1.)
    model.apply_reference_knowledge(ref)
    obj = model.records[7].objectives[0]
    assert obj.type == "KILL" and obj.raw["db2_item_status"] == "AMBIGUOUS"
    # A collect objective with an already identified collected item cannot be
    # overwritten with a different quest tool.
    obj.target_object = {"item_id": 999}
    model.apply_reference_knowledge(references(supplement))
    assert obj.target_object["item_id"] == 999


def test_command_boundary_uses_exact_spell_recipient_and_credit_only(supplement):
    value = payload(supplement)
    skill = UseItemSkill(Bindings())
    runtime = active(value)
    started = skill.begin(runtime, value)
    assert started.status is SkillStatus.RUNNING and started.commands[0].binding == "ACTIONBUTTON7"
    assert skill.verify(runtime, value, 2.).status is SkillStatus.RUNNING
    credited = deepcopy(value)
    credited["active_quests"][0]["objectives"][0]["current"] = 1
    assert skill.verify(runtime, credited, 2.1).status is SkillStatus.SUCCESS
    for change in ("spell", "relation", "guid", "quest"):
        bad = deepcopy(value)
        if change == "spell":
            bad["reference_knowledge"]["quests"]["7"]["items"]["use_profiles"]["44"]["uses"][0]["spell_id"] = 999
        elif change == "relation":
            bad["target"]["attackable"] = False
        elif change == "guid":
            bad["target"]["guid"] = "Other"
        else:
            bad["active_quests"][0]["is_complete"] = True
        result = skill.begin(active(value), bad)
        assert not result.commands and result.status in {SkillStatus.BLOCKED, SkillStatus.FAILURE}


def test_domain_passes_item_effect_through_real_skill_registry(supplement):
    value = payload(supplement)
    world = WorldModel()
    world.ingest(Observation.create(value, 1.))
    world.ingest(Observation.create({"session_id": value["session_id"],
                 "reference_knowledge": value["reference_knowledge"]}, 1., source="REFERENCE_MEMORY"))
    proposals = QuestDomain().propose(world, Goal.parse("Questelj", 1.))
    uses = [p for p in proposals if p.skill == "USE_ON_TARGET"]
    assert uses and uses[0].parameters["item_spell_id"] == 700
    assert uses[0].parameters["npc_id"] == 901
    assert SkillRegistry(bindings=Bindings()).available(uses[0], world)


def test_self_use_never_clicks_an_unrelated_target(supplement):
    value = payload(supplement)
    profile = value["reference_knowledge"]["quests"]["7"]["items"]["use_profiles"]["44"]["uses"][0]
    profile.update(target_mode="SELF", target_relation="ANY")
    # Unrelated selected corpse does not block self use or receive a click.
    value["target"] = {"guid": "Other", "dead": True}
    skill = UseItemSkill(Bindings())
    runtime = active(value, target_required=False, item_target_mode="SELF")
    assert skill.begin(runtime, value).status is SkillStatus.RUNNING
    result = skill.verify(runtime, value, 2.)
    assert result.status is SkillStatus.RUNNING and not result.commands


def test_missing_supplement_and_no_on_use_remain_explicit(tmp_path, supplement):
    assert ClientSupplement(tmp_path/"missing.sqlite3").item(44)["status"] == "MISSING"
    assert supplement.item(999)["status"] == "NO_ON_USE_EFFECT"


def test_reference_can_authorize_visible_item_without_special_item_api(supplement):
    value = payload(supplement)
    value["active_quests"][0].pop("special_item")
    assert authorized_item(value, 44, [7])
    value["active_quests"][0]["objectives"][0]["is_complete"] = True
    assert not authorized_item(value, 44, [7])


def test_reference_range_is_used_for_approach_estimate_without_changing_identity():
    from wowbot.agent.quest_item_knowledge import maximum_range
    use = {"target_relation": "HOSTILE", "ranges": [{"RangeMax": [15., 30.]}]}
    assert maximum_range(use) == 15.
    state = {"player_world_position": {"x": 0., "y": 0., "z": 0., "z_known": True, "instance_id": 2175}}
    target = {"world_position": {"x": 10., "y": 0., "z": 0., "coordinate_space": "WORLD_YARDS",
                                 "source": "PACKET_ENTITY", "instance_id": 2175}}
    domain = QuestDomain()
    assert not domain._item_target_far(state, target, use)
    target["world_position"]["z"] = 20.
    assert domain._item_target_far(state, target, use)


@pytest.mark.parametrize("mode,arrived,expected", [("SELF", False, False), ("SELF", True, True),
                                                  ("GROUND", True, False)])
def test_planner_self_use_requires_existing_arrival_and_ground_use_is_explicitly_unsupported(
        supplement, mode, arrived, expected):
    value = payload(supplement)
    profile = value["reference_knowledge"]["quests"]["7"]["items"]["use_profiles"]["44"]["uses"][0]
    profile.update(target_mode=mode, target_relation="ANY")
    value["target"] = {"guid": "unrelated", "dead": True}
    world = WorldModel()
    world.ingest(Observation.create(value, 1.))
    world.ingest(Observation.create({"session_id": value["session_id"],
                 "reference_knowledge": value["reference_knowledge"]}, 1., source="REFERENCE_MEMORY"))
    domain = QuestDomain()
    domain.location_policy.propose_objective = lambda *args: (
        [Proposal.make("SEEK_VISUAL_CUE", "arrived", {"purpose": "SEARCH_LOCAL_OBJECTIVE_AREA"})]
        if arrived else [Proposal.make("MOVE", "travel", {"x": 10., "y": 0.})])
    proposals = []
    domain._propose_objectives(world, world.state, 1., world.quest_model.records, "7", "7:0", False, proposals)
    uses = [p for p in proposals if p.skill == "USE_ON_TARGET"]
    assert bool(uses) is expected
    if expected:
        assert uses[0].parameters["target_required"] is False
        assert not uses[0].parameters.get("guid")
        assert SkillRegistry(bindings=Bindings()).available(uses[0], world)
    if mode == "GROUND":
        assert any(p.parameters.get("purpose") == "UNSUPPORTED_ITEM_MECHANIC" for p in proposals)


def test_export_provenance_failure_does_not_publish_catalogue(tmp_path):
    source, decoded, definitions = [tmp_path/name for name in ("db2", "export", "dbd")]
    for path in (source, decoded, definitions):
        path.mkdir()
    raw = bytearray(204)
    raw[:4] = b"WDC5"
    raw[8:12] = b"TEST"
    struct.pack_into("<I", raw, 156, 0x112233)
    for table in builder.REQUIRED:
        (source/(table+".db2")).write_bytes(raw)
        (definitions/(table+".dbd")).write_text("fixture")
        manifest = {"type": "table", "name": table, "row_count": 0, "layout_hash": "00112233",
                    "source_sha256": "wrong", "definition_sha256": "wrong"}
        (decoded/(table+".jsonl")).write_text(json.dumps(manifest)+"\n")
    output = tmp_path/"client_supplement.sqlite3"
    with pytest.raises(ValueError, match="provenance"):
        builder.build(output, source, decoded, definitions, tmp_path/"unused.sqlite3", "test")
    assert not output.exists() and not list(tmp_path.glob("*.partial-*"))
