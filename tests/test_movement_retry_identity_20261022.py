"""Navigation explanation/resume metadata must not mint new attempt identities."""
from types import SimpleNamespace

import pytest

from test_agent_core import agent, state
from test_navigation_proposal_adapter import Navigation
from test_planning_orchestration import orchestrator, Supervisor, World
from wowbot.agent.models import Proposal, Outcome
from wowbot.agent.navigation_planning import NavigationProposalAdapter
from wowbot.runtime import Intent, FailureReason, failure_reason_from_legacy
from wowbot.navigation import NavigationContextClassifier, TransitionResolver


PARAMS = {"coordinate_space":"WORLD_YARDS", "instance_id":2444, "map_id":2022,
          "x":2918.2, "y":-986.8, "z":44.76, "require_navmesh":True,
          "purpose":"APPROACH_SERVER_CORPSE", "server_entity_guid":"corpse:own"}


def move(**extra):
    return Proposal.make("MOVE", "server corpse", {**PARAMS, **extra}, priority=112.)


def test_navigation_annotation_and_duplicate_world_map_alias_keep_the_same_key():
    original = move()
    world = SimpleNamespace(state={"session_id":"live:pid14540", "map_id":2022,
        "player_world_position":{"coordinate_space":"WORLD_YARDS","instance_id":2444,
                                 "x":2894.7,"y":-1021.,"z":45.2,"z_observed":True},
        "movement":{"indoors":False}})
    nav = Navigation()
    nav.current_navigation_context = NavigationContextClassifier().classify
    nav.resolve_transition = TransitionResolver().resolve
    adapted = NavigationProposalAdapter(nav).adapt(original, [original], world, 1.)
    assert adapted.skill == "MOVE"
    assert adapted.parameters["navigation_context"] == "OUTDOOR"
    assert adapted.parameters["world_map_id"] == 2444
    assert adapted.key == original.key


@pytest.mark.parametrize("extra", [
    {"navigation_context":"CAVE", "navigation_context_confidence":.7,
     "navigation_context_evidence":["fresh-floor"], "route_expectation":"CORRIDOR"},
    {"_resume_token":"runtime:second", "_resume_after_recovery":True},
    {"world_map_id":2444},
])
def test_explanation_and_resume_tokens_do_not_clear_failure_backoff(extra):
    assert move(**extra).key == move().key


@pytest.mark.parametrize("extra", [
    {"x":2920.}, {"z":50.}, {"instance_id":2175}, {"server_entity_guid":"different-corpse"},
    {"purpose":"LOCATE_TURN_IN_REGION"}, {"stop_distance":3.},
    {"require_navmesh":False}, {"world_map_id":2175},
])
def test_real_destination_identity_and_safety_contract_changes_stay_distinct(extra):
    assert move(**extra).key != move().key


def test_supervisor_resume_cannot_bypass_a_current_route_failure_cooldown():
    original = move()
    supervisor = Supervisor(SimpleNamespace(intent=Intent("MOVE",original.parameters),token="saved:1"))
    value, planner = orchestrator([Proposal.make("WAIT","route temporarily blocked")],supervisor=supervisor)
    planner.blocked_until[original.key] = 40.
    result = value.choose(object(), World(), {}, 10., recovery_resume=None,recovery_resume_ready=False)
    assert result.proposal.skill == "WAIT"
    assert supervisor.resume is not None and supervisor.cleared is None


def test_required_mesh_failure_has_path_recovery_semantics_not_internal_error():
    assert failure_reason_from_legacy("required_navmesh_route_unavailable") is FailureReason.PATH_BLOCKED


def test_a_failed_adapted_move_cools_the_original_policy_proposal():
    bot, _ = agent("Menj oda", {"destination":PARAMS})
    original = move()
    bot.planner.candidates = lambda *args: [original]
    # Install the normal physical route, then fail it without any client input.
    bot.tick(state(1., player_world_position={"coordinate_space":"WORLD_YARDS",
        "instance_id":2444,"x":2894.7,"y":-1021.,"z":45.2,"z_observed":True}),1.)
    assert bot.pending is not None
    assert bot.pending.proposal.key == original.key
    bot._finish(Outcome.FAILURE, "required_navmesh_route_unavailable",1.2)
    assert bot.planner.blocked_until[original.key] > 1.2
