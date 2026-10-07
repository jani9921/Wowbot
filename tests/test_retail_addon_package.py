from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CANONICAL = ROOT / "addon" / "AIPlayerControllerExport"
VERSIONED = ROOT / "addon" / "AIPlayerControllerExport-12.1.0"


def test_retail_packages_are_identical() -> None:
    for name in ("Bindings.lua", "Transport.lua", "AIPlayerControllerExport.lua",
                 "AIPlayerControllerExport.toc"):
        assert (CANONICAL / name).read_bytes() == (VERSIONED / name).read_bytes()


def test_retail_toc_and_protocol_versions_are_explicit() -> None:
    toc = (CANONICAL / "AIPlayerControllerExport.toc").read_text(encoding="utf-8")
    lua = (CANONICAL / "AIPlayerControllerExport.lua").read_text(encoding="utf-8")
    assert "## Interface: 120100" in toc
    assert "## Version: 0.9.61-12.1.0" in toc
    assert 'local PROTOCOL_VERSION = "AIPC5"' in lua
    assert toc.index("Transport.lua") < toc.index("AIPlayerControllerExport.lua")
    assert "local SCHEMA_VERSION = 4" in lua
    assert "local function readQuestRewardChoices" in lua
    assert "GetNumQuestChoices" in lua
    assert "C_QuestLog.IsCampaignQuest" in lua
    assert "local function readExtraAction" in lua
    assert '"EXTRAACTIONBUTTON1"' in lua
    assert "action_type = safeText(actionType" in lua
    assert "action_id = optionalNumber(actionID)" in lua
    assert 'type_source = specialItemReferenced and "QUEST_SPECIAL_ITEM_NAME_MATCH"' in lua
    assert 'item_name = safeText(specialItemName, "")' in lua


def test_quest_waypoints_export_api_world_coordinates_for_mmap_routing() -> None:
    lua = (CANONICAL / "AIPlayerControllerExport.lua").read_text(encoding="utf-8")
    helper = lua[lua.index("local function mapToWorldPosition"):
                 lua.index("local function readQuests")]
    assert "C_Map.GetWorldPosFromMapPos" in helper
    assert "CreateVector2D" in helper
    assert 'coordinate_space = "WORLD_YARDS"' in helper
    assert "instance_id = instanceID" in helper
    assert "z_known = false" in helper
    assert lua.count("world_position = waypointWorld") == 2
    assert "world_position = worldPosition" in lua


def test_fast_player_world_xy_comes_from_the_fresh_map_sample() -> None:
    lua = (CANONICAL / "AIPlayerControllerExport.lua").read_text(encoding="utf-8")
    helper = lua[lua.index("local function currentPlayerWorldPosition"):
                 lua.index("local function readQuests")]
    assert "mapToWorldPosition(mapID, mapX, mapY)" in helper
    assert 'converted.source = "C_MAP_PLAYER_WORLD_POS"' in helper
    assert 'converted.z_source = "NAVMESH_XY_PROJECTION_REQUIRED"' in helper
    assert "converted.z_known = false" in helper
    assert "UnitPosition component is authoritative" in lua
    assert lua.count("currentPlayerWorldPosition(mapID, pos,") == 2
    assert "z = optionalNumber(z)" in lua
    assert "z_known = optionalNumber(z) ~= nil" in lua


def test_indoor_sensor_survives_each_compact_transport_profile() -> None:
    lua = (CANONICAL / "AIPlayerControllerExport.lua").read_text(encoding="utf-8")
    transport = (CANONICAL / "Transport.lua").read_text(encoding="utf-8")
    assert 'if type(indoors) ~= "boolean" then indoors = nil end' in lua
    assert transport.count("indoors=sample.movement.indoors") == 6


def test_ui_errors_are_attempt_correlatable_on_full_and_fast_lanes() -> None:
    lua = (CANONICAL / "AIPlayerControllerExport.lua").read_text(encoding="utf-8")
    transport = (CANONICAL / "Transport.lua").read_text(encoding="utf-8")
    assert 'emitEvent("UI_ERROR_MESSAGE"' in lua
    assert "lastUIErrorSequence = eventSequence" in lua
    for field in ("ui_error_at", "ui_error_sequence", "ui_error_code"):
        assert field in lua
        assert field in transport


def test_retail_frame_visibility_uses_effective_parent_aware_state() -> None:
    lua = (CANONICAL / "AIPlayerControllerExport.lua").read_text(encoding="utf-8")
    helper = lua[lua.index("local function frameIsShown"):lua.index("local function framePoint")]
    assert helper.index("candidate.IsVisible") < helper.index("candidate.IsShown")


def test_gossip_row_lookup_handles_retail_scrollbox_wrappers_and_text_regions() -> None:
    lua = (CANONICAL / "AIPlayerControllerExport.lua").read_text(encoding="utf-8")
    helper = lua[lua.index("local function normalizedQuestRowText"):
                 lua.index("local function rewardChoiceFrame")]
    assert "candidate.GetElementData" in helper
    assert "dataMatches(data, 0, {})" in helper
    assert "candidate:GetRegions()" in helper
    assert "depth > 8" in helper
    assert "scrollBox:ForEachFrame(inspect)" in helper


def test_quest_detail_hint_cannot_reopen_a_hidden_dialog() -> None:
    lua = (CANONICAL / "AIPlayerControllerExport.lua").read_text(encoding="utf-8")
    start = lua.index("local function readQuestUI")
    fast = lua.index("local function readFastQuestUI")
    end = lua.index("local function readTutorialHint")
    slow_body, fast_body = lua[start:fast], lua[fast:end]
    # A QUEST_DETAIL event names the expected action, but it is not a live UI
    # context.  A hidden QuestFrame must therefore stay closed in both lanes.
    assert "if result.open and questUIHint.open" in slow_body
    assert "result.open = frameIsShown(_G.GossipFrame) or frameIsShown(_G.QuestFrame)" in fast_body
    assert "or\n        (questUIHint.open" not in fast_body


def test_reward_choices_require_visible_completion_context_not_quest_offer() -> None:
    lua = (CANONICAL / "AIPlayerControllerExport.lua").read_text(encoding="utf-8")
    start = lua.index("local function readQuestUI")
    end = lua.index("local function readFastCombatHint")
    body = lua[start:end]
    accept_gate = body.index("local acceptVisible = frameIsShown(_G.QuestFrameAcceptButton)")
    completion_gate = body.index("local rewardContext = result.open and not acceptVisible")
    visibility_gate = body.index("if rewardContext then\n        result.reward_choices = readQuestRewardChoices()")
    reward_action = body.index('result.action = "REWARD_SELECT"')
    assert accept_gate < completion_gate < visibility_gate < reward_action
    # 0.9.46 (live 2026-10-04): a single reward is handed out on Complete
    # Quest; only two or more rewards are a selection.
    assert "if rewardContext and #result.reward_choices > 1" in body


def test_reward_selection_is_read_from_quest_info_item_choice() -> None:
    """Live 2026-10-04: the agent clicked the reward and the client selected
    it, but Retail 12 reward buttons have no GetChecked, so the addon kept
    reward_selected_index=0 and never exposed Complete Quest."""
    import pytest
    lupa = pytest.importorskip("lupa")
    source = (CANONICAL / "AIPlayerControllerExport.lua").read_text(encoding="utf-8")
    start = source.index("local function chosenRewardIndex()")
    end = source.index("\nend\n", source.index("local function readQuestRewardChoices()")) + 5
    harness = '''
unpack = unpack or table.unpack
local function accessible(v) return true end
local function optionalNumber(v) if type(v) ~= "number" then return nil end return v end
local function optionalBool(v) if v == nil then return nil end return v and true or false end
local function safeText(v, d) return v or d end
local function safeCall(fn, ...)
    if type(fn) ~= "function" then return nil end
    local r = {pcall(fn, ...)}
    if not r[1] then return nil end
    return select(2, unpack(r))
end
local function frameIsShown(f) return f and f.shown end
local buttons = {{}, {}}
local function rewardChoiceFrame(i) return buttons[i] end
local function framePoint(b) return .1, .6 end
GetNumQuestChoices = function() return 2 end
GetQuestItemInfo = function(kind, i) return "Item" .. i, nil, 1, 2, true, 100 + i, 7 end
''' + source[start:end] + '''
local out = {}
local function sample()
    local r = readQuestRewardChoices()
    out[#out + 1] = tostring(r[1].selected) .. "," .. tostring(r[2].selected) .. ","
        .. tostring(rewardChoiceUnresolved())
end
QuestInfoFrame = {itemChoice = 0}
sample()
QuestInfoFrame.itemChoice = 2
sample()
QuestInfoFrame = nil
QuestInfoRewardsFrame = {ItemHighlight = {shown = true,
    GetPoint = function(self, n) return "TOPLEFT", buttons[1], "TOPLEFT", -8, 7 end}}
sample()
return table.concat(out, "|")
'''
    assert lupa.LuaRuntime().execute(harness) == "nil,nil,true|false,true,false|true,nil,false"
    # The fast lane must not offer Complete Quest while the choice is open.
    fast = source[source.index("local function readFastQuestUI"):source.index("local function readTutorialHint")]
    assert 'if candidate[1] == "COMPLETE" and rewardChoiceUnresolved() then' in fast


def test_addon_remains_a_read_only_sensor() -> None:
    lua = (CANONICAL / "AIPlayerControllerExport.lua").read_text(encoding="utf-8")
    forbidden_calls = (
        "MoveForwardStart(",
        "MoveBackwardStart(",
        "TurnLeftStart(",
        "TurnRightStart(",
        "CastSpellByName(",
        "UseAction(",
        "C_QuestLog.SetSelectedQuest(",
    )
    for call in forbidden_calls:
        assert call not in lua


def test_retail_addon_exports_bounded_world_map_hierarchy_on_full_and_fast_lanes() -> None:
    lua = (CANONICAL / "AIPlayerControllerExport.lua").read_text(encoding="utf-8")
    transport = (CANONICAL / "Transport.lua").read_text(encoding="utf-8")
    helper = lua[lua.index("local function readMapContext"):
                 lua.index("local function recordDeadTarget")]
    assert "C_Map.GetMapInfo" in helper
    assert "info.parentMapID" in helper
    assert "for _ = 1, 4 do" in helper
    assert "seen[current]" in helper
    assert "map_context = readMapContext(mapID, displayedMapID)" in lua
    assert "map_id = liveMapID, map_context = readMapContext" in lua
    assert "map_context=sample.map_context" in transport


def test_retail_addon_exports_authoritative_map_to_world_affine_basis() -> None:
    lua = (CANONICAL / "AIPlayerControllerExport.lua").read_text(encoding="utf-8")
    helper = lua[lua.index("local function mapWorldTransform"):
                 lua.index("local function currentPlayerWorldPosition")]
    assert "mapToWorldPosition(mapID, 0, 0)" in helper
    assert "mapToWorldPosition(mapID, 1, 0)" in helper
    assert "mapToWorldPosition(mapID, 0, 1)" in helper
    assert 'source = "C_MAP_WORLD_POS_AFFINE"' in helper
    assert "map_world_transform = mapWorldTransform(telemetryMapID)" in lua


def test_dialog_quest_text_is_exported_first_with_the_ender_guid() -> None:
    """0.9.56 (user 2026-10-05, quest_creature_memory): the giver/ender of the
    latest quest dialog must reach the agent even when the quest has already
    left the log (turned in) or is not in it yet (offered)."""
    import pytest
    lupa = pytest.importorskip("lupa")
    source = (CANONICAL / "AIPlayerControllerExport.lua").read_text(encoding="utf-8")
    start = source.index("local questLogTextSeen = {}")
    end = source.index("-- Map data APIs")
    harness = """
local now = 100
local function nowSeconds() return now end
local function accessible(v) return true end
local function safeNumber(v, f) if type(v) ~= "number" then return f or 0 end return v end
local function safeText(v, d) if v == nil then return d end return tostring(v) end
AIPlayerControllerExportDB = {}
""" + source[start:end] + """
rememberQuestText(55194, "ender_name", "Captain Garrick")
rememberQuestText(55194, "ender_guid", "Creature-0-3113-2175-63341-245394-00004115E3")
rememberQuestText(7, "description", "other quest")
questTextPending.questID = 55194
questTextPending.untilAt = 105
local first = readQuestText({{quest_id = 7}})
now = 106
local later = readQuestText({{quest_id = 7}})
return first.quest_id .. "," .. first.ender_name .. "," .. first.ender_guid .. "|" .. later.quest_id
"""
    assert lupa.LuaRuntime().execute(harness) == (
        "55194,Captain Garrick,Creature-0-3113-2175-63341-245394-00004115E3|7")
    body = source[source.index("local function readQuests"):source.index("local function readQuestText")]
    assert "GetQuestLogCompletionText, index" in body
    assert "completion_log_text = completionLogText and" in body
    handler = source[source.index('if event == "QUEST_DETAIL" or event == "QUEST_PROGRESS"'):]
    assert 'rememberQuestText(dialogQuestID, "ender_guid", safeUnitCall(UnitGUID, "npc"))' in handler


def test_soft_interact_game_objects_are_exported() -> None:
    """0.9.57 (user 2026-10-06): the Thick Cocoon is a soft-interact game
    object; UnitExists() is false for it, so its GUID/name go out separately."""
    source = (CANONICAL / "AIPlayerControllerExport.lua").read_text(encoding="utf-8")
    body = source[source.index("local function readSoftTargets"):source.index("local function readNameplates")]
    assert 'elseif unitToken == "softinteract" then' in body
    assert 'guidType(guid) == "OBJECT"' in body
    assert 'unit_type = "GAMEOBJECT"' in body
