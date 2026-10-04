import pytest

from wowbot.agent.models import Goal, Observation, Proposal
from wowbot.agent.planner import Planner
from wowbot.agent.quest_model import objective_type
from wowbot.agent.quest_semantics import subject_matches_name
from wowbot.agent.skills import SkillRegistry
from wowbot.agent.world import WorldModel


def world(**extra):
    value = WorldModel()
    value.ingest(Observation.create({
        "session_id": "exile", "frame_id": "f1", "timestamp": 1,
        "monotonic_time": 1, "state_age": 0, "map_id": 1409,
        "position": {"x": .5, "y": .5}, "orientation": 0,
        "player_present": True, "world_map_open": False,
        **extra,
    }, 1))
    return value


def quest(objective):
    return [{"quest_id": 101, "title": "Generic Exile mechanic", "objectives": [objective]}]


def test_vendor_objective_types_are_separate_from_collect():
    assert objective_type({"description": "Purchase any item from the quartermaster"})[0] == "BUY"
    assert objective_type({"description": "Sell any of your items to her"})[0] == "SELL"


def test_named_target_matching_handles_regular_plural_only():
    assert subject_matches_name(["wandering boars"], "Wandering Boar")
    assert not subject_matches_name(["bo"], "Boar")


def test_neutral_quest_item_target_produces_use_on_target():
    actionbar = [{"kind": "item", "id": 9001, "action": "ACTIONBUTTON5",
                  "is_usable": True, "cooldown_remaining": 0}]
    state = world(
        active_quests=quest({"description": "Use the Re-Sizer on Wandering Boars",
                             "type": "USE_ITEM", "item_id": 9001, "current": 0, "required": 3}),
        target={"guid": "boar-1", "name": "Wandering Boar", "attackable": True, "dead": False},
        actionbar=actionbar,
    )
    proposals = Planner(SkillRegistry()).candidates(Goal.parse("Questelj", 1), state, 1)
    assert any(p.skill == "USE_ON_TARGET" and p.parameters["item_id"] == 9001 for p in proposals)


def test_exact_special_item_objective_uses_verified_bag_slot_without_actionbar():
    objective = {"description": "Re-Sizer v9.0.1 tested on Wandering Boars",
                 "type": "USE_ITEM", "raw_type": "monster", "item_id": 170557,
                 "current": 1, "required": 3}
    active_quests = [{"quest_id": 56034, "title": "Re-sizing the Situation",
                      "special_item": {"item_id": 170557}, "objectives": [objective]}]
    inventory = {"items": [{"bag": 0, "slot": 9, "item_id": 170557,
                             "is_quest_item": True, "is_locked": False,
                             "x": .81, "y": .22,
                             "coordinate_space": "CLIENT_BOTTOM_LEFT"}]}
    state = world(active_quests=active_quests, bags_open=True, inventory=inventory,
                  actionbar=[], target={"guid": "boar-1", "name": "Wandering Boar",
                                        "attackable": True, "dead": False})
    proposals = Planner(SkillRegistry()).candidates(Goal.parse("Questelj", 1), state, 1)
    use = next(p for p in proposals if p.skill == "USE_ON_TARGET")
    assert use.parameters["activation_source"] == "INVENTORY_COORDINATE"
    assert (use.parameters["bag"], use.parameters["slot"], use.parameters["x"], use.parameters["y"]) == (0, 9, .81, .22)
    assert SkillRegistry().available(use, state)


def test_exact_special_item_objective_opens_bags_instead_of_attacking():
    objective = {"description": "Re-Sizer v9.0.1 tested on Wandering Boars",
                 "type": "USE_ITEM", "raw_type": "monster", "item_id": 170557,
                 "current": 1, "required": 3}
    active_quests = [{"quest_id": 56034, "special_item": {"item_id": 170557},
                      "objectives": [objective]}]
    state = world(active_quests=active_quests, bags_open=False,
                  inventory={"items": [{"bag": 0, "slot": 9, "item_id": 170557,
                                          "is_quest_item": True, "is_locked": False}]},
                  actionbar=[], target={"guid": "boar-1", "name": "Wandering Boar",
                                        "attackable": True, "dead": False})
    proposals = Planner(SkillRegistry()).candidates(Goal.parse("Questelj", 1), state, 1)
    assert any(p.skill == "OPEN_BAGS" and p.parameters.get("purpose") == "QUEST_ITEM"
               for p in proposals)
    assert not any(p.skill == "COMBAT" for p in proposals)


def test_use_on_target_is_reserved_for_the_canonical_quest_item_skill():
    state = world(target={"guid": "boar-1", "dead": False}, actionbar=[
        {"kind": "item", "id": 9001, "action": "ACTIONBUTTON5", "is_usable": True,
         "cooldown_remaining": 0},
    ])
    proposal = Proposal.make("USE_ON_TARGET", "test", {"guid": "boar-1", "item_id": 9001})
    registry = SkillRegistry()
    assert registry.available(proposal, state)
    with pytest.raises(ValueError, match="canonical quest skill"):
        registry.commands(proposal, state)


def test_buy_vendor_uses_addon_item_coordinate_and_known_money():
    state = world(
        money=30,
        active_quests=quest({"description": "Purchase any item from Quartermaster Richter",
                             "current": 0, "required": 1}),
        vendor_ui={"open": True, "items": [
            {"slot": 1, "item_id": 10, "price": 25, "is_purchasable": True, "x": .6, "y": .4},
            {"slot": 2, "item_id": 11, "price": 50, "is_purchasable": True, "x": .7, "y": .4},
        ]},
    )
    proposals = Planner(SkillRegistry()).candidates(Goal.parse("Questelj", 1), state, 1)
    buy = next(p for p in proposals if p.skill == "BUY_VENDOR")
    assert buy.parameters["item_id"] == 10
    command = SkillRegistry().commands(buy, state)[0]
    assert (command.kind, command.button, command.x, command.y) == ("CLICK", "RIGHT", .6, .4)


def test_sell_vendor_rejects_quest_and_equippable_items():
    inventory = {"items": [
        {"bag": 0, "slot": 1, "item_id": 1, "sell_price": 10, "is_quest_item": True,
         "is_equippable": False, "is_locked": False, "x": .2, "y": .2},
        {"bag": 0, "slot": 2, "item_id": 2, "sell_price": 10, "is_quest_item": False,
         "is_equippable": True, "is_locked": False, "x": .3, "y": .2},
        {"bag": 0, "slot": 3, "item_id": 3, "sell_price": 2, "quality": 0,
         "is_quest_item": False, "is_equippable": False, "is_locked": False, "x": .4, "y": .2},
    ]}
    state = world(
        bags_open=True, inventory=inventory,
        active_quests=quest({"description": "Sell any of your items to her", "current": 0, "required": 1}),
        vendor_ui={"open": True, "items": []},
    )
    proposals = Planner(SkillRegistry()).candidates(Goal.parse("Questelj", 1), state, 1)
    sell = next(p for p in proposals if p.skill == "SELL_VENDOR")
    assert sell.parameters["item_id"] == 3
    assert SkillRegistry().available(sell, state)


def test_sell_objective_opens_bags_before_selecting_item():
    state = world(
        bags_open=False, inventory={"items": []},
        active_quests=quest({"description": "Sell any of your items to her", "current": 0, "required": 1}),
        vendor_ui={"open": True, "items": []},
    )
    proposals = Planner(SkillRegistry()).candidates(Goal.parse("Questelj", 1), state, 1)
    assert any(p.skill == "OPEN_BAGS" for p in proposals)


def test_cooking_objective_uses_tooltip_confirmed_campfire():
    state = world(
        cursor_position={"nx": .55, "ny": .48},
        mouseover={"tooltip": "Campfire", "object_id": 777},
        active_quests=quest({"description": "Cook the meat on the campfire",
                             "current": 0, "required": 1}),
    )
    proposals = Planner(SkillRegistry()).candidates(Goal.parse("Questelj", 1), state, 1)
    use = next(p for p in proposals if p.skill == "OBJECT_USE")
    assert use.parameters["x"] == .55 and use.parameters["y"] == .48


def test_training_instruction_uses_only_explicitly_named_action():
    state = world(
        active_quests=quest({"description": "Spar with Captain Garrick; abilities proven",
                             "type": "KILL", "target_name": "Captain Garrick",
                             "current": 0, "required": 3}),
        target={"guid": "trainer", "name": "Captain Garrick", "attackable": True, "dead": False},
        actionbar=[
            {"kind": "spell", "id": 100, "name": "Slam", "action": "ACTIONBUTTON1",
             "is_harmful": True, "is_usable": True, "cooldown_remaining": 0, "in_range": True},
            {"kind": "spell", "id": 200, "name": "Charge", "action": "ACTIONBUTTON2",
             "is_harmful": True, "is_usable": True, "cooldown_remaining": 0, "in_range": True},
        ],
        events=[{"sequence": 7, "event_type": "NPC_INSTRUCTION",
                 "payload": {"message": "Now use Slam against me!"}}],
    )
    proposals = Planner(SkillRegistry()).candidates(Goal.parse("Questelj", 1), state, 1)
    instructed = next(p for p in proposals if p.skill == "FOLLOW_INSTRUCTION")
    assert instructed.parameters["binding"] == "ACTIONBUTTON1"


def test_training_instruction_does_not_guess_when_no_action_is_named():
    state = world(
        active_quests=quest({"description": "Spar with Captain Garrick; abilities proven",
                             "type": "KILL", "target_name": "Captain Garrick",
                             "current": 0, "required": 3}),
        target={"guid": "trainer", "name": "Captain Garrick", "attackable": True, "dead": False},
        actionbar=[{"kind": "spell", "id": 100, "name": "Slam", "action": "ACTIONBUTTON1",
                    "is_harmful": True, "is_usable": True, "cooldown_remaining": 0, "in_range": True}],
        events=[{"sequence": 8, "event_type": "NPC_INSTRUCTION",
                 "payload": {"message": "Show me what you have learned!"}}],
    )
    proposals = Planner(SkillRegistry()).candidates(Goal.parse("Questelj", 1), state, 1)
    assert not any(p.skill == "FOLLOW_INSTRUCTION" for p in proposals)
    assert any(p.skill == "COMBAT" for p in proposals)
