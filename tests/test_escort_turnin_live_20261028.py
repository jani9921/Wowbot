"""Input-free regressions for the 15:38-15:45 escort and wrong-floor turn-in."""
from copy import deepcopy
from types import SimpleNamespace

import pytest

from test_active_skill_supervision import supervisor
from test_escort_wagon_20261028 import bulwark, _hold
from test_short_layer_flight_20261027 import BridgeGeometry, request, state
from wowbot.agent.escort_planning import EscortPolicy
from wowbot.agent.models import Goal, Outcome, Proposal
from wowbot.agent.memory_terminal import MemoryTerminalProcessor
from wowbot.agent.movement_controller import ReachMovementController
from wowbot.navigation.global_planner import GlobalNavigator
from wowbot.runtime import SkillStatus


def test_an_escort_hold_yields_to_combat_without_failing_the_escort():
    skill, active = _hold(bulwark())
    fighting = bulwark(t=102.)
    fighting.update(is_in_combat=True, target={'guid': 'enemy', 'attackable': True, 'dead': False})
    result = skill.verify(active, fighting, 102.)
    assert result.status is SkillStatus.CANCELLED and result.replan_required
    assert supervisor(result)._project('WAIT_EVENT', result, fighting).terminal_outcome is Outcome.CANCELLED


def test_a_normal_escort_recheck_is_cancelled_not_a_failed_wait():
    skill, active = _hold(bulwark())
    result = skill.verify(active, bulwark(t=109.), 109.)
    assert result.status is SkillStatus.CANCELLED
    projected = supervisor(result)._project("WAIT_EVENT", result, bulwark(t=109.))
    assert projected.terminal_outcome is Outcome.CANCELLED
    assert "escort_hold_recheck" in projected.diagnostics["verification_evidence"]


@pytest.mark.parametrize("only_objective", [False, True])
def test_a_higher_priority_poi_cannot_outrank_an_engaged_escort(only_objective):
    live = bulwark()
    policy = EscortPolicy()
    hold = policy.propose(live)[0]
    poi = Proposal.make("MOVE", "destination POI", {
        **({"objective_id": "65793:2"} if only_objective else {"quest_id": 65793}),
        "purpose": "LOCATE_QUEST_OBJECTIVE_REGION", "x": 1839., "y": 620.}, priority=140.)
    defend = Proposal.make("DEFEND", "defend escort", {"guid": "enemy"}, priority=160.)
    assert policy.filter_travel([poi, hold, defend], live) == [hold, defend]


def test_a_retained_last_seen_subject_blocks_poi_but_keeps_return_and_loot():
    policy = EscortPolicy()
    policy.propose(bulwark(wagon=(1838.,1120.)))
    lost = bulwark(wagon=(1838.,1120.), removed=True, player=(1843.5,623.7),t=130.)
    back = policy.propose(lost)[0]
    poi = Proposal.make("MOVE", "poi", {"quest_id": 65793, "purpose": "LOCATE_QUEST_OBJECTIVE_REGION"})
    loot = Proposal.make("MOVE", "loot", {"purpose": "APPROACH_SERVER_LOOT", "quest_id": 65793})
    assert policy.filter_travel([poi, back, loot], lost) == [back, loot]
    complete = deepcopy(lost);complete["active_quests"][0]["is_complete"] = True
    assert policy.filter_travel([poi], complete) == [poi]
    assert EscortPolicy().filter_travel([poi], bulwark(ours=False)) == [poi]


def test_another_quests_turnin_cannot_draw_us_away_from_an_active_escort():
    policy = EscortPolicy()
    live = bulwark()
    hold = policy.propose(live)[0]
    other = Proposal.make('MOVE','other turn-in',{'quest_id':999,
        'purpose':'LOCATE_TURN_IN_REGION','x':100.,'y':0.},priority=150.)
    assert policy.filter_travel([other,hold],live) == [hold]


def test_cancelled_waits_keep_timing_audit_but_do_not_poison_learned_success_rates():
    calls = []
    memory = SimpleNamespace(
        record_action_timing=lambda *a: calls.append("timing"),
        learning_context=lambda *a: {}, learn=lambda *a: calls.append("learn"),
        learn_procedure=lambda *a,**k: calls.append("procedure"), save_goal=lambda *a: None)
    attempt = SimpleNamespace(proposal=Proposal.make("WAIT_EVENT", "hold"),started_at=0.,
        action_id="hold",plan_id="plan",prediction=SimpleNamespace(prediction_id="prediction"))
    MemoryTerminalProcessor.process(attempt,Outcome.CANCELLED,"escort_hold_recheck",{},
        Goal.parse("Questelj",0.),10.,SimpleNamespace(verification_id="v",evidence=()),
        memory=memory,contract=SimpleNamespace(cost=1.),latest_observation_id="o",last_received=10.,session_id="s")
    assert calls == ["timing"]


def test_primary_tdb_height_cannot_silently_walk_to_a_different_floor():
    route = GlobalNavigator(navmesh=BridgeGeometry()).plan(
        request(flight=False,z_estimated=True,z_confidence=.8,knowledge_priority="PRIMARY_STATIC"),state(),10.)
    assert not route.anchors


def test_primary_tdb_upper_floor_keeps_a_short_flight_instead_of_lower_walk():
    route = GlobalNavigator(navmesh=BridgeGeometry()).plan(
        request(z_estimated=True,z_confidence=.8,knowledge_priority="PRIMARY_STATIC"),state(),10.)
    assert route.regions[0]["route_source"] == "FLIGHT_PLAN"
    assert route.anchors[-1]["z"] > 240.


def test_navmesh_surface_can_veto_arrival_when_this_page_omitted_own_packet_height():
    controller = ReachMovementController.__new__(ReachMovementController)
    controller.destination = {"z":313.,"z_known":True}
    assert controller._level_distance({"player_world_position":{
        "z":128.,"z_source":"NAVMESH_SURFACE","z_observed":False}},.7) == 185.
