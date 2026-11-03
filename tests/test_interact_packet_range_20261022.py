"""Soft F7 range failure uses the same skill and canonical server reach."""
from copy import deepcopy

import pytest

from wowbot.agent.models import Attempt, Prediction, Proposal
from wowbot.navigation.service import NavigationService
from wowbot.runtime import ActiveSkillRuntime, FailureReason, Intent, SkillStatus
from wowbot.skills import InteractSkill, InteractionRuntimeRunner

GUID = "Creature-0-3769-2444-47-194231-00015824CA"
OTHER = "Creature-0-3769-2444-47-1-0000000001"


def state(now=100.):
    return {"monotonic_time": now, "soft_targets_sample_time": now, "target_sample_time": now,
        "player_world_position": {"x": 2989.1567, "y": -1039.7213, "z": 36.1876,
            "z_observed": True, "instance_id": 2444, "coordinate_space": "WORLD_YARDS"},
        "target": {"guid": GUID, "npc_id": 194231, "world_position": False},
        "soft_targets": [{"guid": GUID, "source_unit": "softinteract"}],
        "orientation": 0., "events": [],
        "packet_entities": {GUID: {"guid": GUID, "entry_id": 194231, "kind": "CREATURE",
            "map_id": 2444, "info": {"npc_flags": 0x1000000},
            "position": {"x": 2997.6702, "y": -1039.5938, "z": 36.5990,
                         "source": "PACKET_CREATE_MOVEMENT", "age": 23.1}}}}


def active(before, *, soft=True):
    params = ({"activation_source": "SOFT_INTERACT", "soft_guid": GUID} if soft else {"guid": GUID})
    params.update(purpose="RESCUE_SOFT_INTERACT_NPC", quest_id=65990)
    proposal = Proposal.make("INTERACT", "rescue", params)
    attempt = Attempt("a", proposal, before, "o", 100., 120., (),
                      Prediction("p", "a", "credit", 100., 120., "o"))
    return ActiveSkillRuntime().start(intent=Intent("INTERACT", params), attempt=attempt,
                                      now=100., before_snapshot=deepcopy(before))


def range_error(now=100.3):
    after = state(now)
    after.update(ui_error="You need to be closer to interact with that target.",
                 ui_error_sequence=20625, ui_error_code=852)
    return after


@pytest.mark.parametrize("soft", [True, False])
def test_range_error_uses_exact_server_position_without_addon_target_xyz(soft):
    before = state()
    running, skill = active(before, soft=soft), InteractSkill()
    assert skill.begin(running, before).commands[0].binding == "INTERACTTARGET"
    result = skill.verify(running, range_error(), 100.3)
    assert result.status is SkillStatus.RUNNING and not result.commands
    request = result.metadata["approach_request"]
    assert request["kind"] == "WORLD_ENTITY" and request["expected_guid"] == GUID
    assert request["stop_distance"] == 2.
    assert running.phase == "APPROACH" and running.local_retry_count == 1
    if soft:
        assert request["recipient"] == "SOFT_INTERACT"


@pytest.mark.parametrize("change", ["removed", "dead", "lootable", "map", "no_position", "nan",
                                     "stale_recipient", "wrong_recipient"])
def test_missing_or_unsafe_identity_does_not_authorize_a_packet_approach(change):
    before = state()
    running, skill = active(before), InteractSkill()
    skill.begin(running, before)
    after = range_error()
    actor = after["packet_entities"][GUID]
    if change == "removed": actor["removed"] = {"reason": "OUT_OF_RANGE"}
    elif change == "dead": actor["dead"] = True
    elif change == "lootable": actor["dynamic_flags"] = {"value": 4}
    elif change == "map": actor["map_id"] = 2175
    elif change == "no_position": actor.pop("position")
    elif change == "nan": actor["position"]["x"] = float("nan")
    elif change == "stale_recipient": after["soft_targets_sample_time"] = 90.
    else: after["soft_targets"][0]["guid"] = OTHER
    assert "approach_request" not in skill.verify(running, after, 100.3).metadata


def test_soft_approach_routes_through_navigation_and_rechecks_recipient_before_f7():
    before = state()
    running, skill = active(before), InteractSkill()
    skill.begin(running, before)
    after = range_error()
    result = skill.verify(running, after, 100.3)
    nav = NavigationService()
    starts = []
    nav.start_request = lambda request, *args: starts.append(request)
    nav.command = lambda *args: ()
    step = InteractionRuntimeRunner(nav, skill).step_verification(
        running, after, result, world_observation_id="range", visual_observation_id="v", now=100.3)
    request, = starts
    assert request.mode == 'APPROACH_ENTITY' and request.target_entity_id == GUID
    destination = request.destination
    assert step.event_type == "INTERACT_APPROACH_STARTED" and step.movement_lane
    assert destination["server_entity_guid"] == GUID and destination["require_navmesh"] is True
    assert destination["z"] == 36.5990 and not destination.get("target_guid")
    # Turning may hide the soft hint, not the known server actor.
    nav._movement.destination = destination
    turned = {**state(100.5), "soft_targets": [], "target": {"guid": OTHER}}
    assert nav._entity_route_identity_matches(turned, 100.5)
    removed = deepcopy(turned)
    removed["packet_entities"][GUID]["removed"] = {"reason": "DESTROYED"}
    assert not nav._entity_route_identity_matches(removed, 100.5)
    arrived = state(101.)
    arrived["player_world_position"].update(x=2996., y=-1039.6)
    resumed = skill.resume_after_approach(running, arrived, now=101.)
    assert resumed.status is SkillStatus.RUNNING and resumed.commands[0].binding == "INTERACTTARGET"
    wrong = {**arrived, "soft_targets": [{"guid": OTHER, "source_unit": "softinteract"}]}
    assert skill.resume_after_approach(running, wrong, now=101.).reason is FailureReason.IDENTITY_UNCERTAIN


def test_selected_packet_approach_keeps_selected_guid_authority():
    nav = NavigationService()
    nav.start = lambda *args: None
    destination = nav.move_to_entity(state(), GUID, "o", 100., stop_distance=2.)
    assert destination["interaction_identity_source"] == "TARGET"
    nav._movement.destination = destination
    assert nav._entity_route_identity_matches(state(), 100.)
    assert not nav._entity_route_identity_matches({**state(), "target": {"guid": OTHER}}, 100.)


def test_range_correction_remains_bounded_and_does_not_spam_f7():
    before = state()
    running, skill = active(before), InteractSkill()
    skill.begin(running, before)
    for now in (100.3, 100.5):
        result = skill.verify(running, range_error(now), now)
        assert result.status is SkillStatus.RUNNING and not result.commands
    exhausted = skill.verify(running, range_error(100.7), 100.7)
    assert exhausted.status is SkillStatus.FAILURE and exhausted.reason is FailureReason.OUT_OF_RANGE


def test_nested_server_walk_cannot_extend_the_original_interaction_deadline():
    before = state()
    running = active(before)
    nav = NavigationService()
    nav.observe = lambda *args, **kwargs: pytest.fail("expired attempt must not continue steering")
    step = InteractionRuntimeRunner(nav, InteractSkill()).step_world_entity(running,state(120.),"late",120.)
    assert step.stop_movement and step.terminal_result.reason is FailureReason.TIMEOUT
