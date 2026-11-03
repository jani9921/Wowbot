"""User's 09:58, 10:02 and 10:05 runs: item range != Charge range.

Only synthetic evidence/command descriptions; never sends client input.
"""
from types import SimpleNamespace

import pytest

from test_item_use_no_combat_20261004 import BOAR, INVENTORY, QUEST, _quest_proposals, _world
from wowbot.agent.visual_approach import VisualApproachController
from wowbot.agent.models import Goal, Proposal
from wowbot.agent.planner import Planner
from wowbot.agent.quest_tool_resolver import QuestToolResolver
from wowbot.agent.skills import SkillRegistry
from wowbot.runtime import SkillStatus
from wowbot.skills.quest_item import UseItemSkill


def item_evidence(*, now=1., in_range=True, usable=True, cooldown=0., guid=None):
    return {"guid": guid or BOAR["guid"], "sample_time": now,
            "items": [{"quest_id": 56034, "item_id": 170557,
                       "in_range": in_range, "is_usable": usable,
                       "cooldown_remaining": cooldown}]}


def item_active():
    params = {"guid": BOAR["guid"], "item_id": 170557, "quest_ids": [56034],
              "objective_ids": ["56034:0"], "activation_source": "INTERACT_KEY",
              "binding": "INTERACTTARGET"}
    return SimpleNamespace(intent=SimpleNamespace(parameters=params, target_ref=BOAR["guid"],
                                                  objective_ref="56034:0"),
                           skill_type="USE_ON_TARGET", skill_context={}, phase=None,
                           started_at=1., before_snapshot={"active_quests": [QUEST]})


@pytest.mark.parametrize("proof", [None, item_evidence(in_range=False),
                                  item_evidence(usable=False), item_evidence(cooldown=8.),
                                  item_evidence(now=-2.), item_evidence(guid="other")])
def test_f7_needs_positive_fresh_exact_item_readiness_even_with_selected_target(proof):
    world = {"target": BOAR, "active_quests": [QUEST], "actionbar": [],
             "quest_item_target": proof, "monotonic_time": 1.}
    result = UseItemSkill().begin(item_active(), world)
    assert not result.commands
    assert result.status in {SkillStatus.BLOCKED, SkillStatus.FAILURE}


def test_near_usable_item_keeps_f7_when_the_recipient_is_confirmed():
    world = {"target": BOAR, "active_quests": [QUEST], "actionbar": [],
             "quest_item_target": item_evidence(), "monotonic_time": 1.,
             "soft_targets": [{"source_unit": "softinteract", "guid": BOAR["guid"]}],
             "soft_targets_sample_time": 1.}
    result = UseItemSkill().begin(item_active(), world)
    assert result.status is SkillStatus.RUNNING
    assert [command.binding for command in result.commands] == ["INTERACTTARGET"]


def test_attack_range_does_not_complete_item_approach_without_walking():
    state = _world(inventory=INVENTORY).state
    state["quest_item_target"] = item_evidence(in_range=False)
    state["visual_candidates"] = [{"track_id": "boar", "source": "WORLD3D", "x": .5, "y": .5,
                                   "confidence": .9, "bbox_height_fraction": .08,
                                   "observed_at": 1., "lifecycle": "ACTIVE"}]
    controller = VisualApproachController()
    result = controller.start({"guid": BOAR["guid"], "track_id": "boar", "purpose": "INTERACT",
                               "item_use_approach": True, "item_id": 170557, "quest_ids": [56034]},
                              state, "o1", 1.)
    assert not (result.terminal and result.success), result.reason
    assert not any(command.binding == "INTERACTTARGET"
                   for command in controller.command(state, "o1", 1.))


def test_selected_item_subject_stays_local_instead_of_emitting_quest_region_moves():
    planner, proposals = _quest_proposals(_world(inventory=INVENTORY,
                                               quest_item_target=item_evidence(in_range=False)))
    assert any(p.skill == "VISUAL_APPROACH" and p.parameters.get("item_use_approach")
               for p in proposals)
    assert not any(p.skill == "MOVE" and p.parameters.get("purpose") in {
        "LOCATE_QUEST_OBJECTIVE_REGION", "SEARCH_LOCAL_OBJECTIVE_AREA"} for p in proposals)
    assert not any(p.skill == "USE_ON_TARGET" for p in proposals)


def test_item_subject_hover_uses_the_existing_fast_ground_truth_target_handoff():
    world = _world(target=None, inventory=INVENTORY, mouseover=BOAR,
                   mouseover_sample_time=1., cursor_sample_time=1.,
                   cursor_position={"nx": .52, "ny": .6})
    _, proposals = _quest_proposals(world)
    target = next(p for p in proposals if p.skill == "TARGET" and p.parameters.get("objective_id"))
    assert target.parameters.get("ground_truth_handoff") is True
    assert target.parameters.get("click_current_cursor") is True


def test_unknown_f7_recipient_uses_explicit_item_ui_instead_of_retrying_blind_interact():
    bag = {"items": [{**INVENTORY["items"][0], "x": .98, "y": .24,
                      "coordinate_space": "CLIENT_BOTTOM_LEFT"}]}
    world = _world(inventory=bag, bags_open=True, quest_item_target=item_evidence(),
                   soft_targets=[], soft_targets_sample_time=None, protocol_version="AIPC5")
    _, proposals = _quest_proposals(world)
    use = next(p for p in proposals if p.skill == "USE_ON_TARGET")
    assert use.parameters["activation_source"] == "INVENTORY_COORDINATE"


def test_background_search_cannot_take_the_pointer_or_walk_away_from_item_subject():
    world = _world(inventory=INVENTORY, bags_open=False)
    planner = Planner(SkillRegistry())
    objective = world.quest_model.ready()[0]
    open_bag = Proposal.make("OPEN_BAGS", "exact item", {
        "guid": BOAR["guid"], "item_id": 170557, "purpose": "QUEST_ITEM"})
    distracting = [Proposal.make("SEEK_VISUAL_CUE", "unknown", {"track_id": "elsewhere"}, priority=120),
                   Proposal.make("MOVE", "zone", {"purpose": "SEARCH_LOCAL_OBJECTIVE_AREA"}, priority=120)]
    assert planner._item_subject_owns_input(distracting + [open_bag], world, objective) == [open_bag]
    candidates = planner.candidates(Goal.parse("Questelj", 1.), world.planning_snapshot(1.), 1.)
    assert any(p.skill == "OPEN_BAGS" for p in candidates)
    assert not any(p.skill in {"SEEK_VISUAL_CUE", "INSPECT", "MOVE"} for p in candidates)


def test_item_ownership_keeps_defence_and_releases_dead_or_stale_selection():
    world = _world(inventory=INVENTORY, is_in_combat=True)
    objective = world.quest_model.ready()[0]
    defend = Proposal.make("DEFEND", "survival", {"guid": BOAR["guid"]})
    assert Planner._item_subject_owns_input([defend], world, objective) == [defend]
    assert QuestToolResolver.selected_objective(world.state, [objective], now=1.) is objective
    stale = {**world.state, "target_sample_time": -2.}
    assert QuestToolResolver.selected_objective(stale, [objective], now=1.) is None
    dead = {**world.state, "target": {**BOAR, "dead": True}}
    assert QuestToolResolver.selected_objective(dead, [objective], now=1.) is None


def test_untrusted_unit_position_cannot_drive_item_approach_to_wrong_coordinates():
    target = {**BOAR, "screen_position": None,
              "world_position": {"x": 9999., "y": -9999., "coordinate_space": "WORLD_YARDS",
                                 "instance_id": 2175, "source": "UNIT_POSITION"}}
    _, proposals = _quest_proposals(_world(inventory=INVENTORY, target=target,
                                           quest_item_target=item_evidence(in_range=False)))
    assert not any(p.skill == "MOVE" for p in proposals)
    assert any(p.skill == "WAIT" and p.parameters.get("purpose") == "QUEST_ITEM_READY" for p in proposals)
