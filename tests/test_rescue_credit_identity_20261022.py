"""Live 65990 exports a concrete credit actor but no separate named list."""
import pytest

from wowbot.agent.packet_entity_facts import kill_objective_entries, rescue_objects
from wowbot.agent.rescue_object_planning import (
    open_rescue_entries, rescue_soft_target, SoftInteractRescuePolicy, RescueTargetPolicy,
    RescueObjectPolicy)

GUID = "Creature-0-3769-2444-47-194231-0000D824CA"


def state():
    return {"monotonic_time":100., "map_id":2022, "soft_targets_sample_time":100.,
        "orientation":0., "target":{},
        "player_world_position":{"x":2894.7,"y":-1021.,"z":45.2,"z_observed":True,
                                 "instance_id":2444,"coordinate_space":"WORLD_YARDS"},
        "active_quests":[{"quest_id":65990,"is_complete":False,"objectives":[
            {"description":"0/4 Whimpering Whelplings saved","type":"KILL","raw_type":"monster",
             "current":0,"required":4,"is_complete":False}]}],
        "reference_knowledge":{"quests":{"65990":{"objectives":[{
            "description":"Whimpering Whelplings saved","credit_kind":"CREATURE_CREDIT",
            "credit_name":"Whimpering Whelpling","credit_object_id":194231,
            "named_creatures":[],"credit_creatures":[]}]}}},
        "packet_entities":{GUID:{"guid":GUID,"kind":"CREATURE","entry_id":194231,"map_id":2444,
            "info":{"npc_flags":0x1000000},"dynamic_flags":{"value":0},
            "position":{"x":2891.73,"y":-1007.91,"z":62.68,"age":20.,
                        "source":"PACKET_CREATE_MOVEMENT"}}},
        "soft_targets":[]}


def soft(st, **extra):
    point=st["packet_entities"][GUID]["position"]
    st["player_world_position"].update(x=point["x"]-2.,y=point["y"],z=point["z"])
    st["soft_targets"]=[{"guid":GUID,"npc_id":194231,"unit_type":"NPC",
                         "source_unit":"softinteract","is_attackable":False,"is_dead":False,**extra}]
    return st


def test_real_credit_entry_is_eligible_for_rescue_but_never_a_kill_target():
    st=state()
    assert open_rescue_entries(st)=={"194231":"65990"}
    assert kill_objective_entries(st)=={}


def test_fresh_exact_soft_recipient_uses_the_existing_rescue_interaction():
    st=soft(state())
    assert rescue_soft_target(st)["guid"]==GUID
    proposal,=SoftInteractRescuePolicy().propose(st)
    assert proposal.skill=="INTERACT" and proposal.parameters["soft_guid"]==GUID


@pytest.mark.parametrize("change", ["hostile","stale","other_npc","credited","proxy","object_credit"])
def test_credit_reference_never_bypasses_live_identity_or_completion(change):
    st=soft(state())
    row=st["reference_knowledge"]["quests"]["65990"]["objectives"][0]
    if change=="hostile":st["soft_targets"][0]["is_attackable"]=True
    elif change=="stale":st["soft_targets_sample_time"]=90.
    elif change=="other_npc":st["soft_targets"][0].update(guid="other",npc_id=1)
    elif change=="credited":st["active_quests"][0]["objectives"][0]["is_complete"]=True
    elif change=="proxy":row["credit_name"]="Kill Credit: Rescue Whelps [DNT]"
    else:row["credit_kind"]="GAMEOBJECT"
    assert SoftInteractRescuePolicy().propose(st)==[]


def test_known_spellclick_actor_is_approached_on_its_real_floor_before_friend_tab():
    proposal,=RescueTargetPolicy().propose(state())
    assert proposal.skill=="MOVE"
    assert proposal.parameters["server_entity_guid"]==GUID
    assert proposal.parameters["purpose"]=="APPROACH_RESCUE_NPC"
    assert proposal.parameters["z"]==62.68 and proposal.parameters["require_navmesh"] is True
    assert proposal.parameters["face_on_arrival"] is True


@pytest.mark.parametrize("change", ["removed","other_instance","lootable","no_spellclick"])
def test_missing_or_unsafe_packet_actor_does_not_trigger_blind_friend_tab(change):
    st=state();entity=st["packet_entities"][GUID]
    if change=="removed":entity["removed"]={"reason":"DESTROYED"}
    elif change=="other_instance":entity["map_id"]=2175
    elif change=="lootable":entity["dynamic_flags"]["value"]=4
    else:entity["info"]["npc_flags"]=0
    assert RescueTargetPolicy().propose(st)==[]


def test_age_only_updates_do_not_give_one_rescue_npc_a_new_movement_retry_identity():
    st=state()
    first=RescueTargetPolicy().propose(st)[0]
    st["packet_entities"][GUID]["position"]["age"]=22.
    second=RescueTargetPolicy().propose(st)[0]
    assert first.key==second.key


def test_nullable_unit_flags_do_not_crash_a_known_spellclick_actor_approach():
    st=state()
    st["packet_entities"][GUID]["dynamic_flags"]["value"]=None
    proposal,=RescueTargetPolicy().propose(st)
    assert proposal.skill=="MOVE" and proposal.parameters["server_entity_guid"]==GUID


def test_concrete_actor_under_soft_interact_presses_interact_then_waits_for_credit():
    from copy import deepcopy
    from wowbot.agent.models import Attempt, Prediction
    from wowbot.runtime import ActiveSkillRuntime, Intent, SkillStatus
    from wowbot.skills import InteractSkill

    st=soft(state())
    st["quest_digest"]=[{"id":65990,"done":0}]
    proposal,=SoftInteractRescuePolicy().propose(st)
    attempt=Attempt("rescue",proposal,st,"o",100.,107.,(),
                    Prediction("p","rescue","credit",100.,107.,"o"))
    active=ActiveSkillRuntime().start(intent=Intent(proposal.skill,proposal.parameters),
                                    attempt=attempt,now=100.,before_snapshot=st)
    skill=InteractSkill()
    started=skill.begin(active,st)
    assert [(c.kind,c.binding) for c in started.commands]==[("BIND","INTERACTTARGET")]
    waiting=skill.verify(active,{**st,"monotonic_time":102.,"soft_targets_sample_time":102.},102.)
    assert waiting.status is SkillStatus.RUNNING and not waiting.commands
    credited=deepcopy(st)
    credited.update(monotonic_time=103.5,soft_targets_sample_time=103.5,
                    quest_digest=[{"id":65990,"done":1}])
    result=skill.verify(active,credited,103.5)
    assert result.status is SkillStatus.SUCCESS and "rescue_objective_progress" in result.evidence


def test_an_actual_holding_object_keeps_the_existing_object_use_branch():
    st=state()
    point=st["packet_entities"][GUID]["position"]
    cage="GameObject-0-3769-2444-47-379137-0000000001"
    st["packet_entities"][cage]={"guid":cage,"kind":"GAMEOBJECT","entry_id":379137,
        "map_id":2444,"info":{"go_type":10},"position":point.copy()}
    st["player_world_position"].update(x=point["x"]-1.,y=point["y"],z=point["z"])
    proposal,=RescueObjectPolicy().propose(st)
    assert proposal.skill=="OBJECT_USE"
    assert proposal.parameters["object_guid"]==cage
    assert proposal.parameters["rescue_npc_guid"]==GUID
