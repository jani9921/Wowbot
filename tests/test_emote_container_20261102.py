"""REV4 P8.4 EMOTE and COLLECT_CONTAINER (user 2026-11-02).

* Container: the quest-item path's bag right-click (26391 Extinguishing Hope,
  live) opens the TDB item_loot_template container of an open objective's
  item; the loot window or the credit verifies it.  No addon button.
* Emote: addon 0.9.83 puts the emote an open objective names on one secure
  button the user binds; the agent re-checks the word, walks up, selects the
  NPC with Ctrl+Tab (GUID verified) and presses it; quest credit verifies."""
from pathlib import Path
from types import SimpleNamespace

import pytest

from wowbot.agent.container_planning import ContainerOpenPolicy
from wowbot.agent.emote_planning import EmotePolicy, emote_task
from wowbot.agent.quest_item_knowledge import authorized_item
from wowbot.runtime import SkillStatus
from wowbot.skills.quest_tool import ExtraActionHandler, addon_action_ready
from test_m0_combat_loot_skills import active

ROOT = Path(__file__).resolve().parents[1]
TOMMY = "Creature-0-1463-0-79-42308-0000616901"
BINDING = "CLICK AIPCEMOTEBUTTON:LEFTBUTTON"


def bags(open_=True, has_loot=True):
    return {"monotonic_time": 10., "bags_open": open_, "is_in_combat": False,
            "collection_coverage": {"inventory": "COMPLETE"},
            "inventory": {"items": [{"bag": 0, "slot": 3, "item_id": 5500, "has_loot": has_loot,
                                     "x": .8, "y": .3, "coordinate_space": "CLIENT_BOTTOM_LEFT"}]},
            "active_quests": [{"quest_id": 700, "is_complete": False, "objectives": [
                {"objective_id": "700:0", "description": "0/1 Goldtooth's Gem", "is_complete": False}]}],
            "reference_knowledge": {"quests": {"700": {"objectives": [
                {"objective_id": 9, "order": 0, "raw_type": 1, "credit_object_id": 1307,
                 "description": "Goldtooth's Gem", "container_items": [5500]}]}}}}


def test_a_quest_container_is_opened_from_the_bags():
    (opening,) = ContainerOpenPolicy().propose(bags(open_=False))
    assert opening.skill == "OPEN_BAGS"
    (use,) = ContainerOpenPolicy().propose(bags())
    assert use.skill == "USE_ON_TARGET" and use.parameters["purpose"] == "OPEN_QUEST_CONTAINER"
    assert (use.parameters["bag"], use.parameters["slot"], use.parameters["activation_source"]) == (0, 3, "INVENTORY_COORDINATE")
    assert authorized_item(bags(), 5500, ["700"]) and not authorized_item(bags(), 5501, ["700"])
    assert ContainerOpenPolicy().propose(bags(has_loot=False)) == []


def test_the_open_container_succeeds_on_its_loot_window():
    from wowbot.skills.quest_item import QuestItemSkill
    (use,) = ContainerOpenPolicy().propose(bags())
    before = bags()
    state = active("USE_ON_TARGET", use.parameters, before)
    skill = QuestItemSkill()
    begun = skill.begin(state, before)
    assert begun.status is SkillStatus.RUNNING and begun.commands[0].button == "RIGHT"
    looting = {**bags(), "loot_ui": {"open": True}}
    assert skill.verify(state, looting, 2.).status is SkillStatus.SUCCESS


def emote_state(*, applied=True, word="dance", target=None, x=3.):
    return {"monotonic_time": 10., "is_in_combat": False, "map_id": 37,
            "player_world_position": {"x": 0., "y": 0., "z": 50., "instance_id": 0},
            "emote_action": {"binding": BINDING, "applied": applied, "kind": "EMOTE", "emote": "DANCE", "command": "/dance",
                             "word": word, "quest_id": 106, "objective_index": 0},
            "active_quests": [{"quest_id": 106, "is_complete": False, "objectives": [
                {"objective_id": "106:0", "description": "0/1 Dance with Tommy Joe", "is_complete": False}]}],
            "reference_knowledge": {"quests": {"106": {"objectives": [
                {"objective_id": 1, "order": 0, "raw_type": 0, "credit_object_id": 42308,
                 "description": "Dance with Tommy Joe"}]}}},
            "target": {"guid": target, "dead": False} if target else {},
            "packet_entities": {TOMMY: {"guid": TOMMY, "kind": "CREATURE", "entry_id": 42308, "map_id": 0,
                                        "position": {"x": x, "y": 0., "z": 50.}, "unit": {"health": 10}}}}


def test_the_emote_ladder_walks_up_selects_and_presses_the_bound_button():
    assert EmotePolicy().propose(emote_state(x=40.))[0].skill == "MOVE"
    tab = EmotePolicy().propose(emote_state())[0]
    assert tab.skill == "TARGET" and tab.parameters["activation_source"] == "TAB_FRIEND_RESCUE"
    (press,) = EmotePolicy().propose(emote_state(target=TOMMY))
    assert press.skill == "ADDON_ACTION" and press.parameters["binding"] == BINDING
    assert press.parameters["emote"] == "DANCE" and press.parameters["guid"] == TOMMY
    cache = SimpleNamespace(contains=lambda action: action == BINDING)
    state = emote_state(target=TOMMY)
    assert addon_action_ready(press.parameters, state, cache)
    skill = ExtraActionHandler(cache)
    begun = skill.begin(active("ADDON_ACTION", press.parameters, state), state)
    assert begun.status is SkillStatus.RUNNING and begun.commands[0].binding == BINDING


def test_no_emote_without_the_applied_button_a_matching_word_or_a_bound_key():
    assert emote_task(emote_state(applied=False)) is None
    assert emote_task(emote_state(word="cheer")) is None                # not this objective's word
    press = EmotePolicy().propose(emote_state(target=TOMMY))[0]
    unbound = SimpleNamespace(contains=lambda action: False)
    assert not addon_action_ready(press.parameters, emote_state(target=TOMMY), unbound)


def test_a_click_binding_line_is_read_from_the_selected_cache(tmp_path):
    from wowbot.agent.bindings import BindingsCache
    path = tmp_path / "bindings-cache.wtf"
    path.write_text('bind W MOVEFORWARD\nbind F10 CLICK AIPCEmoteButton:LeftButton\n', encoding="utf-8")
    cache = BindingsCache(path)
    assert cache.resolve(BINDING) == "F10" and cache.resolve("MOVEFORWARD") == "W"


@pytest.mark.parametrize("text,emote", [("0/1 Dance with Tommy Joe", "/dance"), ("Salute given", "/salute"),
                                        ("Soldiers cheered", "/cheer"), ("Use /bow at the shrine", "/bow"),
                                        ("Hugged the bear", "/hug"), ("Kill 6 kobolds", None)])
def test_addon_reads_the_objectives_own_emote_word(text, emote):
    lupa = pytest.importorskip("lupa")
    source = (ROOT / "addon" / "AIPlayerControllerExport-12.1.0" / "AIPlayerControllerExport.lua").read_text(encoding="utf-8")
    start = source.index("local EMOTE_FALLBACK = ")
    end = source.index("local emoteButton, emoteChoice, emotePending")
    harness = '''
local function accessible(v) return true end
EMOTE1_TOKEN = "DANCE"; EMOTE1_CMD1 = "/dance"
''' + source[start:end] + '''
local found = emoteForText(...)
return found and found.command or "none"
'''
    result = lupa.LuaRuntime().execute(harness, text)
    assert result == (emote or "none")
