"""Displayed (Quest) may be missing from C_GossipInfo.GetOptions().name."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from adapters.telemetry_packets import PacketAssembler
from wowbot.agent.models import Goal, Observation
from wowbot.agent.planner import Planner
from wowbot.agent.quest_dialog_planning import QuestDialogPlanningPolicy
from wowbot.agent.skills import SkillRegistry
from wowbot.agent.world import WorldModel
from wowbot.runtime import SkillStatus
from wowbot.skills.quest_dialog import QuestDialogSkill
from test_agent_transport import lua_runtime
from test_m0_combat_loot_skills import active
from test_server_conversation_actor_20261022 import GUID, state

ADDON = Path(__file__).resolve().parents[1] / "addon/AIPlayerControllerExport"
OPTIONS = [
    {"id": 55898, "name": "So this used to be an Embassy for mortals?", "available": True, "x": .081, "y": .64},
    {"id": 55899, "name": "Have you not seen |5human before?", "available": True, "x": .081, "y": .62},
    {"id": 55900, "name": "Tell me about the history of the Djaradin.", "available": True, "x": .081, "y": .60,
     "display_name": "|cFF0000FF(Quest)|r Tell me about the history of the Djaradin."},
]


def dialog():
    live = state()
    live["quest_ui"] = {"open": True, "npc_guid": GUID, "quest_id": 0, "action": "",
                        "gossip_options": deepcopy(OPTIONS)}
    return live


def sensor():
    lua = lua_runtime()
    source = (ADDON / "AIPlayerControllerExport.lua").read_text(encoding="utf-8")
    body = source[source.index("local function normalizedQuestRowText"):
                  source.index("local function rewardChoiceFrame")]
    lua.execute('''
local function accessible(value) return not issecretvalue(value) and canaccessvalue(value) end
local function safeText(value, fallback) return accessible(value) and value or fallback end
local function optionalNumber(value) return accessible(value) and type(value)=="number" and value or nil end
local function safeCall(fn, ...)
    if type(fn) ~= "function" then return nil end
    local ok, value = pcall(fn, ...)
    if ok then return value end
    return nil
end
local function frameIsShown(frame) return frame and frame.shown end
local function framePoint(frame) return frame.x, frame.y end
APIOptions = {
    {gossipOptionID=55898, name="So this used to be an Embassy for mortals?"},
    {gossipOptionID=55899, name="Have you not seen |5human before?"},
    {gossipOptionID=55900, name="Tell me about the history of the Djaradin."}}
Rows = {}
for index, option in ipairs(APIOptions) do
    local row = {shown=true, id=option.gossipOptionID, x=.081, y=.66-index*.02,
        text=(index==3 and "|cFF0000FF(Quest)|r " or "") .. option.name}
    row.GetElementData=function(self) return {gossipOptionID=self.id} end
    row.Text={GetText=function() return row.text end}
    Rows[index]=row
end
GossipFrame={shown=true, GreetingPanel={ScrollBox={
    ForEachFrame=function(self, visit) for _, row in ipairs(Rows) do visit(row) end end}}}
C_GossipInfo={GetOptions=function() return APIOptions end}
''' + body + '''
function ExportOptionsForTest() return readGossipOptions() end
function ExportSingleForTest() return readSingleGossipOption() end
''')
    return lua


@pytest.mark.parametrize("getter", ["Text", "GetText", "GetRegions"])
def test_lua_exports_the_rendered_prefix_from_the_same_identified_option_row(getter):
    lua = sensor()
    if getter == "GetText":
        lua.execute("Rows[3].GetText=function(self) return self.text end; Rows[3].Text=nil")
    elif getter == "GetRegions":
        lua.execute("Rows[3].GetRegions=function(self) return {GetText=function() return self.text end} end; Rows[3].Text=nil")
    options = json.loads(lua.eval("ns.EncodeJSON(ExportOptionsForTest())"))
    assert options[2]["name"] == OPTIONS[2]["name"]
    assert options[2]["display_name"] == OPTIONS[2]["display_name"]
    assert options[2]["id"] == 55900
    assert "(Quest)" not in options[0].get("display_name", "")


def test_single_option_also_preserves_its_displayed_quest_marker():
    lua = sensor()
    lua.execute("APIOptions={APIOptions[3]}")
    option = json.loads(lua.eval("ns.EncodeJSON(ExportSingleForTest())"))
    assert option["id"] == 55900 and option["display_name"] == OPTIONS[2]["display_name"]


def test_identical_titles_cannot_borrow_another_option_ids_marker_or_point():
    lua = sensor()
    lua.execute("APIOptions[1].name=APIOptions[3].name; Rows[1].text='(Quest) '..APIOptions[3].name; Rows[3].text=APIOptions[3].name")
    option = json.loads(lua.eval("ns.EncodeJSON(ExportOptionsForTest())"))[2]
    assert option["id"] == 55900 and option["display_name"] == OPTIONS[2]["name"]
    assert abs(option["y"] - .60) < 1e-6


def test_contradictory_widget_option_id_does_not_supply_a_displayed_marker():
    lua = sensor()
    lua.execute("Rows[3].gossipOptionID=999")
    option = json.loads(lua.eval("ns.EncodeJSON(ExportOptionsForTest())"))[2]
    assert "display_name" not in option and "x" not in option


@pytest.mark.parametrize("position", [0, 1])
def test_a_plain_getter_cannot_hide_the_same_rows_decorated_font_string(position):
    lua = sensor()
    lua.execute("Rows[3].GetText=function() return APIOptions[3].name end")
    if position == 0:
        lua.execute("Rows[3].GetRegions=function() return {GetText=function() return APIOptions[3].name end} end")
    else:
        lua.execute("Rows[3].GetRegions=function() return {GetText=function() return Rows[3].text end}, {GetText=function() return APIOptions[3].name end} end; Rows[3].Text=nil")
    option = json.loads(lua.eval("ns.EncodeJSON(ExportOptionsForTest())"))[2]
    assert option["display_name"] == OPTIONS[2]["display_name"]


@pytest.mark.parametrize("bad", ["different_text", "hidden", "secret"])
def test_lua_never_borrows_a_marker_from_unrelated_hidden_or_secret_text(bad):
    lua = sensor()
    if bad == "different_text":
        lua.execute('Rows[3].text="(Quest) A different option"')
    elif bad == "hidden":
        lua.execute("Rows[3].shown=false")
    else:
        lua.execute("Rows[3].text={secret=true}")
    options = json.loads(lua.eval("ns.EncodeJSON(ExportOptionsForTest())"))
    assert "display_name" not in options[2]


@pytest.mark.parametrize("position", [0, 1, 2])
def test_displayed_quest_option_is_selected_independently_of_row_order(position):
    live = dialog()
    quest = live["quest_ui"]["gossip_options"].pop()
    live["quest_ui"]["gossip_options"].insert(position, quest)
    proposal = QuestDialogPlanningPolicy._talk_gossip(live, True)
    assert proposal is not None and proposal.parameters["gossip_option_id"] == 55900
    assert proposal.parameters["gossip_option_name"] == OPTIONS[2]["name"]
    assert proposal.parameters["gossip_selection_basis"] == "UNIQUE_QUEST_MARKED_OPTION"
    skill = QuestDialogSkill()
    context = active("QUEST_DIALOG", proposal.parameters, live)
    begun = skill.begin(context, live)
    assert begun.status is SkillStatus.RUNNING and len(begun.commands) == 1
    assert begun.commands[0].kind == "CLICK"
    assert skill.verify(context, live, 2.).status is SkillStatus.RUNNING
    credited = deepcopy(live)
    credited["active_quests"][0]["objectives"][2].update(current=1, is_complete=True)
    assert skill.verify(context, credited, 3.).status is SkillStatus.SUCCESS


@pytest.mark.parametrize("bad", ["label_from_other_row", "two_labels", "unavailable", "bad_point",
    "unknown_owner", "wrong_owner", "stale", "objective_complete"])
def test_displayed_label_does_not_bypass_row_identity_or_other_guards(bad):
    live = dialog()
    option = live["quest_ui"]["gossip_options"][-1]
    if bad == "label_from_other_row":
        option["display_name"] = "(Quest) " + OPTIONS[0]["name"]
    elif bad == "two_labels":
        live["quest_ui"]["gossip_options"][0]["display_name"] = "(Quest) " + OPTIONS[0]["name"]
    elif bad == "unavailable":
        option["available"] = False
    elif bad == "bad_point":
        option["x"] = float("nan")
    elif bad == "unknown_owner":
        live["quest_ui"]["npc_guid"] = False
    elif bad == "wrong_owner":
        live["quest_ui"]["npc_guid"] = "Creature-0-3769-2444-47-999-00005824C3"
    elif bad == "stale":
        live["state_age"] = 2.1
    else:
        live["active_quests"][0]["objectives"][2]["is_complete"] = True
    assert QuestDialogPlanningPolicy._talk_gossip(live, True) is None


def test_without_a_label_the_global_two_word_guard_is_not_silently_relaxed():
    live = dialog()
    live["quest_ui"]["gossip_options"][-1].pop("display_name")
    assert QuestDialogPlanningPolicy._talk_gossip(live, True) is None


@pytest.mark.parametrize("change", ["lost", "different_body", "unavailable"])
def test_dispatch_rechecks_the_same_rendered_marker_before_returning_a_click(change):
    live = dialog()
    proposal = QuestDialogPlanningPolicy._talk_gossip(live, True)
    assert proposal is not None
    before = deepcopy(live)
    option = live["quest_ui"]["gossip_options"][-1]
    if change == "lost":
        option.pop("display_name")
    elif change == "different_body":
        option["display_name"] = "(Quest) Another conversation"
    else:
        option["available"] = False
    result = QuestDialogSkill().begin(active("QUEST_DIALOG", proposal.parameters, before), live)
    assert result.status in {SkillStatus.FAILURE, SkillStatus.BLOCKED} and not result.commands


def test_actual_lua_sensor_transport_assembler_planner_and_skill_preserve_the_marker():
    lua = sensor()
    live = dialog()
    live["quest_ui"]["gossip_options"] = json.loads(lua.eval("ns.EncodeJSON(ExportOptionsForTest())"))
    sample = lua.table_from(live, recursive=True)
    assembler = PacketAssembler()
    decoded = None
    for index in range(60):
        fast, full = lua.globals().ns.NextLanePackets(sample, sample, 1792, 1024)
        assembler.feed(fast, now=100.+index*.01)
        result = assembler.feed(full, now=100.+index*.01)
        if result and (result.get("quest_ui") or {}).get("gossip_options"):
            decoded = result
            break
    assert decoded is not None
    assert decoded["quest_ui"]["gossip_options"][2]["display_name"] == OPTIONS[2]["display_name"]
    world = WorldModel()
    world.ingest(Observation.create(decoded, 100.))
    world.state.update(decoded)
    proposal = Planner(SkillRegistry()).candidates(Goal.parse("Questelj", 1), world, 100.)[0]
    assert proposal.skill == "QUEST_DIALOG" and proposal.parameters["gossip_option_id"] == 55900
    context = active("QUEST_DIALOG", proposal.parameters, decoded)
    assert QuestDialogSkill().begin(context, decoded).status is SkillStatus.RUNNING
