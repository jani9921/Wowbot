"""Live 2026-10-04 10:44: Re-sizing the Situation -- "0/3 Re-Sizer v9.0.1
tested on Wandering Boars" (USE_ITEM, quest special item) -- made the selected
boar combat-relevant and COMBAT charged it before the item was used."""
from wowbot.agent.models import Goal, Observation
from wowbot.agent.planner import Planner
from wowbot.agent.skills import SkillRegistry
from wowbot.agent.world import WorldModel

QUEST = {"quest_id": 56034, "title": "Re-sizing the Situation", "is_complete": False, "is_campaign": True,
         "objectives": [{"description": "0/3 Re-Sizer v9.0.1 tested on Wandering Boars", "type": "USE_ITEM",
                         "raw_type": "monster", "current": 0, "required": 3, "is_complete": False,
                         "item_id": 170557}],
         "special_item": {"item_id": 170557, "item_name": "Re-Sizer v9.0.1", "source": "QUEST_LOG_SPECIAL_ITEM"}}
BOAR = {"guid": "Creature-0-3113-2175-63341-160542-0000411A00", "name": "Wandering Boar", "npc_id": 160542,
        "attackable": True, "dead": False, "reaction": "neutral",
        "screen_position": {"x": .5, "y": .55, "source": "NAMEPLATE_API", "coordinate_space": "CLIENT_BOTTOM_LEFT",
                            "sample_time": 1.}}


def _world(**extra):
    world = WorldModel()
    world.ingest(Observation.create({
        "session_id": "i", "timestamp": 1., "frame_id": "f", "monotonic_time": 1., "map_id": 1409,
        "orientation": 0., "position": {"x": .6, "y": .6}, "player_present": True,
        "player_world_position": {"x": 120., "y": -2400., "instance_id": 2175, "coordinate_space": "WORLD_YARDS"},
        "active_quests": [QUEST], "target": BOAR, "world_map_open": False,
        "actionbar": [{"action": "ACTIONBUTTON1", "id": 100, "name": "Charge", "is_harmful": True,
                       "is_usable": True, "in_range": True, "min_range": 8, "max_range": 25, "kind": "spell"}],
        **extra}, 1.))
    return world


def _combat(world):
    planner = Planner(SkillRegistry())
    result = planner.combat_policy.propose(world.planning_snapshot(1.), Goal.parse("Questelj", 1.), 1.,
                                           planner.quest)
    return [proposal.skill for proposal in result.proposals]


def test_item_use_target_is_not_attacked_out_of_combat():
    assert not {"COMBAT", "DEFEND", "VISUAL_APPROACH"} & set(_combat(_world()))


def test_an_attacking_boar_is_still_fought():
    assert {"COMBAT", "DEFEND"} & set(_combat(_world(is_in_combat=True)))


INVENTORY = {"items": [{"bag": 0, "slot": 10, "item_id": 170557, "is_locked": False}], "free_slots": 5}


def _quest_proposals(world):
    planner = Planner(SkillRegistry())
    return planner, planner.quest.propose(world.planning_snapshot(1.), Goal.parse("Questelj", 1.))


def test_selected_boar_gets_the_item_through_the_interact_key():
    # Live 10:50: no action-bar item and no bag coordinate -> no USE_ON_TARGET at
    # all.  The Re-Sizer credit came from INTERACTTARGET on the boar.
    _, proposals = _quest_proposals(_world(inventory=INVENTORY))
    use = [p for p in proposals if p.skill == "USE_ON_TARGET"]
    assert use and use[0].parameters["activation_source"] == "INTERACT_KEY"
    assert use[0].parameters["binding"] == "INTERACTTARGET"
    planner = Planner(SkillRegistry())
    assert planner.registry.available(use[0], _world(inventory=INVENTORY))


def test_too_far_item_target_is_approached_first():
    world = _world(inventory=INVENTORY, ui_error="You need to be closer to interact with that target.")
    _, proposals = _quest_proposals(world)
    assert not any(p.skill == "USE_ON_TARGET" for p in proposals)
    approach = next(p for p in proposals if p.skill == "VISUAL_APPROACH")
    assert approach.parameters["guid"] == BOAR["guid"] and approach.priority > 80


def test_too_far_item_target_without_anchor_uses_the_minimap_position():
    far_boar = {**BOAR, "screen_position": None,
                "world_position": {"x": 150., "y": -2380., "coordinate_space": "WORLD_YARDS",
                                   "instance_id": 2175, "source": "MINIMAP_TARGET_MARKER"}}
    world = _world(inventory=INVENTORY, target=far_boar,
                   ui_error="You need to be closer to interact with that target.")
    _, proposals = _quest_proposals(world)
    move = next(p for p in proposals if p.skill == "MOVE"
                and p.parameters.get("purpose") == "APPROACH_ITEM_TARGET")
    assert (move.parameters["x"], move.parameters["y"]) == (150., -2380.)


def test_use_item_skill_presses_interact_for_interact_key_activation():
    from types import SimpleNamespace
    from wowbot.skills.quest_item import UseItemSkill
    skill = UseItemSkill(bindings=None)
    state = SimpleNamespace(
        intent=SimpleNamespace(parameters={"guid": BOAR["guid"], "item_id": 170557, "quest_ids": [56034],
                                           "objective_ids": ["56034:0"], "binding": "INTERACTTARGET",
                                           "activation_source": "INTERACT_KEY"},
                               target_ref=BOAR["guid"], objective_ref="56034:0"),
        skill_type="USE_ON_TARGET", skill_context={}, phase=None)
    result = skill.begin(state, {"target": BOAR, "actionbar": [], "active_quests": [QUEST]})
    assert [c.binding for c in result.commands] == ["INTERACTTARGET"]


def test_ui_errors_are_classified():
    from wowbot.verification.interaction import classify_ui_error
    assert classify_ui_error("You need to be closer to interact with that target.", 852) == "RANGE"
    assert classify_ui_error("Out of range.") == "RANGE"
    assert classify_ui_error("You are facing the wrong way!") == "FACING"
    assert classify_ui_error("Target needs to be in front of you.") == "FACING"
    assert classify_ui_error("Target not in line of sight") == "LINE_OF_SIGHT"
    assert classify_ui_error("Not enough rage") is None


import pytest  # noqa: E402


@pytest.mark.parametrize("message,reason", [
    ("Target not in line of sight", "LINE_OF_SIGHT"),
    ("You are facing the wrong way!", "FACING_FAILED"),
    ("Out of range.", "OUT_OF_RANGE")])
def test_item_use_ends_on_position_errors(message, reason):
    from types import SimpleNamespace
    from wowbot.skills.quest_item import UseItemSkill
    state = SimpleNamespace(
        skill_context={"quest_item": {"guid": BOAR["guid"], "quest_ids": [56034], "objective_ids": ["56034:0"]}},
        before_snapshot={"events": [{"event_type": "UI_ERROR_MESSAGE", "sequence": 10, "payload": {}}],
                         "active_quests": [QUEST]},
        attempt=SimpleNamespace(deadline=99.), phase=None)
    after = {"target": BOAR, "active_quests": [QUEST],
             "events": [{"event_type": "UI_ERROR_MESSAGE", "sequence": 11, "payload": {"message": message}}]}
    result = UseItemSkill().verify(state, after, 1.)
    assert result.reason.value == reason


@pytest.mark.parametrize("message", ["Target not in line of sight", "You are facing the wrong way!"])
def test_los_or_facing_item_target_is_approached(message):
    _, proposals = _quest_proposals(_world(inventory=INVENTORY, ui_error=message))
    assert not any(p.skill == "USE_ON_TARGET" for p in proposals)
    assert any(p.skill == "VISUAL_APPROACH" and p.parameters["guid"] == BOAR["guid"] for p in proposals)
