"""Live 2026-10-31 10:31 (26209 "Murder Was The Case"): a gossip row's money confirmation.

"Maybe a couple copper will loosen your tongue..." made the server ask "Are
you sure you want to give this hobo money? 2 copper"; the addon did not export
the popup, so the agent waited and the user pressed Accept.  Addon 0.9.81
exports only the GOSSIP_CONFIRM Accept point and the sum; the agent accepts a
small known sum in an NPC's open gossip window, and nothing else."""
from pathlib import Path

import pytest

from wowbot.agent.quest_dialog_planning import QuestDialogPlanningPolicy as Policy
from wowbot.runtime import SkillStatus
from wowbot.skills.quest_dialog import QuestDialogSkill
from test_m0_combat_loot_skills import active
from test_objective_probes_20261031 import DRIFTER, dialog

ROOT = Path(__file__).resolve().parents[1]


def popup(money=2, **extra):
    state = dialog()
    state["quest_ui"]["gossip_confirm"] = {"open": True, "x": .5, "y": .17, "money": money, "enabled": True, **extra}
    return state


def test_a_small_known_sum_is_accepted_and_the_popup_is_modal():
    (accept,) = Policy().propose(popup(), None)
    assert accept.skill == "QUEST_DIALOG" and accept.parameters["action"] == "GOSSIP_CONFIRM"
    assert accept.parameters["money"] == 2 and accept.parameters["target_guid"] == DRIFTER


@pytest.mark.parametrize("change", [{"money": 250}, {"money": None}, {"money": 0}, {"enabled": False},
                                    {"open": False}, {"x": 1.4}])
def test_an_unknown_large_or_unusable_confirmation_is_never_pressed(change):
    assert not any(p.parameters.get("action") == "GOSSIP_CONFIRM" for p in Policy().propose(popup(**change), None))


def test_the_skill_clicks_the_exact_accept_and_succeeds_when_the_popup_closes():
    state = popup()
    (accept,) = Policy().propose(state, None)
    skill = QuestDialogSkill()
    context = active("QUEST_DIALOG", accept.parameters, state)
    begun = skill.begin(context, state)
    assert begun.status is SkillStatus.RUNNING and begun.commands[0].kind == "CLICK"
    assert (begun.commands[0].x, begun.commands[0].y) == (.5, .17)
    assert skill.verify(context, state, 1.).status is SkillStatus.RUNNING
    closed = dialog()
    assert skill.verify(context, closed, 2.).status is SkillStatus.SUCCESS
    moved = popup(x=.7)
    assert skill.begin(active("QUEST_DIALOG", accept.parameters, moved), moved).status is SkillStatus.FAILURE


def test_addon_exports_only_the_gossip_confirm_accept_point_and_sum():
    lupa = pytest.importorskip("lupa")
    source = (ROOT / "addon" / "AIPlayerControllerExport-12.1.0" / "AIPlayerControllerExport.lua").read_text(encoding="utf-8")
    start = source.index("local function moneyOf(frame)")
    end = source.index("local function readExtraAction()")
    harness = '''
local function accessible(v) return true end
local function bool(v) return v and true or false end
local function safeCall(fn, ...) if type(fn) ~= "function" then return nil end return fn(...) end
local function frameIsShown(f) return f and f.shown end
local function framePoint(b) if not b then return nil, nil end return b.x, b.y end
StaticPopup1 = {shown = true, which = "DEATH"}
StaticPopup2 = {shown = true, which = "GOSSIP_CONFIRM", moneyFrame = {staticMoney = 2}}
StaticPopup2Button1 = {x = .5, y = .17, IsEnabled = function() return true end}
''' + source[start:end] + '''
local c = readGossipConfirm()
StaticPopup2.shown = false
local none = readGossipConfirm()
return tostring(c.open) .. "|" .. c.x .. "|" .. c.y .. "|" .. c.money .. "|" .. tostring(c.enabled) .. "|" .. tostring(none)
'''
    assert lupa.LuaRuntime().execute(harness) == "true|0.5|0.17|2|true|nil"
