"""Buy a quest item behind a vendor gossip row (live 2026-10-21, Cataloger Jakes).

15:52:59-15:53:21 "Buy Archeologist Artifact Notes from Cataloger Jakes": his
window listed the quest and two options ("Can I see the Renown items you have
for sale?", the Dragonscale Expedition standing).  The addon exported only a
lone option, so the agent saw an empty window, closed it and reopened it.  In
the shop (one page, user screenshot) the notes are the bottom-right item,
priced in a currency.
"""
from wowbot.agent.models import Proposal
from wowbot.agent.quest_objective_planning import (quest_vendor_item, vendor_dialog_suppressed,
                                                   vendor_gossip_option)
from wowbot.runtime import SkillStatus
from wowbot.skills.quest_dialog import QuestDialogSkill
from wowbot.verification.quest_dialog import QuestDialogVerifier

from test_m0_combat_loot_skills import active

JAKES = "Creature-0-3769-2444-47-187700-00005824C4"
OPTIONS = [
    {"id": 107111, "name": "Can I see the Renown items you have for sale?", "icon": 132060,
     "available": True, "x": .12, "y": .62},
    {"id": 107112, "name": "I wish to know where I stand with the Dragonscale Expedition?",
     "icon": 132053, "available": True, "x": .12, "y": .66},
]
ITEMS = [
    {"slot": 1, "name": "Small Expedition Shovel", "price": 0, "extended_cost": True, "is_purchasable": True,
     "x": .05, "y": .2},
    {"slot": 2, "name": "Expedition Explosives", "price": 0, "extended_cost": True, "is_purchasable": True,
     "x": .1, "y": .2},
    {"slot": 4, "name": "Reliquary Banner", "price": 0, "extended_cost": True, "is_purchasable": False,
     "x": .1, "y": .25},
    {"slot": 5, "name": "Explorers' League Banner", "price": 200000, "extended_cost": True,
     "is_purchasable": True, "x": .05, "y": .3},
    {"slot": 6, "name": "Archeologist Artifact Notes", "price": 0, "extended_cost": True,
     "is_purchasable": True, "x": .1, "y": .3, "item_id": 198854},
]
OBJECTIVE = "0/1 Buy Archeologist Artifact Notes from Cataloger Jakes"


def test_the_shop_row_is_the_vendor_option_not_the_standing_one():
    assert vendor_gossip_option(OPTIONS)["id"] == 107111
    no_icon = [{**row, "icon": None} for row in OPTIONS]
    assert vendor_gossip_option(no_icon)["id"] == 107111                     # by its wording
    assert vendor_gossip_option(OPTIONS[1:]) is None
    assert vendor_gossip_option([{**OPTIONS[0], "x": None}]) is None         # no visible row


def test_the_named_item_is_bought_even_when_priced_in_a_currency():
    item = quest_vendor_item(ITEMS, OBJECTIVE, 433829)
    assert item["name"] == "Archeologist Artifact Notes"
    # Named but not buyable now: nothing else is bought instead.
    blocked = [{**row, "is_purchasable": row["slot"] != 6} for row in ITEMS]
    assert quest_vendor_item(blocked, OBJECTIVE, 433829) is None
    # An objective naming no shop item keeps the cheapest affordable gold item.
    generic = [{"slot": 1, "name": "Bread", "price": 25, "is_purchasable": True, "x": .1, "y": .2},
               {"slot": 2, "name": "Water", "price": 5, "is_purchasable": True, "x": .1, "y": .25}]
    assert quest_vendor_item(generic, "0/1 Buy supplies", 100)["name"] == "Water"


def ui_state(**extra):
    return {"target": {"guid": JAKES, "name": "Cataloger Jakes", "attackable": False, "dead": False},
            "quest_ui": {"open": True, "action": "", "x": 0, "y": 0, "quest_id": 0, "npc_guid": JAKES,
                         "gossip_options": OPTIONS},
            "quest_ui_open": True, "state_age": .5, "active_quests": [{"quest_id": 72709}],
            "vendor_ui": {"open": False}, **extra}


def test_the_vendor_row_is_clicked_and_counts_once_the_shop_opens():
    params = {"action": "GOSSIP_VENDOR", "x": .12, "y": .62, "gossip_option_id": 107111,
              "gossip_option_name": OPTIONS[0]["name"], "target_guid": JAKES, "quest_id": 72709}
    state = active("QUEST_DIALOG", params, ui_state())
    started = QuestDialogSkill().begin(state, ui_state())
    assert started.status is SkillStatus.RUNNING
    assert [(c.kind, c.x, c.y) for c in started.commands] == [("CLICK", .12, .62)]
    moved = {**params, "y": .7}
    wrong = QuestDialogSkill().begin(active("QUEST_DIALOG", moved, ui_state()), ui_state())
    assert wrong.status is SkillStatus.FAILURE
    verifier = QuestDialogVerifier()
    shop = ui_state(vendor_ui={"open": True, "items": ITEMS})
    assert verifier.evaluate(ui_state(), shop, quest_id=72709, action="GOSSIP_VENDOR",
                             gossip_option_id=107111).success
    assert not verifier.evaluate(ui_state(), ui_state(), quest_id=72709, action="GOSSIP_VENDOR",
                                 gossip_option_id=107111).success


def test_a_window_closed_empty_twice_is_not_reopened_for_two_minutes():
    closes = {JAKES: [100., 104.]}
    assert vendor_dialog_suppressed(closes, JAKES, 110.)
    assert not vendor_dialog_suppressed(closes, JAKES, 230.)
    assert not vendor_dialog_suppressed({JAKES: [100.]}, JAKES, 110.)
