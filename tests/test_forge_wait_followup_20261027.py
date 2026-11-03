"""18:47/18:51 user-run forge regressions: wrong inferred floor and sticky WAIT."""
from copy import deepcopy

import pytest

from wowbot.agent.goal_manager import GoalManager
from wowbot.agent.models import Goal
from wowbot.agent.object_interaction_flow import ObjectInteractionFlow
from wowbot.agent.planner import Planner
from wowbot.agent.skills import SkillRegistry
from wowbot.runtime import FailureManager, FailureReason, SkillStatus
from wowbot.runtime.contracts import failure_reason_from_legacy
from wowbot.skills.object_use import ObjectUseSkill
from test_forge_interaction_20261027 import FORGE, forge, active_use
from test_linked_big_object_20261027 import large
from test_linked_quest_object_20261026 import TABLE


class MeasuredStartGeometry:
    def supports(self, instance):
        return instance == 2444

    def walkable_heights_at(self, instance, point, radius=2.5):
        return [203., 207.5, 254.]

    def find_path(self, instance, start, destination):
        from wowbot.navigation.mmap_navmesh import NavMeshPath
        if not start.get("z_observed"):
            return None
        return NavMeshPath((start, {**destination, "z": 207.5}), 1, 0, 5.)


def corner_without_z():
    state = forge(corner=True)
    state["player_world_position"].pop("z")
    state["player_world_position"].update(z_known=False, z_observed=False)
    point = state["packet_entities"][FORGE]["position"]
    spot = {**point, "guid": FORGE, "object_id": 377013, "instance_id": 2444, "distance": 14.89}
    return state, spot


def test_exact_current_recipient_hands_move_to_use_despite_wrong_inferred_navmesh_floor():
    state, spot = corner_without_z()
    flow = ObjectInteractionFlow()
    assert flow.packet_interact_ready(state, spot, 202.89) == "READY"
    params = {"purpose": "APPROACH_QUEST_OBJECT_SPAWN", "quest_id": 66056, "server_entity_guid": FORGE}
    assert flow.object_move_handoff(state, params, 202.89)["kind"] == "SERVER_QUEST_OBJECT_READY"
    assert ObjectUseSkill.packet_object_usable({"object_guid": FORGE, "server_interaction_range": 3.5}, state)
    # A projected state itself is also explicitly estimated, not measured.
    state["player_world_position"].update(z=202.89, z_known=True, z_estimated=True)
    assert flow.packet_interact_ready(state, spot, 202.89) == "READY"


@pytest.mark.parametrize("source", ["raw", "projection"])
def test_measured_other_floor_still_blocks_a_soft_guid(source):
    state, spot = corner_without_z()
    if source == "raw":
        state["player_world_position"].update(z=232., z_known=True, z_observed=True)
    else:
        state["player_world_position"].update(z=207., z_estimated=True, observed_z=232.)
    assert ObjectInteractionFlow().packet_interact_ready(state, spot, 207.) == "OTHER_FLOOR"


@pytest.mark.parametrize("change", ["missing", "stale", "other"])
def test_unknown_floor_never_turns_a_collision_or_wrong_recipient_into_f7_proof(change):
    state, spot = corner_without_z()
    if change == "missing":
        state["soft_targets"] = []
    elif change == "stale":
        state["soft_targets_sample_time"] = 90.
    else:
        state["soft_targets"][0]["guid"] = "Creature-0-1-2444-1-1-0000000001"
    assert ObjectInteractionFlow().packet_interact_ready(state, spot, 202.89) != "READY"


@pytest.mark.parametrize("reason", ["ambiguous_player_layer", "ambiguous_player_layer_after_fall"])
def test_uncertain_floor_uses_bounded_position_recovery_and_does_not_permanently_ban_the_move(reason):
    state = forge()
    state["player_world_position"].pop("z")
    state["player_world_position"]["z_known"] = False
    planner = Planner(SkillRegistry())
    proposal = planner.quest.server_npcs.propose(state)[0]
    goal = Goal.parse("Questelj", 100.)
    typed = failure_reason_from_legacy(reason)
    assert typed is FailureReason.POSITION_UNCERTAIN
    decision = FailureManager().record_failure(correlation_id=proposal.key, skill="MOVE", reason=typed, at=100.)
    assert decision.retry_allowed and decision.recovery_action == "REOBSERVE_POSITION"
    planner.record_terminal_decision(proposal, goal, type("World", (), {"state": state})(),
                                     decision, success=False, now=100.)
    state["player_world_position"].update(z=207.38, z_known=True, z_observed=True)
    assert planner.filter_decision_loops([proposal], goal, state) == [proposal]


def test_three_unknown_floor_observations_do_not_mark_the_quest_move_unresolved_for_two_minutes():
    manager = GoalManager()
    manager.set_goal(Goal.parse("Questelj", 100.), 100.)
    registry = SkillRegistry()
    proposal = Planner(registry).quest.server_npcs.propose(forge())[0]
    failures = FailureManager()
    for index in range(3):
        manager.register(proposal, registry.contracts["MOVE"], 100.+index)
        decision = failures.record_failure(correlation_id=proposal.key, skill="MOVE",
                    reason=FailureReason.POSITION_UNCERTAIN, at=100.+index)
        manager.outcome(proposal, False, "ambiguous_player_layer", 100.+index, decision)
    assert all(task.status != "UNRESOLVED" and task.blocked_until == 0. for task in manager.tasks.values())
    assert manager.filter([proposal], registry.contracts, 104.) == [proposal]


def pending_floor_navigation():
    from wowbot.agent.server_npc_planning import ServerNpcInteractionPolicy
    from wowbot.navigation.service import NavigationService
    from wowbot.navigation.contracts import NavigationRequest
    state = forge()
    state["player_world_position"].pop("z")
    state["player_world_position"].update(z_known=False, sample_time=100.)
    move = ServerNpcInteractionPolicy().propose(state)[0]
    nav = NavigationService(navmesh=MeasuredStartGeometry())
    nav.start_request(NavigationRequest("same-move", "same-action", "MOVE_TO_LOCATION", move.parameters), state, 100.)
    assert nav._route_failure_reason == "ambiguous_player_layer"
    return nav, state


def test_own_height_before_terminal_handoff_replans_same_owned_move_instead_of_returning_latched_failure():
    nav, state = pending_floor_navigation()
    state["player_world_position"].update(z=207.38, z_known=True, z_observed=True, sample_time=101.)
    result = nav.observe(state, "new-own-height", 101.)
    assert not result.terminal and result.reason == "route_replanned_from_observed_position"
    assert nav._active_request.request_id == "same-move"
    assert nav._request_started_at == 100.  # original timeout is retained
    assert nav._active_route.anchors and nav._route_failure_reason is None


@pytest.mark.parametrize("change", ["old", "estimated", "expired", "cancelled"])
def test_a_latched_floor_failure_is_not_rearmed_by_stale_guessed_expired_or_cancelled_state(change):
    nav, state = pending_floor_navigation()
    now = 101.
    state["player_world_position"].update(z=207.38, z_known=True, z_observed=True, sample_time=101.)
    if change == "old":
        state["player_world_position"]["sample_time"] = 99.
    elif change == "estimated":
        state["player_world_position"]["z_observed"] = False
    elif change == "expired":
        now = 1000.
        state["player_world_position"]["sample_time"] = now
    else:
        nav.cancel_movement()
    result = nav.observe(state, "no-resume", now)
    assert result.reason != "route_replanned_from_observed_position"


def test_interrupted_use_cast_does_not_blacklist_the_reachable_forge_corner():
    from wowbot.agent.server_npc_planning import ServerNpcInteractionPolicy
    state = large(soft=TABLE)
    (proposal,) = ServerNpcInteractionPolicy().propose(state)
    active = active_use(state, proposal.parameters)
    skill = ObjectUseSkill()
    assert skill.begin(active, state).commands
    state.update(monotonic_time=11., soft_targets_sample_time=11., ui_error="Interrupted", ui_error_at=10.8)
    result = skill.verify(active, state, 11.)
    assert result.status is SkillStatus.FAILURE and result.reason is FailureReason.CAST_INTERRUPTED
    flow = ObjectInteractionFlow()
    flow.note_result({"action_id": "interrupted", "skill": "OBJECT_USE", "outcome": "FAILURE",
                      "object_guid": TABLE, "reason": "cast_interrupted"}, state)
    (use,) = ServerNpcInteractionPolicy(flow).propose(state)
    assert use.skill == "OBJECT_USE"
    # A previous unrelated cast's old error must not fail a new use.
    active = active_use(state, proposal.parameters)
    skill.begin(active, state)
    active.skill_context["object_use"]["used_at"] = 12.
    result = skill.verify(active, state, 12.1)
    assert result.status is SkillStatus.RUNNING
