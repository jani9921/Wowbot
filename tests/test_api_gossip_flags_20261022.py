"""Read the same API flag that Retail uses to render its quest gossip label."""
from copy import deepcopy
import json

import pytest

from adapters.telemetry_packets import PacketAssembler
from wowbot.agent.models import Goal, Observation
from wowbot.agent.planner import Planner
from wowbot.agent.quest_dialog_planning import QuestDialogPlanningPolicy
from wowbot.agent.quest_ui_evidence import quest_option_marked
from wowbot.agent.skills import SkillRegistry
from wowbot.agent.world import WorldModel
from wowbot.runtime import SkillStatus
from wowbot.skills.quest_dialog import QuestDialogSkill
from test_m0_combat_loot_skills import active
from test_rendered_gossip_marker_20261022 import OPTIONS, dialog, sensor


def flag_sensor(mask=64):
    lua = sensor()
    lua.execute(f'''
Enum={{GossipOptionRecFlags={{QuestLabelPrepend={mask}}},
       GossipOptionStatus={{Available=0}}}}
FlagsUtil={{IsSet=function(value, flag) return math.floor(value/flag)%2 == 1 end}}
for index, option in ipairs(APIOptions) do
    option.flags=(index==3 and {mask} or 0)
    -- Real Retail elementData wraps optionInfo in .info, rather than
    -- placing gossipOptionID directly on the button or elementData.
    Rows[index].GetElementData=function() return {{info=option, buttonType=3}} end
end
-- No rendered label is available: the API evidence must stand on its own.
Rows[3].Text=nil
''')
    return lua


@pytest.mark.parametrize("mask", [8, 64, 1024])
def test_lua_uses_runtime_enum_not_a_guessed_numeric_flag(mask):
    lua = flag_sensor(mask)
    options = json.loads(lua.eval("ns.EncodeJSON(ExportOptionsForTest())"))
    assert [o["quest_label_prepend"] for o in options] == [False, False, True]
    assert [o["flags"] for o in options] == [0, 0, mask]
    assert options[2]["id"] == 55900 and options[2]["name"] == OPTIONS[2]["name"]
    assert "display_name" not in options[2]


def test_movie_or_other_option_flags_are_not_a_quest_label():
    lua = flag_sensor()
    lua.execute("APIOptions[1].flags=128; APIOptions[2].flags=192; APIOptions[3].flags=0")
    options = json.loads(lua.eval("ns.EncodeJSON(ExportOptionsForTest())"))
    assert [o["quest_label_prepend"] for o in options] == [False, True, False]


@pytest.mark.parametrize("missing", ["flags", "enum", "helper", "secret", "boolean",
    "negative", "fraction", "nan", "infinity", "invalid_mask"])
def test_unknown_inaccessible_or_invalid_api_flags_never_become_quest_proof(missing):
    lua = flag_sensor()
    lua.execute({
        "flags": "APIOptions[3].flags=nil",
        "enum": "Enum.GossipOptionRecFlags=nil",
        "helper": "FlagsUtil=nil",
        "secret": "APIOptions[3].flags={secret=true}",
        "boolean": "APIOptions[3].flags=true",
        "negative": "APIOptions[3].flags=-1",
        "fraction": "APIOptions[3].flags=64.5",
        "nan": "APIOptions[3].flags=0/0",
        "infinity": "APIOptions[3].flags=math.huge",
        "invalid_mask": "Enum.GossipOptionRecFlags.QuestLabelPrepend=0",
    }[missing])
    option = json.loads(lua.eval("ns.EncodeJSON(ExportOptionsForTest())"))[2]
    assert "quest_label_prepend" not in option
    assert not quest_option_marked(option)


def test_single_option_exports_the_same_api_quest_proof():
    lua = flag_sensor()
    lua.execute("APIOptions={APIOptions[3]}")
    option = json.loads(lua.eval("ns.EncodeJSON(ExportSingleForTest())"))
    assert option["quest_label_prepend"] is True and option["flags"] == 64


def test_a_known_false_api_flag_overrules_stale_or_decorated_text():
    assert not quest_option_marked({"name": "(Quest) Outdated label", "quest_label_prepend": False})
    assert not quest_option_marked({**OPTIONS[2], "quest_label_prepend": False})
    assert quest_option_marked({"name": "An undecorated option", "quest_label_prepend": True})


@pytest.mark.parametrize("value", [1, "true", "false", {}, []])
def test_only_an_actual_api_boolean_is_marker_proof(value):
    assert not quest_option_marked({"name": "An undecorated option", "quest_label_prepend": value})


@pytest.mark.parametrize("position", [0, 1, 2])
def test_api_marked_row_is_selected_and_rechecked_without_rendered_text(position):
    live = dialog()
    option = live["quest_ui"]["gossip_options"].pop()
    option.pop("display_name")
    option.update(flags=64, quest_label_prepend=True)
    live["quest_ui"]["gossip_options"].insert(position, option)
    proposal = QuestDialogPlanningPolicy._talk_gossip(live, True)
    assert proposal is not None and proposal.parameters["gossip_option_id"] == 55900
    skill = QuestDialogSkill()
    context = active("QUEST_DIALOG", proposal.parameters, live)
    result = skill.begin(context, live)
    assert result.status is SkillStatus.RUNNING
    assert [(c.kind, c.x, c.y) for c in result.commands] == [("CLICK", .081, .60)]
    assert skill.verify(context, live, 2.).status is SkillStatus.RUNNING
    credited = deepcopy(live)
    credited["active_quests"][0]["objectives"][2].update(current=1, is_complete=True)
    assert skill.verify(context, credited, 3.).status is SkillStatus.SUCCESS


@pytest.mark.parametrize("changed", ["removed", "false", "unavailable"])
def test_dispatch_rejects_api_marker_loss_or_unavailability(changed):
    live = dialog()
    option = live["quest_ui"]["gossip_options"][-1]
    option.pop("display_name")
    option["quest_label_prepend"] = True
    proposal = QuestDialogPlanningPolicy._talk_gossip(live, True)
    assert proposal is not None
    before = deepcopy(live)
    if changed == "removed":
        option.pop("quest_label_prepend")
    elif changed == "false":
        option["quest_label_prepend"] = False
    else:
        option["available"] = False
    result = QuestDialogSkill().begin(active("QUEST_DIALOG", proposal.parameters, before), live)
    assert result.status in {SkillStatus.FAILURE, SkillStatus.BLOCKED} and not result.commands


@pytest.mark.parametrize("bad", ["other_owner", "unknown_owner", "stale", "two_marked", "unavailable", "bad_point"])
def test_api_marker_cannot_bypass_existing_identity_freshness_or_ambiguity_guards(bad):
    live = dialog()
    option = live["quest_ui"]["gossip_options"][-1]
    option.pop("display_name")
    option["quest_label_prepend"] = True
    if bad == "other_owner":
        live["quest_ui"]["npc_guid"] = "Creature-0-3769-2444-47-999-00005824C3"
    elif bad == "unknown_owner":
        live["quest_ui"]["npc_guid"] = False
    elif bad == "stale":
        live["state_age"] = 2.1
    elif bad == "two_marked":
        live["quest_ui"]["gossip_options"][0]["quest_label_prepend"] = True
    elif bad == "unavailable":
        option["available"] = False
    else:
        option["x"] = float("nan")
    assert QuestDialogPlanningPolicy._talk_gossip(live, True) is None


def test_real_lua_api_flags_survive_paging_and_drive_the_shared_planner_and_skill():
    lua = flag_sensor()
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
    assert decoded["quest_ui"]["gossip_options"][2]["quest_label_prepend"] is True
    world = WorldModel()
    world.ingest(Observation.create(decoded, 100.))
    world.state.update(decoded)
    proposal = Planner(SkillRegistry()).candidates(Goal.parse("Questelj", 1), world, 100.)[0]
    assert proposal.skill == "QUEST_DIALOG" and proposal.parameters["gossip_option_id"] == 55900
    context = active("QUEST_DIALOG", proposal.parameters, decoded)
    begun = QuestDialogSkill().begin(context, decoded)
    assert begun.status is SkillStatus.RUNNING and len(begun.commands) == 1


def test_named_color_and_button_fontstring_are_supported_for_legacy_text_fallback():
    lua = sensor()
    lua.execute('''
Rows[3].Text=nil
Rows[3].GetFontString=function(self) return {GetText=function()
    return "|cnBRIGHTBLUE_FONT_COLOR:(Quest)|r " .. APIOptions[3].name
end} end
''')
    option = json.loads(lua.eval("ns.EncodeJSON(ExportOptionsForTest())"))[2]
    assert option["display_name"].startswith("|cnBRIGHTBLUE_FONT_COLOR:")
    assert quest_option_marked(option)


def test_nested_element_info_id_cannot_lend_another_rows_marker_or_point():
    lua = sensor()
    lua.execute('''
Rows[1].GetElementData=function() return {info={gossipOptionID=55898},
    titleOptionButton={gossipOptionID=55900}} end
Rows[3].shown=false
''')
    option = json.loads(lua.eval("ns.EncodeJSON(ExportOptionsForTest())"))[2]
    assert "x" not in option and "display_name" not in option
