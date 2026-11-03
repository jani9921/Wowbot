"""Design spec 32: mechanic registry names, full MechanicContract, target roles,
a branching QuestExecutionGraph and the diagnostic failure taxonomy."""
from wowbot.quests.mechanics import MechanicNodeState, MechanicResolver, QuestExecutionGraph
from wowbot.quests.playbooks import PLAYBOOKS, registry_name
from wowbot.runtime import FailureReason
from wowbot.runtime.contracts import failure_reason_from_legacy
from wowbot.runtime.failures import FailureManager


def names(nodes):
    return {n.name: n for n in nodes}


def test_registry_names_follow_the_spec_and_unknown_is_never_guessed():
    assert registry_name("COLLECT_DROP") == "KILL_FOR_ITEM"
    assert registry_name("USE_ITEM", "SELF") == "USE_ITEM_SELF"
    assert registry_name("USE_ITEM", "GROUND") == "USE_ITEM_AT_LOCATION"
    assert registry_name("ARRIVE") == "EXPLORE_LOCATION"
    assert registry_name("PET_BATTLE") == "UNKNOWN_MECHANIC"


def test_the_contract_names_success_failures_and_recovery_and_the_target_roles():
    contract = MechanicResolver().resolve(5, "5:0", {"mechanism": "KILL", "target_location":
        {"x": 1., "y": 2., "z": 3., "instance_id": 0, "source": "SERVER_POI"}},
        {"credit_object_id": 900, "area_triggers": [88]})
    assert contract.registry_name == "KILL_TARGET" and contract.success_condition == "objective_progress_verified"
    assert "TARGET_MISSING" in contract.failure_reasons
    assert ("TARGET", "TARGET_MISSING", ("APPROACH",)) in contract.recovery_options
    assert contract.targets.nav_target == {"x": 1., "y": 2., "z": 3., "instance_id": 0, "source": "SERVER_POI"}
    assert contract.targets.search_region == {"kind": "AREA_TRIGGERS", "ids": [88]}
    unknown = MechanicResolver().resolve(5, "5:0", {"mechanism": "PET_BATTLE"})
    assert unknown.failure_reasons == ("MECHANIC_UNKNOWN",) and unknown.success_condition.startswith("unsupported")


def test_conditional_branches_never_block_and_or_alternatives_open_the_next_step():
    escort = QuestExecutionGraph().build(MechanicResolver().resolve(1, "1:0", {"mechanism": "ESCORT"}),
                                         verified_steps=("TALK", "DIALOG", "FOLLOW"))
    nodes = names(escort)
    assert nodes["DEFEND"].state is MechanicNodeState.CONDITIONAL and nodes["DEFEND"].condition
    assert nodes["RESTART"].dependencies == (nodes["FOLLOW"].node_id,)
    kill = names(QuestExecutionGraph().build(MechanicResolver().resolve(1, "1:0", {"mechanism": "KILL"}),
                                             verified_steps=("APPROACH", "TARGET", "FIGHT")))
    assert kill["LOOT"].state is MechanicNodeState.CONDITIONAL
    probe = QuestExecutionGraph().build(MechanicResolver().resolve(1, "1:0", {"mechanism": "SPELL_CREDIT"}),
                                        verified_steps=("APPROACH", "PROBE_OBJECT"))
    nodes = names(probe)
    assert nodes["PROBE_OBJECT"].dependencies == nodes["PROBE_TALK"].dependencies
    assert set(nodes["OBSERVE"].any_of) == {nodes["PROBE_TALK"].node_id, nodes["PROBE_OBJECT"].node_id}
    assert nodes["OBSERVE"].state is MechanicNodeState.READY           # the object alternative was enough


def test_the_spec_failure_taxonomy_types_reasons_and_names_a_recovery():
    assert failure_reason_from_legacy("trip_final_floor_not_verified") is FailureReason.WRONG_FLOOR
    assert failure_reason_from_legacy("selected_cache_missing_extra_action_binding") is FailureReason.MISSING_BINDING
    assert failure_reason_from_legacy("ROUTE_UNREACHABLE") is FailureReason.NO_ROUTE
    assert failure_reason_from_legacy("MISSING_ITEM") is FailureReason.EXPECTED_ITEM_NOT_RECEIVED
    for reason in ("WRONG_FLOOR", "MISSING_BINDING", "MECHANIC_UNKNOWN", "PHASE_MISMATCH",
                   "WAITING_SERVER_STATE", "SCENE_NOT_RESOLVED", "SPELL_NO_EFFECT", "LOCATION_UNKNOWN"):
        assert FailureManager.recovery_for(FailureReason[reason]) != "DOMAIN_RECOVERY"
