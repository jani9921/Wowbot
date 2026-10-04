local ADDON_NAME, namespace = ...
local frame = CreateFrame("Frame")
-- Hidden background tooltip used only to force the client to resolve a
-- unit's name/data (the same thing a real mouseover triggers) without
-- moving the cursor or showing anything on screen. Confirmed live
-- 2026-09-12: UnitName("target") stayed nil for 7-8+ seconds after a
-- pure tab-target (TARGETNEARESTENEMY), while manually hovering the same
-- unit resolved it immediately -- SetUnit on this scanning tooltip
-- reproduces that resolution path for readUnit()'s UnitName fallback.
local scanTooltip = CreateFrame("GameTooltip", "AIPlayerControllerScanTooltip", nil, "GameTooltipTemplate")
scanTooltip:SetOwner(UIParent, "ANCHOR_NONE")
local panel
local ticker
local transportTicker
local latestSnapshot
local isLoading = false
local lastError
local lastUIError
local lastUIErrorAt = 0
local lastUIErrorSequence = 0
local lastUIErrorCode
local refreshCount = 0
local lastMouseoverKey = nil
local lastRefreshAt = 0
local pixelFrame
local pixelCells = {}
local questRevision = 0
local lastQuestSignature = ""
local killedCorpses = {}
local eventSequence = 0
local latestEvent
local previousState = {}
local cache = {}
local dirty = { actionbar = true, quests = true, quest_ui = true, inventory = true }
local questUIHint = {open = false, action = "", observed_at = 0}
-- PREPARED 2026-09-14, UNTESTED LIVE. Mirrors questUIHint's fast-lane
-- pattern so COMBAT/DEFEND's success check (skills.py verify()) no longer
-- depends solely on the slow/paged `events` list for spell-cast
-- confirmation. See docs/LIVE_VALIDATION.md for the full test checklist
-- before this is trusted as the primary signal.
local combatHint = {spell_id = 0, at = 0}

local ADDON_VERSION = "0.9.54"
local PROTOCOL_VERSION = "AIPC5"
local SCHEMA_VERSION = 4
local SNAPSHOT_INTERVAL = 0.2
-- Live-measured 2026-09-14: the opt-in DXGI capture backend
-- (dxgi_capture.py) sustains ~60 distinct frames/sec against this client
-- (the display's own refresh-rate ceiling, confirmed live), above the
-- previous GDI backend's measured ~28 Hz. Raised to match so the pixel
-- strip's own write cadence is no longer the bottleneck once that capture
-- backend is in use; the previous 0.025 (40 Hz) was itself untested against
-- this specific ceiling. UNTESTED LIVE: whether 60 Hz Lua/UI work here
-- measurably affects the WoW client's own frame time -- the user reported
-- ~100 FPS headroom, but that was not measured with this addon at 60 Hz.
-- See docs/LIVE_VALIDATION.md for the full checklist before treating this
-- as validated.
local TRANSPORT_INTERVAL = 1/60
local EVENT_HISTORY_LIMIT = 100

local PIXEL_COLUMNS = 128
local PIXEL_CELL_SIZE = 4
local PIXEL_MAX_BYTES = 1000
local PIXEL_PALETTE = {
    {0.05, 0.05, 0.05},
    {1.00, 0.05, 0.05},
    {0.05, 1.00, 0.05},
    {0.05, 0.20, 1.00},
}
local PIXEL_HEADER = {3, 1, 2, 4, 3, 4, 2, 1}

local function bool(value)
    if issecretvalue and issecretvalue(value) then return false end
    if canaccessvalue and not canaccessvalue(value) then return false end
    return value and true or false
end

local function accessible(value)
    if issecretvalue and issecretvalue(value) then return false end
    if canaccessvalue and not canaccessvalue(value) then return false end
    return true
end

local function optionalBool(value)
    if not accessible(value) or value == nil then return nil end
    if value == 0 then return false end
    return value and true or false
end

local function safeText(value, fallback)
    if not accessible(value) or value == nil then return fallback or "?" end
    return tostring(value)
end

local function safeNumber(value, fallback)
    if not accessible(value) or type(value) ~= "number" then return fallback or 0 end
    return value
end

local function optionalNumber(value)
    if not accessible(value) or type(value) ~= "number" then return nil end
    return value
end

local function safeCall(fn, ...)
    if type(fn) ~= "function" then return nil end
    local ok, a, b, c, d, e, f, g, h, i, j, k = pcall(fn, ...)
    if not ok then return nil end
    if not accessible(a) then a = nil end
    if not accessible(b) then b = nil end
    if not accessible(c) then c = nil end
    if not accessible(d) then d = nil end
    if not accessible(e) then e = nil end
    if not accessible(f) then f = nil end
    if not accessible(g) then g = nil end
    if not accessible(h) then h = nil end
    if not accessible(i) then i = nil end
    if not accessible(j) then j = nil end
    if not accessible(k) then k = nil end
    return a, b, c, d, e, f, g, h, i, j, k
end

local function unitExists(unit)
    return bool(safeCall(UnitExists, unit))
end

local function nowSeconds()
    return safeNumber(safeCall(GetTime), 0)
end

local function serverTimestamp()
    return safeNumber(safeCall(GetServerTime), 0)
end

local function sanitizeEventValue(value, depth)
    depth = depth or 0
    if depth > 3 or not accessible(value) then return nil end
    local kind = type(value)
    if kind == "string" or kind == "number" or kind == "boolean" then return value end
    if kind ~= "table" then return nil end
    local result = {}
    for key, child in pairs(value) do
        if accessible(key) and (type(key) == "string" or type(key) == "number") then
            result[key] = sanitizeEventValue(child, depth + 1)
        end
    end
    return result
end

local function emitEvent(eventType, payload, source)
    eventSequence = eventSequence + 1
    latestEvent = {
        protocol_version = PROTOCOL_VERSION,
        schema_version = SCHEMA_VERSION,
        addon_version = ADDON_VERSION,
        timestamp = serverTimestamp(),
        sequence = eventSequence,
        event_type = safeText(eventType, "UNKNOWN"),
        source = safeText(source, "WOW_API"),
        payload = sanitizeEventValue(payload or {}),
    }
    AIPlayerControllerExportDB = AIPlayerControllerExportDB or {}
    AIPlayerControllerExportDB.events = AIPlayerControllerExportDB.events or {}
    AIPlayerControllerExportDB.events[#AIPlayerControllerExportDB.events + 1] = latestEvent
    while #AIPlayerControllerExportDB.events > EVENT_HISTORY_LIMIT do
        table.remove(AIPlayerControllerExportDB.events, 1)
    end
    AIPlayerControllerExportDB.latest_event = latestEvent
    AIPlayerControllerExportDB.last_event_sequence = eventSequence
end

local function initializeDatabase()
    AIPlayerControllerExportDB = AIPlayerControllerExportDB or {}
    AIPlayerControllerExportDB.settings = AIPlayerControllerExportDB.settings or {}
    local configuredInterval = safeNumber(AIPlayerControllerExportDB.settings.snapshot_interval, SNAPSHOT_INTERVAL)
    if configuredInterval < 0.2 or configuredInterval > 10 then configuredInterval = SNAPSHOT_INTERVAL end
    AIPlayerControllerExportDB.settings.snapshot_interval = configuredInterval
    AIPlayerControllerExportDB.settings.debug = bool(AIPlayerControllerExportDB.settings.debug)
    AIPlayerControllerExportDB.events = AIPlayerControllerExportDB.events or {}
    eventSequence = safeNumber(AIPlayerControllerExportDB.last_event_sequence, 0)
end

local function objectiveType(text)
    if not accessible(text) then return "UNKNOWN" end
    local value = string.lower(text or "")
    if value:find("escort") or value:find("accompany") or value:find("protect while") then return "ESCORT" end
    if value:find("turn in") or value:find("return to") or value:find("report to") then return "TURN_IN" end
    if value:find("kill") or value:find("slay") or value:find("slain") or value:find("defeat") or value:find("destroy") or value:find("attack") then return "KILL" end
    if value:find("talk") or value:find("speak") then return "TALK" end
    if value:find("purchase") or value:find("buy") then return "BUY" end
    if value:find("sell") then return "SELL" end
    if value:find("loot") or value:find("recover") or value:find("retrieve") then return "LOOT" end
    if value:find("collect") or value:find("gather") or value:find("harvest") then return "GATHER" end
    if value:find("use") or value:find("cook") or value:find("burn") then return "USE_ITEM" end
    if value:find("interact") or value:find("open ") or value:find("examine") or value:find("inspect") then return "INTERACT" end
    if value:find("travel") or value:find("reach") or value:find("meet") or value:find("find") or value:find("locate") or value:find("inside") then return "MOVE_TO" end
    return "UNKNOWN"
end

local function normalizedObjectiveType(apiType, text)
    if accessible(apiType) then
        local value = string.lower(tostring(apiType or ""))
        if value == "monster" or value == "player" then return "KILL" end
        if value == "item" or value == "currency" then return "COLLECT" end
        if value == "object" then return "INTERACT" end
        if value == "event" or value == "log" then return objectiveType(text) end
        if value == "progressbar" then return "AREA" end
    end
    return objectiveType(text)
end

-- Full readActionbar() below only feeds the slow/paged STATE snapshot
-- (dirty.actionbar only flips on ACTIONBAR_SLOT_CHANGED/SPELLS_CHANGED, not
-- on cooldowns ticking), so combat_controller.choose_action() was picking
-- abilities off data that could be several seconds stale mid-fight --
-- live-confirmed 2026-09-12: an ability kept getting re-selected and
-- rejected by the client (still shown available, actually on cooldown)
-- for the rest of a fight. This is the same fast/slow-lane split as
-- target.name, scoped down to just the first 4 action buttons for now
-- (user: "az első 4 bindet figyelje csak egyelőre"). One 4-element
-- positional array per slot -- {id, is_usable, in_range, cooldown_remaining}
-- -- to stay compact; empty/unbound slots are `false`. Matched back to the
-- slow-lane actionbar entries by id in combat_controller.py, not by slot
-- position, since ACTIONBUTTON1-12 only reflect the *currently displayed*
-- bar page (see readActionbar()'s own page-gating below).
local function activeOverridePage()
    local function has(api, legacy)
        local fn = (C_ActionBar and C_ActionBar[api]) or _G[legacy or api]
        return fn and bool(safeCall(fn)) or false
    end
    local function index(api, legacy)
        local fn = (C_ActionBar and C_ActionBar[api]) or _G[legacy or api]
        return fn and safeNumber(safeCall(fn)) or nil
    end
    if has("HasVehicleActionBar") then return index("GetVehicleBarIndex"), "VEHICLE" end
    if has("HasOverrideActionBar") then return index("GetOverrideBarIndex"), "OVERRIDE" end
    if has("HasTempShapeshiftActionBar") then return index("GetTempShapeshiftBarIndex"), "TEMP_SHAPESHIFT" end
    return nil, nil
end

local function readFastActionbar()
    local result = {}
    -- 0.9.49: on a vehicle/override bar the fast lane follows that page, so
    -- range/usability for the boar's charge is fresh (not 2-4 s old).
    local page = activeOverridePage()
    local firstSlot = (page and page > 0) and ((page - 1) * 12) or 0
    for index = 1, 4 do
        local slot = firstSlot + index
        local actionType, id
        if C_ActionBar and C_ActionBar.GetActionInfo then
            local info, legacyID = safeCall(C_ActionBar.GetActionInfo, slot)
            if type(info) == "table" then actionType, id = info.actionType, info.id
            else actionType, id = info, legacyID end
        elseif GetActionInfo then
            actionType, id = safeCall(GetActionInfo, slot)
        end
        if accessible(actionType) and accessible(id) and actionType and id then
            local usable = safeCall((C_ActionBar and C_ActionBar.IsUsableAction) or IsUsableAction, slot)
            local inRange = safeCall((C_ActionBar and C_ActionBar.IsActionInRange) or IsActionInRange, slot, "target")
            local cooldown = C_ActionBar and C_ActionBar.GetActionCooldown and safeCall(C_ActionBar.GetActionCooldown, slot) or nil
            local cooldownStart = type(cooldown) == "table" and optionalNumber(cooldown.startTime) or nil
            local cooldownDuration = type(cooldown) == "table" and optionalNumber(cooldown.duration) or nil
            local remaining = (cooldownStart and cooldownDuration)
                and math.max(0, cooldownStart+cooldownDuration-nowSeconds()) or 0
            result[index] = {id, optionalBool(usable) == true, optionalBool(inRange) == true, remaining}
        else
            result[index] = false
        end
    end
    return result
end

local function readActionbar()
    local result = {}
    local function bindingAction(slot)
        if slot >= 1 and slot <= 12 then return "ACTIONBUTTON" .. slot end
        if slot >= 61 and slot <= 72 then return "MULTIACTIONBAR1BUTTON" .. (slot - 60) end
        if slot >= 49 and slot <= 60 then return "MULTIACTIONBAR2BUTTON" .. (slot - 48) end
        if slot >= 25 and slot <= 36 then return "MULTIACTIONBAR3BUTTON" .. (slot - 24) end
        if slot >= 37 and slot <= 48 then return "MULTIACTIONBAR4BUTTON" .. (slot - 36) end
        -- Unsupported/override pages must not be guessed as primary-bar binds.
        if slot >= 145 and slot <= 156 then return "MULTIACTIONBAR5BUTTON" .. (slot-144) end
        if slot >= 157 and slot <= 168 then return "MULTIACTIONBAR6BUTTON" .. (slot-156) end
        if slot >= 169 and slot <= 180 then return "MULTIACTIONBAR7BUTTON" .. (slot-168) end
        return nil
    end
    for slot = 1, 180 do
        local actionType, id
        if C_ActionBar and C_ActionBar.GetActionInfo then
            local info, legacyID = safeCall(C_ActionBar.GetActionInfo, slot)
            if type(info) == "table" then
                actionType, id = info.actionType, info.id
            else
                actionType, id = info, legacyID
            end
        elseif GetActionInfo then
            actionType, id = safeCall(GetActionInfo, slot)
        end
        if accessible(actionType) and accessible(id) and actionType and id then
            local name
            local spellInfo
            if actionType == "spell" and C_Spell and C_Spell.GetSpellName then
                name = safeCall(C_Spell.GetSpellName, id)
                if C_Spell.GetSpellInfo then spellInfo = safeCall(C_Spell.GetSpellInfo, id) end
            elseif actionType == "item" and C_Item and C_Item.GetItemNameByID then
                name = safeCall(C_Item.GetItemNameByID, id)
            end
            local usable, noResource = safeCall((C_ActionBar and C_ActionBar.IsUsableAction) or IsUsableAction, slot)
            local cooldown = C_ActionBar and C_ActionBar.GetActionCooldown and safeCall(C_ActionBar.GetActionCooldown, slot) or nil
            local binding = bindingAction(slot)
            -- ACTIONBUTTON1..12 execute the currently displayed page only.
            local page = safeNumber(safeCall((C_ActionBar and C_ActionBar.GetActionBarPage) or GetActionBarPage), 1)
            if slot <= 12 and page ~= 1 then binding = nil end
            local primaryKey, secondaryKey = safeCall(GetBindingKey, binding)
            local cooldownStart = type(cooldown) == "table" and optionalNumber(cooldown.startTime) or nil
            local cooldownDuration = type(cooldown) == "table" and optionalNumber(cooldown.duration) or nil
            result[#result + 1] = {
                slot = slot,
                action = binding,
                binding_primary = safeText(primaryKey, ""),
                binding_secondary = safeText(secondaryKey, ""),
                kind = actionType,
                id = id,
                name = accessible(name) and name or nil,
                min_range = type(spellInfo) == "table" and optionalNumber(spellInfo.minRange) or nil,
                max_range = type(spellInfo) == "table" and optionalNumber(spellInfo.maxRange) or nil,
                is_usable = optionalBool(usable),
                lacks_resource = optionalBool(noResource),
                is_harmful = actionType == "spell" and optionalBool(safeCall(C_Spell and C_Spell.IsSpellHarmful, id)) or nil,
                in_range = optionalBool(safeCall((C_ActionBar and C_ActionBar.IsActionInRange) or IsActionInRange, slot, "target")),
                cooldown_start = cooldownStart,
                cooldown_duration = cooldownDuration,
                cooldown_remaining = cooldownStart and cooldownDuration and math.max(0, cooldownStart+cooldownDuration-nowSeconds()) or nil,
            }
        end
    end
    return result
end

-- 0.9.49 (live 2026-10-04, Ride of the Scientifically Enhanced Boar): a
-- ridden Giant Boar replaces the main bar with its own abilities (override /
-- vehicle page).  ACTIONBUTTON1..12 then fire that page; the normal bar
-- export above only showed the player's own, unusable spells.
local function readVehicleBar()
    local page, kind = activeOverridePage()
    if not page or page <= 0 then return nil end
    local result = {page = page, kind = kind, actions = {}}
    for index = 1, 12 do
        local slot = (page - 1) * 12 + index
        local actionType, id
        if C_ActionBar and C_ActionBar.GetActionInfo then
            local info, legacyID = safeCall(C_ActionBar.GetActionInfo, slot)
            if type(info) == "table" then actionType, id = info.actionType, info.id
            else actionType, id = info, legacyID end
        elseif GetActionInfo then
            actionType, id = safeCall(GetActionInfo, slot)
        end
        if accessible(actionType) and accessible(id) and actionType and id then
            local name, spellInfo
            if actionType == "spell" and C_Spell and C_Spell.GetSpellName then
                name = safeCall(C_Spell.GetSpellName, id)
                if C_Spell.GetSpellInfo then spellInfo = safeCall(C_Spell.GetSpellInfo, id) end
            end
            if not (accessible(name) and name) and GetActionText then name = safeCall(GetActionText, slot) end
            -- 0.9.50: every quest vehicle differs; the agent classifies how an
            -- ability is used (dash / targeted / close) from its live text.
            local description
            if actionType == "spell" and C_Spell and C_Spell.GetSpellDescription then
                description = safeCall(C_Spell.GetSpellDescription, id)
            end
            local usable, noResource = safeCall((C_ActionBar and C_ActionBar.IsUsableAction) or IsUsableAction, slot)
            local cooldown = C_ActionBar and C_ActionBar.GetActionCooldown and safeCall(C_ActionBar.GetActionCooldown, slot) or nil
            local cooldownStart = type(cooldown) == "table" and optionalNumber(cooldown.startTime) or nil
            local cooldownDuration = type(cooldown) == "table" and optionalNumber(cooldown.duration) or nil
            local binding = "ACTIONBUTTON" .. index
            local primaryKey, secondaryKey = safeCall(GetBindingKey, binding)
            result.actions[#result.actions + 1] = {
                slot = slot, index = index, action = binding,
                binding_primary = safeText(primaryKey, ""), binding_secondary = safeText(secondaryKey, ""),
                kind = actionType, id = id, name = accessible(name) and name or nil,
                description = accessible(description) and safeText(description, "") or nil,
                min_range = type(spellInfo) == "table" and optionalNumber(spellInfo.minRange) or nil,
                max_range = type(spellInfo) == "table" and optionalNumber(spellInfo.maxRange) or nil,
                is_usable = optionalBool(usable), lacks_resource = optionalBool(noResource),
                is_harmful = actionType == "spell" and optionalBool(safeCall(C_Spell and C_Spell.IsSpellHarmful, id)) or nil,
                in_range = optionalBool(safeCall((C_ActionBar and C_ActionBar.IsActionInRange) or IsActionInRange, slot, "target")),
                cooldown_start = cooldownStart, cooldown_duration = cooldownDuration,
                cooldown_remaining = cooldownStart and cooldownDuration and math.max(0, cooldownStart+cooldownDuration-nowSeconds()) or nil,
                source = "VEHICLE_BAR",
            }
        end
    end
    return result
end

local function buttonScreenPoint(button)
    local x, y = safeCall(button.GetCenter, button)
    local width, height = safeCall(GetScreenWidth), safeCall(GetScreenHeight)
    if accessible(x) and accessible(y) and x and y and width and height and width > 0 and height > 0 then
        return x / width, y / height
    end
    return nil, nil
end

local function containerFrames()
    -- 0.9.48 (live 2026-10-04): Retail 12 bag buttons live in pooled item
    -- frames (and ContainerFrameCombinedBags); the old global
    -- ContainerFrameNItemM names gave the Re-Sizer quest item no coordinate.
    local frames = {}
    if _G.ContainerFrameCombinedBags then frames[#frames + 1] = _G.ContainerFrameCombinedBags end
    for frameIndex = 1, 13 do
        local frame = _G["ContainerFrame" .. frameIndex]
        if frame then frames[#frames + 1] = frame end
    end
    return frames
end

local function inventoryButtonPoint(bag, slot)
    for _, frame in ipairs(containerFrames()) do
        if bool(safeCall(frame.IsVisible, frame)) and type(frame.EnumerateValidItems) == "function" then
            local ok, iterator, state, initial = pcall(frame.EnumerateValidItems, frame)
            if ok and type(iterator) == "function" then
                for _, button in iterator, state, initial do
                    if type(button) == "table" and bool(safeCall(button.IsVisible, button)) then
                        local buttonBag = button.GetBagID and safeCall(button.GetBagID, button) or nil
                        local buttonSlot = button.GetID and safeCall(button.GetID, button) or nil
                        if safeNumber(buttonBag, -99) == bag and safeNumber(buttonSlot, -99) == slot then
                            local x, y = buttonScreenPoint(button)
                            if x and y then return x, y end
                        end
                    end
                end
            end
        end
    end
    for frameIndex = 1, 13 do
        for buttonIndex = 1, 36 do
            local button = _G["ContainerFrame" .. frameIndex .. "Item" .. buttonIndex]
            if button and bool(safeCall(button.IsVisible, button)) then
                local buttonBag = button.GetBagID and safeCall(button.GetBagID, button) or nil
                local buttonSlot = button.GetID and safeCall(button.GetID, button) or nil
                if safeNumber(buttonBag, -99) == bag and safeNumber(buttonSlot, -99) == slot then
                    local x, y = safeCall(button.GetCenter, button)
                    local width, height = safeCall(GetScreenWidth), safeCall(GetScreenHeight)
                    if accessible(x) and accessible(y) and x and y and width and height and width > 0 and height > 0 then
                        return x / width, y / height
                    end
                end
            end
        end
    end
    return nil, nil
end

local function bagsAreOpen()
    local combined = _G.ContainerFrameCombinedBags
    if combined and bool(safeCall(combined.IsVisible, combined)) then return true end
    for frameIndex = 1, 13 do
        local candidate = _G["ContainerFrame" .. frameIndex]
        if candidate and bool(safeCall(candidate.IsVisible, candidate)) then return true end
    end
    return false
end

local function readInventory()
    local result = { items = {}, total_slots = 0, free_slots = 0 }
    if not C_Container then return result end
    for bag = 0, 5 do
        local slots = safeNumber(safeCall(C_Container.GetContainerNumSlots, bag), 0)
        local free = safeNumber(safeCall(C_Container.GetContainerNumFreeSlots, bag), 0)
        result.total_slots = result.total_slots + slots
        result.free_slots = result.free_slots + free
        for slot = 1, slots do
            local info = safeCall(C_Container.GetContainerItemInfo, bag, slot)
            if type(info) == "table" then
                local itemID = safeNumber(info.itemID)
                local itemName, _, quality, itemLevel, _, itemType, _, maxStack, _, _, sellPrice = safeCall(GetItemInfo, itemID)
                local questInfo = C_Container.GetContainerItemQuestInfo and safeCall(C_Container.GetContainerItemQuestInfo, bag, slot) or nil
                local x, y = inventoryButtonPoint(bag, slot)
                result.items[#result.items + 1] = {
                    bag = bag, slot = slot, item_id = itemID,
                    item_name = safeText(itemName, ""), count = safeNumber(info.stackCount, 1),
                    quality = safeNumber(quality), item_level = safeNumber(itemLevel),
                    item_type = safeText(itemType, ""), max_stack = safeNumber(maxStack, 1),
                    sell_price = safeNumber(sellPrice),
                    is_quest_item = type(questInfo) == "table" and bool(questInfo.isQuestItem) or false,
                    is_locked = bool(info.isLocked),
                    is_equippable = bool(IsEquippableItem and safeCall(IsEquippableItem, itemID)),
                    x = x, y = y, coordinate_space = x and "CLIENT_BOTTOM_LEFT" or nil,
                }
            end
        end
    end
    return result
end

local function readControlBindings()
    local result = {}
    for _, action in ipairs({"MOVEFORWARD", "MOVEBACKWARD", "TURNLEFT", "TURNRIGHT", "STRAFELEFT", "STRAFERIGHT",
        "JUMP", "INTERACTTARGET", "TARGETNEARESTENEMY", "TOGGLEWORLDMAP", "TOGGLEQUESTLOG", "OPENALLBAGS",
        "EXTRAACTIONBUTTON1"}) do
        local primary, secondary = safeCall(GetBindingKey, action)
        result[action] = {primary=safeText(primary, ""), secondary=safeText(secondary, ""), source="GET_BINDING_KEY"}
    end
    return result
end

local function readPlayerMovement()
    local speed = safeNumber(safeCall(GetUnitSpeed, "player"), 0)
    return {
        speed = speed,
        moving = speed > 0,
        running = speed > 0 and not bool(safeCall(IsSwimming)) and not bool(safeCall(IsFlying)),
        flying = bool(safeCall(IsFlying)),
        swimming = bool(safeCall(IsSwimming)),
        falling = bool(safeCall(IsFalling)),
        indoors = bool(safeCall(IsIndoors)),
    }
end

local function headerMatch(haystack, needle)
    if not accessible(haystack) or not accessible(needle) then return false end
    local h = string.lower(tostring(haystack))
    local n = string.lower(tostring(needle))
    if n == "" then return false end
    return h:find(n, 1, true) ~= nil or n:find(h, 1, true) ~= nil
end

local function questInCurrentZone(header, zoneName, subzoneName)
    if header == "" then return true end
    return headerMatch(header, zoneName) or (subzoneName ~= "" and headerMatch(header, subzoneName))
end

-- Convert an authoritative UI-map point into the world-coordinate system
-- used by UnitPosition and TrinityCore mmaps.  The API returns the instance
-- (called continentID by C_Map) separately from the Vector2D.  No Z value is
-- invented here; the navmesh owner projects the X/Y endpoint onto a walkable
-- polygon and remains responsible for floor/transition ambiguity.
local function mapToWorldPosition(mapID, mapX, mapY)
    mapID, mapX, mapY = optionalNumber(mapID), optionalNumber(mapX), optionalNumber(mapY)
    if not (mapID and mapX and mapY and mapX >= 0 and mapX <= 1 and mapY >= 0 and mapY <= 1) then return nil end
    if not (C_Map and C_Map.GetWorldPosFromMapPos and CreateVector2D) then return nil end
    local mapPosition = safeCall(CreateVector2D, mapX, mapY)
    if not mapPosition then return nil end
    local instanceID, worldPosition = safeCall(C_Map.GetWorldPosFromMapPos, mapID, mapPosition)
    instanceID = optionalNumber(instanceID)
    if not (instanceID and worldPosition and accessible(worldPosition)) then return nil end
    local worldX, worldY
    if type(worldPosition.GetXY) == "function" then
        worldX, worldY = safeCall(worldPosition.GetXY, worldPosition)
    else
        worldX, worldY = optionalNumber(worldPosition.x), optionalNumber(worldPosition.y)
    end
    worldX, worldY = optionalNumber(worldX), optionalNumber(worldY)
    if not (worldX and worldY) then return nil end
    return {
        x = worldX, y = worldY, instance_id = instanceID, ui_map_id = mapID,
        coordinate_space = "WORLD_YARDS", source = "C_MAP_WORLD_POS",
        z_known = false,
    }
end

local function mapWorldTransform(mapID)
    local origin = mapToWorldPosition(mapID, 0, 0)
    local xPoint = mapToWorldPosition(mapID, 1, 0)
    local yPoint = mapToWorldPosition(mapID, 0, 1)
    if not (origin and xPoint and yPoint
            and origin.instance_id == xPoint.instance_id
            and origin.instance_id == yPoint.instance_id) then return nil end
    return {
        ui_map_id = mapID, instance_id = origin.instance_id,
        coordinate_space = "NORMALIZED_MAP_TO_WORLD_YARDS",
        source = "C_MAP_WORLD_POS_AFFINE",
        origin = {x=origin.x, y=origin.y},
        x_axis = {x=xPoint.x-origin.x, y=xPoint.y-origin.y},
        y_axis = {x=yPoint.x-origin.x, y=yPoint.y-origin.y},
    }
end

-- Retail can return a syntactically valid UnitPosition("player") sample whose
-- X/Y stays frozen while C_Map.GetPlayerMapPosition continues to advance.  A
-- frozen world point breaks closed-loop mmap traversal: the controller keeps
-- steering towards the first corridor anchor forever.  Convert the *fresh*
-- player map sample through Blizzard's own map transform on every FAST_STATE
-- sample. Retail returned a frozen/zero player Z in live validation, so no
-- UnitPosition component is authoritative for player navigation here. The
-- mmap layer resolver projects this fresh X/Y onto a plausible walkable
-- surface and keeps that height explicitly estimated rather than observed.
local function currentPlayerWorldPosition(mapID, mapPosition, unitWorldPosition)
    local mapX = mapPosition and optionalNumber(mapPosition.x) or nil
    local mapY = mapPosition and optionalNumber(mapPosition.y) or nil
    local converted = mapToWorldPosition(mapID, mapX, mapY)
    if not converted then return unitWorldPosition end
    converted.source = "C_MAP_PLAYER_WORLD_POS"
    converted.z = nil
    converted.z_known = false
    converted.z_source = "NAVMESH_XY_PROJECTION_REQUIRED"
    return converted
end

-- Campaign status (user 2026-10-03: campaign quests always first).  The
-- former C_QuestLog.IsCampaignQuest does not exist on Retail 12, so active
-- quests never carried the flag; C_CampaignInfo and the 10.1.5+ quest
-- classification are the real sources.
local function questIsCampaign(questID)
    if not questID then return nil end
    if C_CampaignInfo and C_CampaignInfo.IsCampaignQuest then
        local value = safeCall(C_CampaignInfo.IsCampaignQuest, questID)
        if value ~= nil then return bool(value) end
    end
    if C_QuestInfoSystem and C_QuestInfoSystem.GetQuestClassification
            and Enum and Enum.QuestClassification and Enum.QuestClassification.Campaign then
        local classification = safeCall(C_QuestInfoSystem.GetQuestClassification, questID)
        if classification ~= nil then
            return classification == Enum.QuestClassification.Campaign
        end
    end
    return nil
end

-- 0.9.51 (user 2026-10-04): the local LLM objective interpreter needs the
-- quest's own words ("ride the boar and trample..."), not only the counter
-- lines.  Texts are captured when the client shows them (quest dialog) or
-- from the quest log, kept per character, and exported one quest per
-- snapshot so the multi-page transport does not grow with the log.
local questLogTextSeen = {}
local questLogTextUnreliable = false
local questTextCursor = 0

local function storedQuestTexts()
    AIPlayerControllerExportDB = AIPlayerControllerExportDB or {}
    AIPlayerControllerExportDB.quest_texts = AIPlayerControllerExportDB.quest_texts or {}
    return AIPlayerControllerExportDB.quest_texts
end

local function rememberQuestText(questID, field, text)
    questID = safeNumber(questID)
    if not questID or questID <= 0 or not accessible(text) or not text or text == "" then return end
    local store = storedQuestTexts()
    store[questID] = store[questID] or {}
    store[questID][field] = string.sub(safeText(text, ""), 1, 1200)
end

local function captureQuestLogText(questID, index)
    local entry = storedQuestTexts()[questID]
    if (entry and entry.description) or questLogTextUnreliable or not GetQuestLogQuestText then return end
    local description, objectivesText = safeCall(GetQuestLogQuestText, index)
    if not accessible(description) or not description or description == "" then return end
    for otherID, other in pairs(questLogTextSeen) do
        -- Same text for two quests: the API ignored the index (selected
        -- quest only); never attach one quest's text to another.
        if otherID ~= questID and other == description then
            questLogTextUnreliable = true
            return
        end
    end
    questLogTextSeen[questID] = description
    rememberQuestText(questID, "description", description)
    rememberQuestText(questID, "objectives_text", objectivesText)
end

local function readQuests()
    local quests = {}
    if not C_QuestLog or not C_QuestLog.GetNumQuestLogEntries then return quests end
    local zoneName = GetZoneText and safeText(GetZoneText(), "") or ""
    local subzoneName = GetSubZoneText and safeText(GetSubZoneText(), "") or ""
    local currentHeader = ""
    local entryCount = safeNumber(safeCall(C_QuestLog.GetNumQuestLogEntries), 0)
    for index = 1, entryCount do
        local info = safeCall(C_QuestLog.GetInfo, index)
        if info then
            if bool(info.isHeader) then
                currentHeader = accessible(info.title) and info.title or currentHeader
            end
        end
        local questID = info and safeNumber(info.questID) or 0
        if info and not bool(info.isHeader) and questID > 0 then
            captureQuestLogText(questID, index)
            local objectives = {}
            local hasWaypointObjective = false
            local specialItemLink = GetQuestLogSpecialItemInfo and safeCall(GetQuestLogSpecialItemInfo, index) or nil
            local specialItemID = accessible(specialItemLink) and tonumber(tostring(specialItemLink):match("item:(%d+)")) or nil
            local specialItemName = accessible(specialItemLink) and tostring(specialItemLink):match("%[(.-)%]") or nil
            local raw = C_QuestLog.GetQuestObjectives and safeCall(C_QuestLog.GetQuestObjectives, questID) or {}
            if type(raw) ~= "table" then raw = {} end
            for _, objective in ipairs(raw) do
                local objectiveText = safeText(objective.text, "")
                local normalizedType = normalizedObjectiveType(objective.type, objectiveText)
                -- Retail labels item-on-unit objectives as `monster` even
                -- when killing the unit is not the objective.  The quest-log
                -- special-item hyperlink is authoritative API evidence.  An
                -- exact item-name occurrence in the objective text is a
                -- narrow, quest-agnostic discriminator; keep raw_type so the
                -- Python evidence layer can still see the API classification.
                local specialItemReferenced = specialItemID and specialItemName
                    and string.lower(objectiveText):find(string.lower(specialItemName), 1, true) ~= nil
                if specialItemReferenced then normalizedType = "USE_ITEM" end
                objectives[#objectives + 1] = {
                    description = objectiveText,
                    raw_type = accessible(objective.type) and objective.type or nil,
                    type = normalizedType,
                    type_source = specialItemReferenced and "QUEST_SPECIAL_ITEM_NAME_MATCH" or "QUEST_API_NORMALIZATION",
                    item_id = normalizedType == "USE_ITEM" and specialItemID or nil,
                    current = safeNumber(objective.numFulfilled),
                    required = safeNumber(objective.numRequired, 1),
                    is_complete = bool(objective.finished),
                }
            end
            if #objectives == 0 and C_QuestLog.GetNextWaypointText then
                local waypointText = safeCall(C_QuestLog.GetNextWaypointText, questID)
                if accessible(waypointText) and waypointText and waypointText ~= "" then
                    local waypointMap, waypointX, waypointY
                    if C_QuestLog.GetNextWaypoint then waypointMap, waypointX, waypointY = safeCall(C_QuestLog.GetNextWaypoint, questID) end
                    local waypointWorld = mapToWorldPosition(waypointMap, waypointX, waypointY)
                    objectives[#objectives + 1] = {
                        description = waypointText,
                        type = objectiveType(waypointText),
                        current = 0,
                        required = 1,
                        is_complete = false,
                        map_id = safeNumber(waypointMap),
                        x = safeNumber(waypointX),
                        y = safeNumber(waypointY),
                        coordinate_space = "NORMALIZED_MAP",
                        world_position = waypointWorld,
                    }
                    hasWaypointObjective = true
                end
            end
            local waypointMap, waypointX, waypointY, waypointText
            if C_QuestLog.GetNextWaypoint then waypointMap, waypointX, waypointY = safeCall(C_QuestLog.GetNextWaypoint, questID) end
            if C_QuestLog.GetNextWaypointText then waypointText = safeCall(C_QuestLog.GetNextWaypointText, questID) end
            local readyForTurnIn = C_QuestLog.ReadyForTurnIn and safeCall(C_QuestLog.ReadyForTurnIn, questID)
            if readyForTurnIn == nil and C_QuestLog.IsComplete then readyForTurnIn = safeCall(C_QuestLog.IsComplete, questID) end
            local waypointWorld = mapToWorldPosition(waypointMap, waypointX, waypointY)
            quests[#quests + 1] = {
                quest_id = questID,
                title = safeText(info.title, ""),
                level = safeNumber(info.level),
                suggested_group = safeNumber(info.suggestedGroup),
                -- Campaign status is addon/API evidence, not an inferred
                -- title/marker classification. Unsupported client APIs simply
                -- yield nil, and the controller then refuses auto-continuation.
                is_campaign = questIsCampaign(questID),
                is_accepted = true,
                is_complete = optionalBool(readyForTurnIn),
                waypoint = waypointX and waypointY and {
                    map_id = safeNumber(waypointMap), x = safeNumber(waypointX), y = safeNumber(waypointY),
                    text = safeText(waypointText, ""), source = "QUEST_API", coordinate_space = "NORMALIZED_MAP",
                    world_position = waypointWorld,
                } or nil,
                objectives = objectives,
                special_item = specialItemID and {item_id = specialItemID, item_name = safeText(specialItemName, ""), source = "QUEST_LOG_SPECIAL_ITEM"} or nil,
            }
        end
    end
    return quests
end

local function readQuestText(quests)
    local active = {}
    for _, quest in ipairs(quests or {}) do
        if quest.quest_id and storedQuestTexts()[quest.quest_id] then active[#active + 1] = quest.quest_id end
    end
    if #active == 0 then return nil end
    questTextCursor = (questTextCursor % #active) + 1
    local questID = active[questTextCursor]
    local entry = storedQuestTexts()[questID]
    return {quest_id = questID, description = entry.description, objectives_text = entry.objectives_text,
            progress_text = entry.progress_text, completion_text = entry.completion_text,
            giver_name = entry.giver_name, giver_guid = entry.giver_guid, ender_name = entry.ender_name}
end

-- Map data APIs (not secret values): available quests ("!" givers),
-- dungeon/raid entrances, flight points and area POIs with world positions.
-- User 2026-10-01: find quest givers / entrances from the API instead of a
-- blind visual search.  Cached per map for 5 s; quest lines load async.
local mapPoiCache = {mapID = nil, at = -1000, data = nil}
local questLineRequestAt = {}

local function poiPosition(position)
    if not position or not accessible(position) then return nil, nil end
    local x, y
    if type(position.GetXY) == "function" then
        x, y = safeCall(position.GetXY, position)
    else
        x, y = position.x, position.y
    end
    return optionalNumber(x), optionalNumber(y)
end

local function poiMapChain(mapID)
    -- The current map plus parents up to (and including) the zone map;
    -- Enum.UIMapType: 3 Zone, 4 Dungeon, 5 Micro, 6 Orphan.
    local chain, seen = {}, {}
    local current = optionalNumber(mapID)
    while current and not seen[current] and #chain < 3 do
        seen[current] = true
        chain[#chain + 1] = current
        local info = C_Map and C_Map.GetMapInfo and safeCall(C_Map.GetMapInfo, current) or nil
        if not info or not accessible(info) then break end
        local mapType = optionalNumber(info.mapType)
        if not mapType or mapType <= 3 then break end
        current = optionalNumber(info.parentMapID)
    end
    return chain
end

local function readMapPOIs(mapID)
    local now = nowSeconds()
    if mapPoiCache.mapID == mapID and mapPoiCache.data and now - mapPoiCache.at < 5 then
        return mapPoiCache.data
    end
    local result = {available_quests = {}, dungeon_entrances = {}, taxi_nodes = {}, area_pois = {}}
    local seen = {}
    local function add(list, limit, key, record)
        if #list >= limit or seen[key] then return end
        seen[key] = true
        list[#list + 1] = record
    end
    for _, uiMapID in ipairs(poiMapChain(mapID)) do
        if C_QuestLine and C_QuestLine.RequestQuestLinesForMap
                and now - (questLineRequestAt[uiMapID] or -1000) > 15 then
            questLineRequestAt[uiMapID] = now
            safeCall(C_QuestLine.RequestQuestLinesForMap, uiMapID)
        end
        local lines = C_QuestLine and C_QuestLine.GetAvailableQuestLines
            and safeCall(C_QuestLine.GetAvailableQuestLines, uiMapID) or nil
        if type(lines) == "table" then
            for _, line in ipairs(lines) do
                if type(line) == "table" and accessible(line) then
                    local x, y = optionalNumber(line.x), optionalNumber(line.y)
                    local questID = optionalNumber(line.questID)
                    if x and y and questID and not bool(line.isHidden) then
                        add(result.available_quests, 25, "q" .. questID, {
                            quest_id = questID, quest_name = safeText(line.questName, ""),
                            quest_line_id = optionalNumber(line.questLineID),
                            map_id = uiMapID, x = x, y = y, coordinate_space = "NORMALIZED_MAP",
                            world_position = mapToWorldPosition(uiMapID, x, y),
                            is_campaign = optionalBool(line.isCampaign),
                            is_daily = optionalBool(line.isDaily),
                            is_important = optionalBool(line.isImportant),
                            source = "QUESTLINE_API",
                        })
                    end
                end
            end
        end
        local entrances = C_EncounterJournal and C_EncounterJournal.GetDungeonEntrancesForMap
            and safeCall(C_EncounterJournal.GetDungeonEntrancesForMap, uiMapID) or nil
        if type(entrances) == "table" then
            for _, entry in ipairs(entrances) do
                if type(entry) == "table" and accessible(entry) then
                    local x, y = poiPosition(entry.position)
                    local key = "e" .. tostring(optionalNumber(entry.journalInstanceID) or optionalNumber(entry.areaPoiID) or safeText(entry.name, ""))
                    if x and y then
                        add(result.dungeon_entrances, 10, key, {
                            name = safeText(entry.name, ""), atlas_name = safeText(entry.atlasName, ""),
                            journal_instance_id = optionalNumber(entry.journalInstanceID),
                            area_poi_id = optionalNumber(entry.areaPoiID),
                            map_id = uiMapID, x = x, y = y, coordinate_space = "NORMALIZED_MAP",
                            world_position = mapToWorldPosition(uiMapID, x, y),
                            source = "ENCOUNTER_JOURNAL_API",
                        })
                    end
                end
            end
        end
        local taxi = C_TaxiMap and C_TaxiMap.GetTaxiNodesForMap
            and safeCall(C_TaxiMap.GetTaxiNodesForMap, uiMapID) or nil
        if type(taxi) == "table" then
            for _, node in ipairs(taxi) do
                if type(node) == "table" and accessible(node) then
                    local x, y = poiPosition(node.position)
                    local nodeID = optionalNumber(node.nodeID)
                    if x and y and nodeID then
                        add(result.taxi_nodes, 10, "t" .. nodeID, {
                            node_id = nodeID, name = safeText(node.name, ""),
                            atlas_name = safeText(node.atlasName, ""),
                            map_id = uiMapID, x = x, y = y, coordinate_space = "NORMALIZED_MAP",
                            world_position = mapToWorldPosition(uiMapID, x, y),
                            source = "TAXI_MAP_API",
                        })
                    end
                end
            end
        end
        local poiIDs = C_AreaPoiInfo and C_AreaPoiInfo.GetAreaPOIsForMap
            and safeCall(C_AreaPoiInfo.GetAreaPOIsForMap, uiMapID) or nil
        if type(poiIDs) == "table" and C_AreaPoiInfo.GetAreaPOIInfo then
            for _, poiID in ipairs(poiIDs) do
                local info = safeCall(C_AreaPoiInfo.GetAreaPOIInfo, uiMapID, poiID)
                if type(info) == "table" and accessible(info) then
                    local x, y = poiPosition(info.position)
                    local id = optionalNumber(info.areaPoiID) or optionalNumber(poiID)
                    if x and y and id then
                        add(result.area_pois, 15, "a" .. id, {
                            area_poi_id = id, name = safeText(info.name, ""),
                            atlas_name = safeText(info.atlasName, ""),
                            map_id = uiMapID, x = x, y = y, coordinate_space = "NORMALIZED_MAP",
                            world_position = mapToWorldPosition(uiMapID, x, y),
                            source = "AREA_POI_API",
                        })
                    end
                end
            end
        end
    end
    mapPoiCache = {mapID = mapID, at = now, data = result}
    return result
end

local function readQuestLocations(mapID)
    local result = {}
    if not mapID then return result end
    local function append(entries, source)
        if type(entries) ~= "table" then return end
        for _, entry in ipairs(entries) do
            if type(entry) == "table" then
                local rawQuestID = accessible(entry.questID) and entry.questID or (accessible(entry.questId) and entry.questId or nil)
                local questID = optionalNumber(rawQuestID)
                local x, y = optionalNumber(entry.x), optionalNumber(entry.y)
                if questID and x and y then
                    local worldPosition = mapToWorldPosition(mapID, x, y)
                    result[#result + 1] = {
                        quest_id = questID, map_id = mapID, x = x, y = y,
                        source = source, coordinate_space = "NORMALIZED_MAP",
                        world_position = worldPosition,
                        in_progress = optionalBool(entry.inProgress),
                    }
                end
            end
        end
    end
    if C_QuestLog and C_QuestLog.GetQuestsOnMap then append(safeCall(C_QuestLog.GetQuestsOnMap, mapID), "QUEST_POI") end
    if C_TaskQuest and C_TaskQuest.GetQuestsOnMap then append(safeCall(C_TaskQuest.GetQuestsOnMap, mapID), "TASK_QUEST_POI") end
    return result
end

local function frameIsShown(candidate)
    if not candidate then return false end
    -- IsShown() only reports the frame's own shown flag.  A child can still
    -- return true while an ancestor hides it, which produced a permanent
    -- quest_ui.open=true on Retail and disabled World3D perception.  IsVisible
    -- includes the parent chain and is therefore authoritative when present.
    if candidate.IsVisible then
        return bool(safeCall(candidate.IsVisible, candidate))
    end
    return bool(candidate.IsShown and safeCall(candidate.IsShown, candidate))
end

local function framePoint(candidate)
    if not candidate or not candidate.GetCenter then return nil, nil end
    if not frameIsShown(candidate) then return nil, nil end
    local x, y = safeCall(candidate.GetCenter, candidate)
    if not accessible(x) or not accessible(y) or not x or not y then return nil, nil end
    local width = (_G.UIParent and optionalNumber(safeCall(_G.UIParent.GetWidth, _G.UIParent))) or
                  optionalNumber(safeCall(GetScreenWidth))
    local height = (_G.UIParent and optionalNumber(safeCall(_G.UIParent.GetHeight, _G.UIParent))) or
                   optionalNumber(safeCall(GetScreenHeight))
    if not width or not height or width <= 0 or height <= 0 then return nil, nil end
    return x / width, y / height
end

-- 0.9.45 (user 2026-10-03): death recovery.  Read-only: the visible death
-- popup's confirm button (Release Spirit / Resurrect Now) as a click point,
-- and the corpse position from C_DeathInfo.  Python clicks the button only
-- while the player is dead/a ghost and the popup kind matches.
local DEATH_POPUPS = {DEATH = "RELEASE_SPIRIT", RECOVER_CORPSE = "RECOVER_CORPSE"}

local function readDeathRecovery()
    local result = {popup = "", x = nil, y = nil, enabled = nil, corpse = nil,
                    recovery_delay = nil}
    for index = 1, 4 do
        local popup = _G["StaticPopup" .. index]
        if popup and frameIsShown(popup) then
            local which = popup.which
            if accessible(which) and type(which) == "string" and DEATH_POPUPS[which] then
                local button = _G["StaticPopup" .. index .. "Button1"] or popup.button1 or
                    (popup.ButtonContainer and popup.ButtonContainer.Button1)
                local x, y = framePoint(button)
                if x and y then
                    result.popup, result.x, result.y = DEATH_POPUPS[which], x, y
                    result.enabled = not button.IsEnabled or bool(safeCall(button.IsEnabled, button))
                    break
                end
            end
        end
    end
    local mapID = C_Map and C_Map.GetBestMapForUnit and safeCall(C_Map.GetBestMapForUnit, "player")
    if mapID and C_DeathInfo and C_DeathInfo.GetCorpseMapPosition then
        local position = safeCall(C_DeathInfo.GetCorpseMapPosition, mapID)
        if position and accessible(position) then
            local cx, cy
            if type(position.GetXY) == "function" then
                cx, cy = safeCall(position.GetXY, position)
            else
                cx, cy = position.x, position.y
            end
            cx, cy = optionalNumber(cx), optionalNumber(cy)
            if cx and cy and (cx > 0 or cy > 0) then
                result.corpse = {x = cx, y = cy, map_id = mapID, coordinate_space = "NORMALIZED_MAP",
                                 world_position = mapToWorldPosition(mapID, cx, cy)}
            end
        end
    end
    if GetCorpseRecoveryDelay then
        result.recovery_delay = optionalNumber(safeCall(GetCorpseRecoveryDelay))
    end
    return result
end

local function readExtraAction()
    -- This is a pure UI/control observation. It deliberately exports the
    -- client action token rather than inventing a key; Python can act only if
    -- the selected binding cache independently contains that exact token.
    local button = _G.ExtraActionButton1
    local visible = frameIsShown(button)
    local enabled = button and (not button.IsEnabled or safeCall(button.IsEnabled, button))
    local x, y = framePoint(button)
    local primary, secondary = safeCall(GetBindingKey, "EXTRAACTIONBUTTON1")
    -- ``ExtraActionButton1.action`` is the client's action slot, not a
    -- guessed spell or item. Resolve its published action identity when the
    -- API permits it so the controller can require an exact quest-item match.
    local slot = button and optionalNumber(button.action) or nil
    local actionType, actionID
    if slot then
        if C_ActionBar and C_ActionBar.GetActionInfo then
            local info, legacyID = safeCall(C_ActionBar.GetActionInfo, slot)
            if type(info) == "table" then actionType, actionID = info.actionType, info.id
            else actionType, actionID = info, legacyID end
        elseif GetActionInfo then
            actionType, actionID = safeCall(GetActionInfo, slot)
        end
    end
    return {
        visible = visible,
        -- Unknown/secret enabled state is deliberately not usable evidence.
        usable = visible and enabled == true,
        action = "EXTRAACTIONBUTTON1",
        action_slot = slot or 0,
        action_type = safeText(actionType, ""),
        action_id = optionalNumber(actionID),
        binding_primary = safeText(primary, ""),
        binding_secondary = safeText(secondary, ""),
        x = x or 0, y = y or 0,
    }
end

local function targetScreenPosition()
    if not C_NamePlate or not C_NamePlate.GetNamePlateForUnit then return nil end
    local plate = safeCall(C_NamePlate.GetNamePlateForUnit, "target")
    if not accessible(plate) or not plate then return nil end
    if plate.IsForbidden and bool(safeCall(plate.IsForbidden, plate)) then return nil end
    local x,y = framePoint(plate)
    if not x or not y or x <= 0 or x >= 1 or y <= 0 or y >= 1 then return nil end
    return {x=x,y=y,source="NAMEPLATE_API",coordinate_space="CLIENT_BOTTOM_LEFT",sample_time=nowSeconds()}
end

local function normalizedQuestRowText(value)
    if not accessible(value) or type(value) ~= "string" then return "" end
    local text = safeText(value, "")
    text = text:gsub("|c%x%x%x%x%x%x%x%x", ""):gsub("|r", ""):gsub("|T.-|t", "")
    return text:gsub("^%s+", ""):gsub("%s+$", ""):gsub("%s+", " ")
end

local function questRowPoint(questID, title)
    local foundX, foundY
    local wantedID = optionalNumber(questID)
    local wantedTitle = normalizedQuestRowText(title)
    local function dataMatches(value, depth, seen)
        if not accessible(value) or type(value) ~= "table" or depth > 4 or seen[value] then return false end
        seen[value] = true
        local directID = optionalNumber(value.questID or value.questId)
        if wantedID and directID == wantedID then return true end
        local directTitle = normalizedQuestRowText(value.title or value.name or value.text)
        if wantedTitle ~= "" and directTitle == wantedTitle then return true end
        local matched = false
        pcall(function()
            local inspected = 0
            for _, nested in pairs(value) do
                inspected = inspected + 1
                if inspected > 32 then break end
                if type(nested) == "table" and dataMatches(nested, depth + 1, seen) then
                    matched = true
                    break
                end
            end
        end)
        return matched
    end
    local function frameTextMatches(candidate)
        local function matches(value)
            return wantedTitle ~= "" and normalizedQuestRowText(value) == wantedTitle
        end
        if candidate.GetText and matches(safeCall(candidate.GetText, candidate)) then return true end
        if candidate.Text and candidate.Text.GetText
           and matches(safeCall(candidate.Text.GetText, candidate.Text)) then return true end
        local matched = false
        if candidate.GetRegions then
            pcall(function()
                for _, region in ipairs({candidate:GetRegions()}) do
                    if region and region.GetText and matches(safeCall(region.GetText, region)) then
                        matched = true
                        break
                    end
                end
            end)
        end
        return matched
    end
    local function inspect(candidate)
        if foundX or not candidate or not frameIsShown(candidate) then return end
        local data = candidate.GetElementData and safeCall(candidate.GetElementData, candidate) or nil
        local candidateID = optionalNumber(candidate.questID or candidate.questId)
        if (wantedID and candidateID == wantedID)
           or dataMatches(data, 0, {}) or frameTextMatches(candidate) then
            foundX, foundY = framePoint(candidate)
        end
    end
    local scrollBoxes = {}
    local gossipScroll = _G.GossipFrame and _G.GossipFrame.GreetingPanel and _G.GossipFrame.GreetingPanel.ScrollBox
    local greetingScroll = _G.QuestFrameGreetingPanel and _G.QuestFrameGreetingPanel.ScrollBox
    if gossipScroll then scrollBoxes[#scrollBoxes + 1] = gossipScroll end
    if greetingScroll then scrollBoxes[#scrollBoxes + 1] = greetingScroll end
    for _, scrollBox in ipairs(scrollBoxes) do
        if scrollBox and scrollBox.ForEachFrame then pcall(function() scrollBox:ForEachFrame(inspect) end) end
    end
    if foundX then return foundX, foundY end
    local roots = {}
    if _G.GossipFrame then roots[#roots + 1] = _G.GossipFrame end
    if _G.QuestFrameGreetingPanel then roots[#roots + 1] = _G.QuestFrameGreetingPanel end
    local function walk(frameToWalk, depth)
        if foundX or not frameToWalk or depth > 8 then return end
        inspect(frameToWalk)
        if frameToWalk.GetChildren then
            for _, child in ipairs({frameToWalk:GetChildren()}) do walk(child, depth + 1) end
        end
    end
    for _, root in ipairs(roots) do walk(root, 0) end
    return foundX, foundY
end

local function rewardChoiceFrame(index)
    -- Retail's quest-info item widgets retain these stable global names. The
    -- lookup is deliberately optional: if a UI revision changes the widget
    -- tree, no coordinate is exported and the controller fails closed rather
    -- than guessing a reward click from an item index alone.
    -- 0.9.46: Retail 12 keeps the choice buttons in
    -- QuestInfoRewardsFrame.RewardButtons (live 2026-10-04: the old global
    -- names exported x=0,y=0 for every choice).
    local rewards = _G.QuestInfoRewardsFrame
    local pooled = rewards and type(rewards.RewardButtons) == "table" and rewards.RewardButtons[index] or nil
    return pooled or _G["QuestInfoRewardsFrameQuestInfoItem" .. tostring(index)]
        or _G["QuestInfoItem" .. tostring(index)] or _G["QuestInfoReward" .. tostring(index)]
end

-- 0.9.54 (live 2026-10-04): Retail 12 reward buttons are not CheckButtons
-- (no GetChecked) and never report PUSHED, so a successful reward click was
-- invisible: reward_selected_index stayed 0, Complete Quest stayed hidden and
-- the agent re-clicked the reward until its retry budget ran out.  Blizzard's
-- QuestInfoItem_OnClick stores the chosen index in QuestInfoFrame.itemChoice
-- (the value the Complete button hands to GetQuestReward); the item highlight
-- anchored to a button is the fallback.
local function chosenRewardIndex()
    local ok, value = pcall(function()
        local info = _G.QuestInfoFrame
        return info and info.itemChoice
    end)
    local index = ok and optionalNumber(value) or nil
    if index and index > 0 then return index end
    return nil
end

local function highlightedRewardButton()
    local rewards = _G.QuestInfoRewardsFrame
    local highlight = (rewards and rewards.ItemHighlight) or _G.QuestInfoItemHighlight
    if not highlight or not frameIsShown(highlight) or not highlight.GetPoint then return nil end
    local ok, _, relative = pcall(highlight.GetPoint, highlight, 1)
    if ok and relative and accessible(relative) then return relative end
    return nil
end

local function rewardChoiceUnresolved()
    local count = optionalNumber(safeCall(GetNumQuestChoices)) or 0
    return count > 1 and chosenRewardIndex() == nil and highlightedRewardButton() == nil
end

local function readQuestRewardChoices()
    local result = {}
    local count = optionalNumber(safeCall(GetNumQuestChoices)) or 0
    local chosen = chosenRewardIndex()
    local highlighted = highlightedRewardButton()
    for index = 1, math.min(count, 8) do
        local name, _, quantity, quality, usable, itemID, itemLevel =
            safeCall(GetQuestItemInfo, "choice", index)
        local button = rewardChoiceFrame(index)
        local x, y = framePoint(button)
        local selected = nil
        if button and button.GetChecked then selected = optionalBool(safeCall(button.GetChecked, button)) end
        if selected == nil and button and button.GetButtonState then
            local state = safeCall(button.GetButtonState, button)
            if accessible(state) and state == "PUSHED" then selected = true end
        end
        if chosen then
            selected = chosen == index
        elseif selected == nil and highlighted and button and highlighted == button then
            selected = true
        end
        -- 0.9.53 (live 2026-10-04): GetQuestItemInfo gave no item level, so
        -- the reward choice stalled.  The item link carries level, vendor
        -- price and slot for the agent's deterministic AUTO choice.
        local link = GetQuestItemLink and safeCall(GetQuestItemLink, "choice", index) or nil
        local linkLevel, sellPrice, equipLoc, classID, subclassID
        if accessible(link) and link then
            if C_Item and C_Item.GetDetailedItemLevelInfo then
                linkLevel = safeCall(C_Item.GetDetailedItemLevelInfo, link)
            end
            local getInfo = (C_Item and C_Item.GetItemInfo) or GetItemInfo
            if getInfo then
                local info = {safeCall(getInfo, link)}
                sellPrice, equipLoc, classID, subclassID = info[11], info[9], info[12], info[13]
            end
        end
        result[#result + 1] = {
            index = index, item_id = optionalNumber(itemID), name = safeText(name, ""),
            quantity = optionalNumber(quantity), quality = optionalNumber(quality),
            item_level = optionalNumber(itemLevel) or optionalNumber(linkLevel),
            sell_price = optionalNumber(sellPrice),
            equip_loc = accessible(equipLoc) and safeText(equipLoc, "") or nil,
            item_class_id = optionalNumber(classID), item_subclass_id = optionalNumber(subclassID),
            is_usable = optionalBool(usable),
            x = x or 0, y = y or 0, selected = selected,
        }
    end
    return result
end

local function readVendorUI()
    local result = {open = false, npc_name = nil, npc_guid = nil, can_repair = false,
                    repair_all_cost = 0, repair_x = nil, repair_y = nil, items = {}}
    result.open = bool(_G.MerchantFrame and safeCall(_G.MerchantFrame.IsVisible, _G.MerchantFrame))
    if not result.open then return result end
    result.npc_name = safeText(safeCall(UnitName, "npc"), nil)
    result.npc_guid = safeCall(UnitGUID, "npc")
    if CanMerchantRepair and bool(safeCall(CanMerchantRepair)) then
        result.can_repair = true
        result.repair_all_cost = optionalNumber(GetRepairAllCost and safeCall(GetRepairAllCost)) or 0
        local repairButton = _G.MerchantRepairAllButton
        if repairButton then
            local rx, ry = framePoint(repairButton)
            result.repair_x, result.repair_y = rx, ry
        end
    end
    local numItems = optionalNumber(GetMerchantNumItems and safeCall(GetMerchantNumItems)) or 0
    for i = 1, math.min(numItems, 12) do
        local name, _, price, stackCount, numAvailable, isPurchasable, isUsable, extendedCost =
            safeCall(GetMerchantItemInfo, i)
        if accessible(name) and name then
            local button = _G["MerchantItem" .. i .. "ItemButton"]
            local bx, by
            if button then bx, by = framePoint(button) end
            result.items[#result.items + 1] = {
                slot = i, name = safeText(name, ""), price = optionalNumber(price) or 0,
                item_id = optionalNumber(GetMerchantItemLink and tonumber((safeText(safeCall(GetMerchantItemLink, i), ""):match("item:(%d+)")))),
                stack_count = optionalNumber(stackCount) or 1,
                num_available = optionalNumber(numAvailable) or -1,
                is_purchasable = bool(isPurchasable), is_usable = bool(isUsable),
                extended_cost = bool(extendedCost), x = bx, y = by,
            }
        end
    end
    return result
end

local function readQuestUI()
    local result = {open = false, entries = {}, reward_choices = {}, reward_selected_index = 0,
                    action = "", x = 0, y = 0, quest_id = 0}
    result.open = frameIsShown(_G.GossipFrame) or frameIsShown(_G.QuestFrame)
    -- QUEST_DETAIL tells us which action is expected, but it is not proof
    -- that the dialog is still on screen.  In live testing the player could
    -- walk past an NPC, Retail closed QuestFrame, and this ten-second hint
    -- kept exporting `open=true` with an old Accept coordinate.  Python then
    -- waited/clicked a dialog that no longer existed.  Keep the hint only as
    -- a label for a *currently visible* UI; button visibility remains the
    -- authoritative action and coordinate source.
    if result.open and questUIHint.open and nowSeconds() - questUIHint.observed_at <= 10 then
        result.action = questUIHint.action
    end
    if C_GossipInfo then
        local available = C_GossipInfo.GetAvailableQuests and C_GossipInfo.GetAvailableQuests() or {}
        for _, quest in ipairs(available) do
            local questID = safeNumber(quest.questID or quest.questId)
            local title = safeText(quest.title, "")
            local x, y = questRowPoint(questID, title)
            result.entries[#result.entries + 1] = {
                kind = "AVAILABLE", quest_id = questID, title = title,
                x = x or 0, y = y or 0, acceptable = true,
            }
        end
        local active = C_GossipInfo.GetActiveQuests and C_GossipInfo.GetActiveQuests() or {}
        for _, quest in ipairs(active) do
            if bool(quest.isComplete) then
                local questID = safeNumber(quest.questID or quest.questId)
                local title = safeText(quest.title, "")
                local x, y = questRowPoint(questID, title)
                result.entries[#result.entries + 1] = {
                    kind = "COMPLETE", quest_id = questID, title = title,
                    x = x or 0, y = y or 0, acceptable = true,
                }
            end
        end
    end
    -- Quest givers without gossip list several quests on QuestFrame's
    -- greeting panel (QUEST_GREETING) instead; C_GossipInfo is empty there.
    -- User 2026-10-03: take every offered quest, one after the other.
    if #result.entries == 0 and frameIsShown(_G.QuestFrameGreetingPanel) then
        local available = optionalNumber(safeCall(GetNumAvailableQuests)) or 0
        for index = 1, math.min(available, 16) do
            local title = safeText(safeCall(GetAvailableTitle, index), "")
            local _, _, _, _, questID = safeCall(GetAvailableQuestInfo, index)
            questID = optionalNumber(questID)
            local x, y = questRowPoint(questID, title)
            if questID then
                result.entries[#result.entries + 1] = {
                    kind = "AVAILABLE", quest_id = questID, title = title,
                    x = x or 0, y = y or 0, acceptable = true,
                }
            end
        end
        local activeCount = optionalNumber(safeCall(GetNumActiveQuests)) or 0
        for index = 1, math.min(activeCount, 16) do
            local title, isComplete = safeCall(GetActiveTitle, index)
            local questID = optionalNumber(safeCall(GetActiveQuestID, index))
            if questID and bool(isComplete) then
                title = safeText(title, "")
                local x, y = questRowPoint(questID, title)
                result.entries[#result.entries + 1] = {
                    kind = "COMPLETE", quest_id = questID, title = title,
                    x = x or 0, y = y or 0, acceptable = true,
                }
            end
        end
    end
    local acceptVisible = frameIsShown(_G.QuestFrameAcceptButton)
    local completeVisible = frameIsShown(_G.QuestFrameCompleteQuestButton)
    -- GetNumQuestChoices() is not, by itself, proof of a selectable reward
    -- dialog. Retail can expose the reward preview while QUEST_DETAIL and the
    -- Accept button are on screen (observed live with a single preview item).
    -- Only interpret choices inside the completion/turn-in UI. The explicit
    -- Accept button always wins over a stale completion hint.
    local rewardContext = result.open and not acceptVisible and
        (completeVisible or result.action == "COMPLETE")
    if rewardContext then
        result.reward_choices = readQuestRewardChoices()
    end
    for _, choice in ipairs(result.reward_choices) do
        if choice.selected == true then result.reward_selected_index = choice.index; break end
    end
    -- Selecting an item and completing the quest are separate client actions.
    -- Do not expose Complete while a choice is still unresolved; the Python
    -- policy must select an explicit exported choice first.
    -- 0.9.46 (live 2026-10-04): a single reward is not a choice -- the
    -- client hands it out on Complete Quest; waiting for a selection hid the
    -- Complete button and the agent stood at the reward frame.
    if rewardContext and #result.reward_choices > 1 and result.reward_selected_index == 0 then
        result.action = "REWARD_SELECT"
        result.quest_id = safeNumber(GetQuestID and safeCall(GetQuestID), 0)
        result.open = true
        return result
    end
    local buttons = {
        {"ACCEPT", _G.QuestFrameAcceptButton},
        {"CONTINUE", _G.QuestFrameCompleteButton},
        {"COMPLETE", _G.QuestFrameCompleteQuestButton},
    }
    for _, candidate in ipairs(buttons) do
        local button = candidate[2]
        local enabled = button and (not button.IsEnabled or safeCall(button.IsEnabled, button))
        if button and frameIsShown(button) and enabled ~= false then
            local x, y = framePoint(button)
            if x and y then
                result.action, result.x, result.y = candidate[1], x, y
                local questID = GetQuestID and GetQuestID() or 0
                result.quest_id = safeNumber(questID)
                result.open = true
                break
            end
        end
    end
    return result
end

-- PREPARED 2026-09-14, UNTESTED LIVE. Same fast-lane-hint shape as
-- readFastQuestUI() below, for the same reason: verify()'s COMBAT/DEFEND
-- branch otherwise only sees a landed spell cast via the slow/paged
-- `events` list, which this session's own telemetry showed arriving
-- several seconds late -- COMBAT's SkillContract timeout was raised to 8s
-- to compensate (skills.py), but a fast-lane confirmation removes the wait
-- almost entirely instead of just tolerating it.
local function readFastCombatHint()
    local result = {spell_id = 0, at = 0}
    if combatHint.spell_id ~= 0 and nowSeconds() - combatHint.at <= 10 then
        result.spell_id = combatHint.spell_id
        result.at = combatHint.at
    end
    return result
end

-- Cheap control-lane projection. It deliberately skips gossip-row traversal,
-- quest-log enumeration and text extraction; the slow snapshot owns those.
-- Direct named buttons plus authoritative quest UI events are enough to stop
-- movement/map fallback immediately and expose a verified click point.
local function readFastQuestUI()
    local result = {open = false, action = "", x = 0, y = 0, quest_id = 0}
    -- Do not turn a past QUEST_DETAIL event into a synthetic, still-open
    -- dialog.  A fast packet must be able to stop movement when the real UI
    -- opens, but must also report closed immediately when range/movement
    -- closes it.
    result.open = frameIsShown(_G.GossipFrame) or frameIsShown(_G.QuestFrame)
    result.action = result.open and questUIHint.action or ""
    local buttons = {
        {"ACCEPT", _G.QuestFrameAcceptButton},
        {"CONTINUE", _G.QuestFrameCompleteButton},
        {"COMPLETE", _G.QuestFrameCompleteQuestButton},
    }
    for _, candidate in ipairs(buttons) do
        local button = candidate[2]
        local enabled = button and (not button.IsEnabled or safeCall(button.IsEnabled, button))
        if button and frameIsShown(button) and enabled ~= false then
            result.open = true
            local x, y = framePoint(button)
            if candidate[1] == "COMPLETE" and rewardChoiceUnresolved() then
                result.action, result.x, result.y = "REWARD_SELECT", 0, 0
                result.quest_id = safeNumber(GetQuestID and safeCall(GetQuestID), 0)
            elseif x and y then
                result.action, result.x, result.y = candidate[1], x, y
                result.quest_id = safeNumber(GetQuestID and safeCall(GetQuestID), 0)
            end
            break
        end
    end
    return result
end

local function readTutorialHint()
    if not EnumerateFrames then return "" end
    local candidate = EnumerateFrames()
    local inspected = 0
    while candidate and inspected < 2000 do
        inspected = inspected + 1
        local visibleOk, visible = pcall(function() return candidate:IsVisible() end)
        if visibleOk and visible and candidate.GetRegions then
            local regionsOk, regions = pcall(function() return {candidate:GetRegions()} end)
            if regionsOk then
                for _, region in ipairs(regions) do
                    local textOk, text = pcall(function()
                        if region.IsObjectType and region:IsObjectType("FontString") and region:IsVisible() then
                            return region:GetText()
                        end
                    end)
                    if textOk and accessible(text) and type(text) == "string" and
                       string.lower(text):find("walk around", 1, true) then
                        return safeText(text, "")
                    end
                end
            end
        end
        candidate = EnumerateFrames(candidate)
    end
    return ""
end

local function updateQuestRevision(quests)
    local parts = {}
    for _, quest in ipairs(quests) do
        parts[#parts + 1] = safeText(quest.quest_id, "0") .. ":" .. (quest.is_complete and "1" or "0")
        for _, objective in ipairs(quest.objectives) do
            parts[#parts + 1] = safeText(objective.current, "0") .. "/" .. safeText(objective.required, "1") .. ":" .. safeText(objective.description, "")
        end
    end
    local signature = table.concat(parts, ";")
    if signature ~= lastQuestSignature then
        lastQuestSignature = signature
        questRevision = questRevision + 1
    end
    return questRevision
end

local function worldToMap(mapID, wx, wy)
    if not (mapID and wx and wy) then return nil end
    local info = C_Map and C_Map.GetMapInfo and safeCall(C_Map.GetMapInfo, mapID)
    local rect = info and info.uiMapRectangle
    if not rect then return nil end
    local minX, minY, maxX, maxY = rect.minX, rect.minY, rect.maxX, rect.maxY
    if not (minX and maxX and minY and maxY) or maxX == minX or maxY == minY then return nil end
    local mx = (wx - minX) / (maxX - minX)
    local my = (wy - minY) / (maxY - minY)
    if mx < 0 or mx > 1 or my < 0 or my > 1 then return nil end
    return mx, my
end

-- Export the hierarchy that Retail itself reports for the currently usable
-- World Map level.  This is read-only context evidence: parent_map_id/name do
-- not claim that a quest marker exists there and never become navigation
-- coordinates.  The bounded chain prevents malformed API data from growing
-- the transport indefinitely.
local function readMapContext(playerMapID, displayedMapID)
    local mapOpen = _G.WorldMapFrame and
        bool(safeCall(_G.WorldMapFrame.IsShown, _G.WorldMapFrame)) or false
    local activeMapID = (mapOpen and displayedMapID) or playerMapID
    local result = {
        player_map_id = optionalNumber(playerMapID),
        displayed_map_id = optionalNumber(displayedMapID),
        active_map_id = optionalNumber(activeMapID),
        world_map_open = mapOpen,
        hierarchy = {},
    }
    local current, seen = activeMapID, {}
    for _ = 1, 4 do
        if not current or seen[current] then break end
        seen[current] = true
        local info = C_Map and C_Map.GetMapInfo and safeCall(C_Map.GetMapInfo, current)
        if not info then break end
        local parent = optionalNumber(info.parentMapID)
        result.hierarchy[#result.hierarchy + 1] = {
            map_id = optionalNumber(current),
            parent_map_id = parent,
            name = safeText(info.name, ""),
            map_type = optionalNumber(info.mapType),
        }
        if #result.hierarchy == 1 then
            result.map_name = safeText(info.name, "")
            result.map_type = optionalNumber(info.mapType)
            result.parent_map_id = parent
        end
        if not parent or parent == 0 then break end
        current = parent
    end
    if result.parent_map_id then
        local parentInfo = C_Map and C_Map.GetMapInfo and
            safeCall(C_Map.GetMapInfo, result.parent_map_id)
        result.parent_map_name = parentInfo and safeText(parentInfo.name, "") or ""
        result.parent_map_type = parentInfo and optionalNumber(parentInfo.mapType) or nil
    end
    return result
end

local function recordDeadTarget(data, mapID)
    if not (data.target and data.target.dead and data.target.guid) then return end
    local wx, wy = safeCall(UnitPosition, "target")
    if not (wx and wy) then return end
    local mx, my = worldToMap(mapID, wx, wy)
    if not mx then return end
    for _, c in ipairs(killedCorpses) do
        if c.guid == data.target.guid then
            c.x, c.y, c.at = mx, my, serverTimestamp()
            return
        end
    end
    killedCorpses[#killedCorpses + 1] = { guid = data.target.guid, x = mx, y = my, at = serverTimestamp() }
    local now = serverTimestamp()
    for i = #killedCorpses, 1, -1 do
        if now - (killedCorpses[i].at or 0) > 300 then table.remove(killedCorpses, i) end
    end
    while #killedCorpses > 6 do table.remove(killedCorpses, 1) end
end

local function guidType(guid)
    if not guid then return nil end
    local prefix = guid:match("^([^%-]+)")
    if prefix == "Player" then return "PLAYER" end
    if prefix == "Creature" then return "NPC" end
    if prefix == "Vehicle" then return "VEHICLE" end
    if prefix == "Pet" then return "PET" end
    if prefix == "GameObject" then return "OBJECT" end
    if prefix == "Item" then return "ITEM" end
    return prefix
end

local function npcIdFromGuid(guid)
    if not guid then return nil end
    local kind = guidType(guid)
    if kind == "PLAYER" or kind == "OBJECT" or kind == "ITEM" then return nil end
    local id = guid:match("^[^%-]+%-%d+%-%d+%-%d+%-%d+%-(%d+)%-%x+$")
    if id then return tonumber(id) end
    return nil
end

local function safeUnitCall(fn, unit, ...)
    if not fn or not unit or not unitExists(unit) then return nil end
    local ok, a, b, c, d, e = pcall(fn, unit, ...)
    if not ok then return nil end
    if not accessible(a) then a = nil end
    if not accessible(b) then b = nil end
    if not accessible(c) then c = nil end
    if not accessible(d) then d = nil end
    if not accessible(e) then e = nil end
    return a, b, c, d, e
end

local function readUnitType(unit, guid)
    local kind = guidType(guid)
    if bool(safeUnitCall(UnitIsPlayer, unit)) then return "PLAYER" end
    if kind == "PET" then return "PET" end
    if kind == "VEHICLE" then return "VEHICLE" end
    if kind == "NPC" then return "NPC" end
    local unitType = safeUnitCall(UnitCreatureType, unit)
    if unitType then return "NPC" end
    return kind
end

local function readCursorPosition()
    if not GetCursorPosition then return nil end
    local x, y = safeCall(GetCursorPosition)
    if not x or not y then return nil end
    local scale = UIParent and UIParent.GetEffectiveScale and safeCall(UIParent.GetEffectiveScale, UIParent) or 1
    if not scale or scale <= 0 then scale = 1 end
    x, y = x / scale, y / scale
    local width, height = safeCall(GetScreenWidth), safeCall(GetScreenHeight)
    if not width or not height or width <= 0 or height <= 0 then return nil end
    return { x = x, y = y, nx = x / width, ny = y / height }
end

local function readUnit(unit)
    if not unit or not unitExists(unit) then return nil end
    local guid = safeUnitCall(UnitGUID, unit)
    local name, realm = safeUnitCall(UnitName, unit)
    if (not name or name == "") and scanTooltip and scanTooltip.SetUnit then
        -- Force the same client-side resolution a real mouseover would
        -- trigger, then retry. Cheap: only runs when the name is already
        -- missing, and SetUnit never shows the tooltip since it is never
        -- anchored/shown to the player.
        safeCall(scanTooltip.SetUnit, scanTooltip, unit)
        name, realm = safeUnitCall(UnitName, unit)
    end
    local level = safeUnitCall(UnitLevel, unit)
    local classification = safeUnitCall(UnitClassification, unit)
    local creatureType = safeUnitCall(UnitCreatureType, unit)
    local creatureFamily = safeUnitCall(UnitCreatureFamily, unit)
    local reaction = safeUnitCall(UnitReaction, "player", unit)
    local isDead = safeUnitCall(UnitIsDead, unit)
    -- Live 2026-10-02: a right-click on an empty corpse opens nothing and
    -- shows no error.  CanLootUnit(guid) -> hasLoot, canLoot tells it apart.
    local lootable = nil
    if bool(isDead) and guid and CanLootUnit then
        local hasLoot, canLoot = safeCall(CanLootUnit, guid)
        if hasLoot ~= nil then lootable = bool(hasLoot) and canLoot ~= false end
    end
    local canAttack = safeUnitCall(UnitCanAttack, "player", unit)
    local isTapDenied = safeUnitCall(UnitIsTapDenied, unit)
    local isConnected = safeUnitCall(UnitIsConnected, unit)
    local isPlayer = safeUnitCall(UnitIsPlayer, unit)
    local unitType = readUnitType(unit, guid)
    local npcID = npcIdFromGuid(guid)
    local className, classToken
    if isPlayer and UnitClass then
        className, classToken = safeUnitCall(UnitClass, unit)
    end
    local reactionName = nil
    if reaction then
        if reaction >= 5 then reactionName = "friendly"
        elseif reaction >= 4 then reactionName = "neutral"
        else reactionName = "hostile" end
    elseif canAttack ~= nil then
        reactionName = canAttack and "hostile" or "friendly"
    end
    local health = safeUnitCall(UnitHealth, unit)
    local maxHealth = safeUnitCall(UnitHealthMax, unit)
    local x, y, z, instanceID = safeUnitCall(UnitPosition, unit)
    return {
        exists = true,
        unit = unit,
        name = name,
        realm = realm,
        guid = guid,
        npc_id = npcID,
        unit_type = unitType,
        level = level,
        classification = classification,
        creature_type = creatureType,
        creature_family = creatureFamily,
        reaction = reactionName,
        reaction_value = reaction,
        class_name = className,
        class_token = classToken,
        is_player = bool(isPlayer),
        is_dead = bool(isDead),
        lootable = lootable,
        is_attackable = optionalBool(canAttack),
        is_tap_denied = optionalBool(isTapDenied),
        is_connected = optionalBool(isConnected),
        health = health,
        max_health = maxHealth,
        world_position = x and y and {x = x, y = y, z = optionalNumber(z),
            instance_id = instanceID, source = "UNIT_POSITION",
            coordinate_space = "WORLD_YARDS", z_known = optionalNumber(z) ~= nil} or nil,
    }
end

-- Retail action-targeting unit tokens are read-only candidate hints. They do
-- not replace the selected target and must never be treated as confirmed
-- identity/role merely because the client currently highlights them.
local function readSoftTargets()
    local result = {}
    for _, unitToken in ipairs({"softenemy", "softfriend", "softinteract"}) do
        local unit = readUnit(unitToken)
        if unit then
            result[#result + 1] = {
                source_unit = unitToken,
                guid = unit.guid,
                npc_id = unit.npc_id,
                name = unit.name,
                unit_type = unit.unit_type,
                reaction = unit.reaction,
                is_attackable = unit.is_attackable,
                is_dead = unit.is_dead,
                world_position = unit.world_position,
                evidence_role = "CANDIDATE_HINT",
                confirmed = false,
            }
        end
    end
    return result
end

local function readNameplates()
    if not C_NamePlate or not C_NamePlate.GetNamePlates then return {} end
    local plates = safeCall(C_NamePlate.GetNamePlates)
    if not accessible(plates) or type(plates) ~= "table" then return {} end
    local result = {}
    for _, plate in ipairs(plates) do
        if accessible(plate) and plate then
            local unit = plate.namePlateUnitToken
            if accessible(unit) and unit and unitExists(unit) then
                local x, y = framePoint(plate)
                if x and y then
                    local guid = safeUnitCall(UnitGUID, unit)
                    local reaction = safeUnitCall(UnitReaction, "player", unit)
                    local canAttack = safeUnitCall(UnitCanAttack, "player", unit)
                    local reactionName = nil
                    if reaction then
                        if reaction >= 5 then reactionName = "friendly"
                        elseif reaction >= 4 then reactionName = "neutral"
                        else reactionName = "hostile" end
                    elseif canAttack ~= nil then
                        reactionName = canAttack and "hostile" or "friendly"
                    end
                    result[#result + 1] = {
                        unit = unit, name = safeUnitCall(UnitName, unit), guid = guid,
                        creature_type = safeUnitCall(UnitCreatureType, unit),
                        reaction = reactionName, nx = x, ny = y,
                    }
                end
            end
        end
    end
    return result
end

local function tooltipText()
    if not GameTooltip or not bool(safeCall(GameTooltip.IsShown, GameTooltip)) then return "" end
    local parts = {}
    for line = 1, 6 do
        local fontString = _G["GameTooltipTextLeft" .. line]
        local text = fontString and bool(safeCall(fontString.IsVisible, fontString)) and safeCall(fontString.GetText, fontString) or nil
        if accessible(text) and text and text ~= "" then
            parts[#parts + 1] = safeText(text, "")
        end
    end
    return table.concat(parts, " ~ ")
end

local function tooltipMetadata()
    if not GameTooltip or not GameTooltip.GetPrimaryTooltipData then return nil end
    local data = safeCall(GameTooltip.GetPrimaryTooltipData, GameTooltip)
    if type(data) ~= "table" then return nil end
    local rawType = accessible(data.type) and data.type or nil
    local result = {
        raw_type = safeNumber(rawType),
        id = safeNumber(data.id),
        guid = safeText(data.guid, ""),
        hyperlink = safeText(data.hyperlink, ""),
    }
    local lineParts = {}
    if type(data.lines) == "table" then
        for index = 1, math.min(6, #data.lines) do
            local line = data.lines[index]
            if type(line) == "table" then
                for _, field in ipairs({"leftText", "rightText"}) do
                    local value = line[field]
                    if accessible(value) and value and value ~= "" then
                        lineParts[#lineParts + 1] = safeText(value, "")
                    end
                end
            end
        end
    end
    result.structured_text = table.concat(lineParts, " ~ ")
    result.unit_name = lineParts[1]
    if rawType and Enum and Enum.TooltipDataType then
        if rawType == Enum.TooltipDataType.Quest then result.quest_id = safeNumber(data.id) end
        if rawType == Enum.TooltipDataType.Item then result.item_id = safeNumber(data.id) end
        if rawType == Enum.TooltipDataType.Spell then result.spell_id = safeNumber(data.id) end
        if rawType == Enum.TooltipDataType.Unit then
            result.unit_guid = safeText(data.guid, "")
            result.is_unit = true
        end
        if Enum.TooltipDataType.Object and rawType == Enum.TooltipDataType.Object then result.object_id = safeNumber(data.id) end
    end
    return result
end

local function activeQuestTooltipMatch(text, activeQuests)
    local value = string.lower(safeText(text, ""))
    if value == "" or type(activeQuests) ~= "table" then return false, nil end
    for _, quest in ipairs(activeQuests) do
        local title = string.lower(safeText(quest.title, ""))
        if title ~= "" and value:find(title, 1, true) then
            return true, safeNumber(quest.quest_id)
        end
    end
    return false, nil
end

local function readMouseover(activeQuests)
    local unit = readUnit("mouseover")
    local text = tooltipText()
    local metadata = tooltipMetadata()
    if text == "" and metadata and metadata.structured_text then
        text = metadata.structured_text
    end
    local identitySource = unit and "WOW_API_MOUSEOVER" or nil
    -- Retail can render a valid unit tooltip while UnitExists("mouseover") is
    -- temporarily unavailable to the addon.  Use the public tooltip unit token
    -- and structured primary-tooltip data as ordered fallbacks; never unwrap or
    -- stringify inaccessible/secret values.
    if not unit and GameTooltip and GameTooltip.GetUnit then
        local ok, _, tooltipUnit = pcall(GameTooltip.GetUnit, GameTooltip)
        if ok and accessible(tooltipUnit) and tooltipUnit then
            unit = readUnit(tooltipUnit)
            if unit then identitySource = "GAME_TOOLTIP_UNIT" end
        end
    end
    if not unit and metadata then
        local guid = safeText(metadata.unit_guid or metadata.guid, "")
        local unitName = safeText(metadata.unit_name, "")
        if guid ~= "" or (metadata.is_unit and unitName ~= "") then
            unit = {
                exists = true,
                guid = guid,
                npc_id = npcIdFromGuid(guid),
                name = unitName,
                unit_type = guid ~= "" and guidType(guid) or "UNIT",
                structured_unit = metadata.is_unit and true or nil,
            }
            identitySource = "TOOLTIP_PRIMARY_DATA"
        end
    end
    unit = unit or {}
    if not next(unit) and text == "" and not metadata then return nil end
    unit.tooltip = text
    unit.tooltip_data = metadata
    unit.identity_source = identitySource
    unit.item_id = metadata and metadata.item_id or nil
    unit.object_id = metadata and metadata.object_id or nil
    local questRelated, questID = activeQuestTooltipMatch(text, activeQuests)
    unit.quest_related = questRelated or nil
    unit.quest_id = questID
    return unit
end

local function classifyMapMouseoverTooltip(text)
    local value = string.lower(text or "")
    if value == "" then return "UNKNOWN" end
    if value:find("turn in") or value:find("turn-in") or value:find("complete quest") or value:find("quest complete") then
        return "QUEST_TURN_IN"
    end
    if value:find("quest giver") or value:find("available quest") or value:find("accept quest") then
        return "QUEST_GIVER"
    end
    if value:find("quest") then return "QUEST_RELATED" end
    return "UNKNOWN"
end

local function pointInside(frame, x, y)
    if not frame or not frame.IsShown or not bool(safeCall(frame.IsShown, frame)) or not frame.GetLeft then return false end
    local left = safeCall(frame.GetLeft, frame)
    local bottom = safeCall(frame.GetBottom, frame)
    local width = safeCall(frame.GetWidth, frame)
    local height = safeCall(frame.GetHeight, frame)
    if not accessible(left) or not accessible(bottom) or not accessible(width) or not accessible(height) then return false end
    if not left or not bottom or not width or not height then return false end
    return x >= left and x <= left + width and y >= bottom and y <= bottom + height
end

local function readMapMouseover()
    local cursor = readCursorPosition()
    if not cursor then return nil end
    local surface = nil
    local mapX, mapY = nil, nil
    local localX, localY = nil, nil
    local mapFrame = _G.WorldMapFrame
    local minimap = _G.Minimap
    if mapFrame and bool(safeCall(mapFrame.IsShown, mapFrame)) then
        local scroll = mapFrame.ScrollContainer
        local inScroll = scroll and pointInside(scroll, cursor.x, cursor.y) or false
        local inMap = inScroll or pointInside(mapFrame, cursor.x, cursor.y)
        if inMap then
            surface = "WORLD_MAP"
            if scroll and scroll.GetNormalizedCursorPosition then
                local ok, x, y = pcall(scroll.GetNormalizedCursorPosition, scroll)
                if ok and accessible(x) and accessible(y) and type(x) == "number" and type(y) == "number" and x >= 0 and x <= 1 and y >= 0 and y <= 1 then
                    mapX, mapY = x, y
                end
            end
            if mapX == nil and mapFrame.GetNormalizedCursorPosition then
                local ok, x, y = pcall(mapFrame.GetNormalizedCursorPosition, mapFrame)
                if ok and accessible(x) and accessible(y) and type(x) == "number" and type(y) == "number" and x >= 0 and x <= 1 and y >= 0 and y <= 1 then
                    mapX, mapY = x, y
                end
            end
        end
    end
    if not surface and minimap and minimap.IsShown and bool(safeCall(minimap.IsShown, minimap)) and pointInside(minimap, cursor.x, cursor.y) then
        surface = "MINIMAP"
        local left = safeCall(minimap.GetLeft, minimap)
        local bottom = safeCall(minimap.GetBottom, minimap)
        local width = safeCall(minimap.GetWidth, minimap)
        local height = safeCall(minimap.GetHeight, minimap)
        if left and bottom and width and height and width > 0 and height > 0 then
            localX = (cursor.x - left) / width
            localY = (cursor.y - bottom) / height
        end
    end
    if not surface then return nil end
    local text = tooltipText()
    local tooltipData = tooltipMetadata()
    local tooltipUnit = nil
    if GameTooltip and GameTooltip.GetUnit then
        local ok, _, unit = pcall(GameTooltip.GetUnit, GameTooltip)
        if ok and unit and unitExists(unit) then tooltipUnit = readUnit(unit) end
    end
    local displayedMapID = mapFrame and mapFrame.GetMapID and safeCall(mapFrame.GetMapID, mapFrame) or nil
    return {
        surface = surface,
        map_id = surface == "WORLD_MAP" and displayedMapID or (C_Map and C_Map.GetBestMapForUnit and safeCall(C_Map.GetBestMapForUnit, "player") or nil),
        x = mapX,
        y = mapY,
        local_x = localX,
        local_y = localY,
        cursor_x = cursor.x,
        cursor_y = cursor.y,
        tooltip = text,
        semantic_type = classifyMapMouseoverTooltip(text),
        semantic_source = text ~= "" and "TOOLTIP" or nil,
        coordinate_space = surface == "WORLD_MAP" and "NORMALIZED_MAP" or "MINIMAP_LOCAL",
        tooltip_data = tooltipData,
        quest_id = tooltipData and tooltipData.quest_id or nil,
        item_id = tooltipData and tooltipData.item_id or nil,
        spell_id = tooltipData and tooltipData.spell_id or nil,
        unit = tooltipUnit,
    }
end

local function cachedValue(name, reader)
    if dirty[name] or cache[name] == nil then
        cache[name] = reader()
        dirty[name] = false
    end
    return cache[name]
end

local function snapshot()
    -- 0.9.48: item button coordinates exist only while bags are open; a
    -- cached inventory from before the bags opened has none.
    if bagsAreOpen() then dirty.inventory = true end
    local mapID = C_Map and C_Map.GetBestMapForUnit and safeCall(C_Map.GetBestMapForUnit, "player")
    local pos = mapID and safeCall(C_Map.GetPlayerMapPosition, mapID, "player")
    local casting = safeCall(UnitCastingInfo, "player") or safeCall(UnitChannelInfo, "player")
    local player = readUnit("player")
    local target = readUnit("target")
    local targetName = target and target.name or nil
    local quests = cachedValue("quests", readQuests)
    local questUI = readQuestUI()
    local vendorUI = readVendorUI()
    local actionbar = readActionbar()
    local inventory = cachedValue("inventory", readInventory)
    local nameplates = readNameplates()
    local movement = readPlayerMovement()
    local _, classToken = safeUnitCall(UnitClass, "player")
    local _, raceToken = safeUnitCall(UnitRace, "player")
    local gameVersion, gameBuild = safeCall(GetBuildInfo)
    local displayedMapID = _G.WorldMapFrame and _G.WorldMapFrame.GetMapID and safeCall(_G.WorldMapFrame.GetMapID, _G.WorldMapFrame) or nil
    local telemetryMapID = displayedMapID or mapID
    local minimapGeometry
    if _G.Minimap and bool(safeCall(_G.Minimap.IsShown, _G.Minimap)) then
        local x,y = safeCall(_G.Minimap.GetCenter, _G.Minimap)
        local width,height = safeCall(_G.Minimap.GetWidth, _G.Minimap), safeCall(_G.Minimap.GetHeight, _G.Minimap)
        local sw,sh = safeCall(GetScreenWidth), safeCall(GetScreenHeight)
        if x and y and width and height and sw and sh and sw > 0 and sh > 0 then
            minimapGeometry = {center_x=x/sw,center_y=1-y/sh,radius_fraction=math.min(width,height)/2/sh,visible=true}
            -- Quest-area outline on the minimap (user 2026-10-03): pixel ->
            -- yard scale and orientation for the agent's area memory.
            local viewRadius = C_Minimap and C_Minimap.GetViewRadius and safeCall(C_Minimap.GetViewRadius) or nil
            minimapGeometry.view_radius_yards = optionalNumber(viewRadius)
            minimapGeometry.zoom = optionalNumber(safeCall(_G.Minimap.GetZoom, _G.Minimap))
            local rotate = GetCVar and safeCall(GetCVar, "rotateMinimap") or nil
            minimapGeometry.rotate_minimap = (rotate ~= nil) and tostring(rotate) == "1" or nil
        end
    end
    local data = {
        protocol_version = PROTOCOL_VERSION,
        schema_version = SCHEMA_VERSION,
        addon_version = ADDON_VERSION,
        game_version = safeText(gameVersion, ""),
        game_build = safeText(gameBuild, ""),
        addon = ADDON_NAME,
        timestamp = serverTimestamp(),
        monotonic_time = nowSeconds(),
        player_present = unitExists("player"),
        nameplates = nameplates,
        loading = isLoading,
        input_blocked = safeCall(GetCurrentKeyBoardFocus) ~= nil or
            bool(_G.GameMenuFrame and safeCall(_G.GameMenuFrame.IsShown, _G.GameMenuFrame)) or
            bool(_G.CinematicFrame and safeCall(_G.CinematicFrame.IsShown, _G.CinematicFrame)) or
            bool(_G.MovieFrame and safeCall(_G.MovieFrame.IsShown, _G.MovieFrame)),
        ui_error = nowSeconds()-lastUIErrorAt < 3 and lastUIError or nil,
        ui_error_at = nowSeconds()-lastUIErrorAt < 3 and lastUIErrorAt or nil,
        ui_error_sequence = nowSeconds()-lastUIErrorAt < 3 and lastUIErrorSequence or nil,
        ui_error_code = nowSeconds()-lastUIErrorAt < 3 and lastUIErrorCode or nil,
        event_type = "STATE_SNAPSHOT",
        character_guid = safeUnitCall(UnitGUID, "player"),
        character_name = safeUnitCall(UnitName, "player"),
        map_id = mapID,
        map_context = readMapContext(mapID, displayedMapID),
        map_world_transform = mapWorldTransform(telemetryMapID),
        minimap_geometry = minimapGeometry,
        zone_name = GetZoneText and safeText(GetZoneText(), "") or "",
        subzone_name = GetSubZoneText and safeText(GetSubZoneText(), "") or "",
        position = pos and { x = optionalNumber(pos.x), y = optionalNumber(pos.y), z = 0,
            source = "PLAYER_MAP_POSITION", coordinate_space = "NORMALIZED_MAP" } or nil,
        player_world_position = currentPlayerWorldPosition(mapID, pos,
            player and player.world_position or nil),
        orientation = safeCall(GetPlayerFacing),
        health = safeUnitCall(UnitHealth, "player"),
        max_health = safeUnitCall(UnitHealthMax, "player"),
        power = safeUnitCall(UnitPower, "player"),
        max_power = safeUnitCall(UnitPowerMax, "player"),
        money = optionalNumber(GetMoney and safeCall(GetMoney)),
        power_type = safeUnitCall(UnitPowerType, "player"),
        level = safeUnitCall(UnitLevel, "player"),
        class = classToken,
        race = raceToken,
        is_casting = casting ~= nil,
        is_mounted = bool(safeCall(IsMounted)),
        is_in_combat = bool(safeUnitCall(UnitAffectingCombat, "player")),
        is_dead = bool(safeUnitCall(UnitIsDead, "player")),
        is_ghost = bool(safeUnitCall(UnitIsGhost, "player")),
        -- 0.9.47 (live 2026-10-04, Scout-o-Matic 5000): a used vehicle NPC
        -- opens no dialog; the player is seated and flown instead.
        in_vehicle = bool(safeUnitCall(UnitInVehicle, "player")),
        has_vehicle_ui = bool(safeUnitCall(UnitHasVehicleUI, "player")),
        on_taxi = bool(safeCall(UnitOnTaxi, "player")),
        -- 0.9.50: own-avatar recognition (the ridden vehicle's box is "self")
        -- and zoom-scaled avatar size.
        vehicle_guid = unitExists("vehicle") and safeText(safeUnitCall(UnitGUID, "vehicle"), "") or nil,
        camera_distance = GetCameraZoom and safeNumber(safeCall(GetCameraZoom)) or nil,
        movement = movement,
        current_target = targetName,
        target = target and {
            guid = target.guid,
            npc_id = target.npc_id,
            name = target.name,
            level = target.level,
            classification = target.classification,
            reaction = target.reaction,
            health = target.health,
            max_health = target.max_health,
            attackable = target.is_attackable,
            dead = target.is_dead, lootable = target.lootable,
            unit_type = target.unit_type,
            world_position = target.world_position,
            screen_position = targetScreenPosition(),
        } or nil,
        soft_targets = readSoftTargets(),
        visible_units = target and {{
            guid = target.guid,
            name = targetName,
            is_attackable = target.is_attackable,
            is_interactable = target.is_attackable == false,
            is_quest_giver = false,
            is_dead = target.is_dead,
        }} or {},
        actionbar = actionbar,
        vehicle_bar = readVehicleBar(),
        control_bindings = readControlBindings(),
        binding_catalog_page = namespace.BindingCatalogPage(),
        active_quests = quests,
        quest_text = readQuestText(quests),
        quest_locations = readQuestLocations(telemetryMapID),
        map_pois = readMapPOIs(telemetryMapID),
        quest_state_revision = updateQuestRevision(quests),
        quest_ui = questUI,
        extra_action = readExtraAction(),
        death_recovery = readDeathRecovery(),
        vendor_ui = vendorUI,
        tutorial_hint = AIPlayerControllerExportDB.settings.debug and readTutorialHint() or "",
        mouseover = readMouseover(quests),
        cursor_position = readCursorPosition(),
        map_mouseover = readMapMouseover(),
        world_map_open = _G.WorldMapFrame and bool(safeCall(_G.WorldMapFrame.IsShown, _G.WorldMapFrame)) or false,
        inventory = inventory,
        bags_open = bagsAreOpen(),
        heartbeat = {
            timestamp = serverTimestamp(), addon_version = ADDON_VERSION,
            protocol_version = PROTOCOL_VERSION, player_present = unitExists("player"), map_id = mapID,
        },
        latest_event = latestEvent,
        killed_corpses = {},
    }
    recordDeadTarget(data, mapID)
    local corps = {}
    for _, c in ipairs(killedCorpses) do
        corps[#corps + 1] = { x = c.x, y = c.y, guid = c.guid, at = c.at }
    end
    data.killed_corpses = corps
    AIPlayerControllerExportDB = AIPlayerControllerExportDB or {}
    AIPlayerControllerExportDB.latest = data
    AIPlayerControllerExportDB.updated_at = serverTimestamp()
    AIPlayerControllerExportDB.health = {
        refresh_count = refreshCount, last_snapshot = data.timestamp,
        last_event = latestEvent and latestEvent.event_type or nil,
        event_sequence = eventSequence, event_history_limit = EVENT_HISTORY_LIMIT,
    }
    return data
end

local function panelText(data)
    local pos = data.position
    local lines = {
        string.format("%s schema=%d addon=%s", PROTOCOL_VERSION, SCHEMA_VERSION, ADDON_VERSION),
        "N=" .. safeText(data.character_name),
        string.format("M=%s X=%.5f Y=%.5f F=%.3f", safeText(data.map_id, "0"), safeNumber(pos and pos.x), safeNumber(pos and pos.y), safeNumber(data.orientation)),
        string.format("HP=%s/%s P=%s/%s C=%d D=%d MT=%d", safeText(data.health), safeText(data.max_health), safeText(data.power), safeText(data.max_power), bool(data.is_in_combat) and 1 or 0, bool(data.is_dead) and 1 or 0, bool(data.is_mounted) and 1 or 0),
        "T=" .. safeText(data.current_target, ""),
        string.format("Q=%d A=%d TS=%s", #data.active_quests, #data.actionbar, safeText(data.timestamp, "0")),
        string.format("BAGS=%s/%s EVENT=%s #%s", safeText(data.inventory and data.inventory.free_slots, "?"), safeText(data.inventory and data.inventory.total_slots, "?"), safeText(data.latest_event and data.latest_event.event_type, ""), safeText(data.latest_event and data.latest_event.sequence, "0")),
    }
    local mouse = data.mouseover
    local cursor = data.cursor_position
    lines[#lines + 1] = ""
    if cursor then
        lines[#lines + 1] = string.format("Cursor=%.0f %.0f (%.4f %.4f)", safeNumber(cursor.x), safeNumber(cursor.y), safeNumber(cursor.nx), safeNumber(cursor.ny))
    else
        lines[#lines + 1] = "Cursor=?"
    end
    local mapMouse = data.map_mouseover
    lines[#lines + 1] = "MAP/MINIMAP MOUSEOVER"
    if mapMouse then
        lines[#lines + 1] = string.format("Surface=%s Type=%s Map=%s X=%s Y=%s", safeText(mapMouse.surface, "?"), safeText(mapMouse.semantic_type, "?"), safeText(mapMouse.map_id, "?"), safeText(mapMouse.x, "?"), safeText(mapMouse.y, "?"))
        if mapMouse.local_x and mapMouse.local_y then
            lines[#lines + 1] = string.format("Local=%.4f %.4f", safeNumber(mapMouse.local_x), safeNumber(mapMouse.local_y))
        end
        lines[#lines + 1] = "Tooltip=" .. safeText(mapMouse.tooltip, "")
        if mapMouse.unit then
            lines[#lines + 1] = string.format("Unit=%s NPCID=%s GUID=%s", safeText(mapMouse.unit.name, "?"), safeText(mapMouse.unit.npc_id, "?"), safeText(mapMouse.unit.guid, "?"))
        end
    else
        lines[#lines + 1] = "<none>"
    end
    lines[#lines + 1] = "MOUSEOVER ENTITY"
    if mouse then
        lines[#lines + 1] = string.format("Name=%s Type=%s NPCID=%s", safeText(mouse.name, "?"), safeText(mouse.unit_type, "?"), safeText(mouse.npc_id, "?"))
        lines[#lines + 1] = string.format("GUID=%s Level=%s Class=%s", safeText(mouse.guid, "?"), safeText(mouse.level, "?"), safeText(mouse.class_name, "?"))
        lines[#lines + 1] = string.format("Reaction=%s Classif=%s Creature=%s Family=%s", safeText(mouse.reaction, "?"), safeText(mouse.classification, "?"), safeText(mouse.creature_type, "?"), safeText(mouse.creature_family, "?"))
        lines[#lines + 1] = string.format("Attackable=%s Dead=%s TapDenied=%s Connected=%s", safeText(mouse.is_attackable, "?"), safeText(mouse.is_dead, "?"), safeText(mouse.is_tap_denied, "?"), safeText(mouse.is_connected, "?"))
        if mouse.world_position then
            lines[#lines + 1] = string.format("WorldPos=%.2f %.2f %.2f", safeNumber(mouse.world_position.x), safeNumber(mouse.world_position.y), safeNumber(mouse.world_position.z))
        end
    else
        lines[#lines + 1] = "<none>"
    end
    for _, quest in ipairs(data.active_quests) do
        lines[#lines + 1] = string.format("QID=%s DONE=%d %s", safeText(quest.quest_id, "0"), bool(quest.is_complete) and 1 or 0, safeText(quest.title))
        for _, obj in ipairs(quest.objectives) do
            lines[#lines + 1] = string.format("O=%s %s/%s %s", safeText(obj.type, "UNKNOWN"), safeText(obj.current, "?"), safeText(obj.required, "?"), safeText(obj.description))
        end
    end
    return table.concat(lines, "\n")
end

local function cleanField(value)
    local text = safeText(value, "?")
    return text:gsub("[|\r\n]", " "):sub(1, 100)
end

local function pixelPayload(data)
    local pos = data.position
    local fields = {
        PROTOCOL_VERSION,
        cleanField(data.timestamp), cleanField(data.character_name), cleanField(data.map_id),
        cleanField(math.floor(safeNumber(pos and pos.x) * 100000 + 0.5)),
        cleanField(math.floor(safeNumber(pos and pos.y) * 100000 + 0.5)),
        cleanField(math.floor(safeNumber(data.orientation) * 1000 + 0.5)),
        cleanField(data.health), cleanField(data.max_health), cleanField(data.power), cleanField(data.max_power),
        bool(data.is_in_combat) and "1" or "0", bool(data.is_dead) and "1" or "0", bool(data.is_mounted) and "1" or "0",
        cleanField(data.current_target),
        cleanField(data.zone_name), cleanField(data.subzone_name), cleanField(data.quest_state_revision),
    }
    local questTotal = #data.active_quests
    local questPage = questTotal > 0 and ((refreshCount - 1) % questTotal) + 1 or 0
    fields[#fields + 1] = cleanField(questTotal)
    fields[#fields + 1] = cleanField(questPage > 0 and questPage - 1 or -1)
    local quest = questPage > 0 and data.active_quests[questPage] or nil
    fields[#fields + 1] = quest and "1" or "0"
    if quest then
        fields[#fields + 1] = cleanField(quest.quest_id)
        fields[#fields + 1] = cleanField(quest.title)
        fields[#fields + 1] = bool(quest.is_complete) and "1" or "0"
        local objectiveCount = math.min(#quest.objectives, 3)
        fields[#fields + 1] = cleanField(objectiveCount)
        for objectiveIndex = 1, objectiveCount do
            local obj = quest.objectives[objectiveIndex]
            fields[#fields + 1] = cleanField(obj.type)
            fields[#fields + 1] = cleanField(obj.current)
            fields[#fields + 1] = cleanField(obj.required)
            fields[#fields + 1] = cleanField(obj.description)
            fields[#fields + 1] = cleanField(obj.map_id or 0)
            fields[#fields + 1] = cleanField(math.floor(safeNumber(obj.x) * 100000 + 0.5))
            fields[#fields + 1] = cleanField(math.floor(safeNumber(obj.y) * 100000 + 0.5))
        end
    end
    local actionCountIndex = #fields + 1
    fields[actionCountIndex] = "0"
    local exportedActions = 0
    for _, action in ipairs(data.actionbar) do
        if action.name and exportedActions < 16 then
            local group = {
                cleanField(action.action), cleanField(action.kind), cleanField(action.name),
                cleanField(action.id), bool(action.is_usable) and "1" or "0",
            }
            if #(table.concat(fields, "|") .. "|" .. table.concat(group, "|")) < PIXEL_MAX_BYTES - 330 then
                for _, value in ipairs(group) do fields[#fields + 1] = value end
                exportedActions = exportedActions + 1
            end
        end
    end
    fields[actionCountIndex] = tostring(exportedActions)
    local questUI = data.quest_ui or {open = false, entries = {}, action = "", x = 0, y = 0, quest_id = 0}
    fields[#fields + 1] = questUI.open and "1" or "0"
    local uiEntryCountIndex = #fields + 1
    fields[uiEntryCountIndex] = "0"
    local exportedUIEntries = 0
    for _, entry in ipairs(questUI.entries) do
        if exportedUIEntries >= 6 then break end
        local group = {
            cleanField(entry.kind), cleanField(entry.quest_id), cleanField(entry.title),
            cleanField(math.floor(safeNumber(entry.x) * 10000 + 0.5)),
            cleanField(math.floor(safeNumber(entry.y) * 10000 + 0.5)),
            entry.acceptable and "1" or "0",
        }
        if #(table.concat(fields, "|") .. "|" .. table.concat(group, "|")) < PIXEL_MAX_BYTES - 170 then
            for _, value in ipairs(group) do fields[#fields + 1] = value end
            exportedUIEntries = exportedUIEntries + 1
        end
    end
    fields[uiEntryCountIndex] = tostring(exportedUIEntries)
    fields[#fields + 1] = cleanField(questUI.action)
    fields[#fields + 1] = cleanField(math.floor(safeNumber(questUI.x) * 10000 + 0.5))
    fields[#fields + 1] = cleanField(math.floor(safeNumber(questUI.y) * 10000 + 0.5))
    fields[#fields + 1] = cleanField(questUI.quest_id)
    fields[#fields + 1] = data.target and bool(data.target.attackable) and "1" or "0"
    fields[#fields + 1] = data.target and bool(data.target.dead) and "1" or "0"
    local mouse = data.mouseover
    fields[#fields + 1] = mouse and "1" or "0"
    if mouse then
        fields[#fields + 1] = cleanField(mouse.name)
        fields[#fields + 1] = cleanField(mouse.realm)
        fields[#fields + 1] = cleanField(mouse.guid)
        fields[#fields + 1] = cleanField(mouse.npc_id)
        fields[#fields + 1] = cleanField(mouse.unit_type)
        fields[#fields + 1] = cleanField(mouse.level)
        fields[#fields + 1] = cleanField(mouse.classification)
        fields[#fields + 1] = cleanField(mouse.creature_type)
        fields[#fields + 1] = cleanField(mouse.creature_family)
        fields[#fields + 1] = cleanField(mouse.reaction)
        fields[#fields + 1] = cleanField(mouse.reaction_value)
        fields[#fields + 1] = cleanField(mouse.class_name)
        fields[#fields + 1] = cleanField(mouse.class_token)
        fields[#fields + 1] = mouse.is_player and "1" or "0"
        fields[#fields + 1] = mouse.is_dead and "1" or "0"
        fields[#fields + 1] = mouse.is_attackable == nil and "?" or (mouse.is_attackable and "1" or "0")
        fields[#fields + 1] = mouse.is_tap_denied == nil and "?" or (mouse.is_tap_denied and "1" or "0")
        fields[#fields + 1] = mouse.is_connected == nil and "?" or (mouse.is_connected and "1" or "0")
        local wp = mouse.world_position
        fields[#fields + 1] = cleanField(wp and math.floor(safeNumber(wp.x) * 100 + 0.5) or "")
        fields[#fields + 1] = cleanField(wp and math.floor(safeNumber(wp.y) * 100 + 0.5) or "")
        fields[#fields + 1] = cleanField(wp and math.floor(safeNumber(wp.z) * 100 + 0.5) or "")
    end
    local cursor = data.cursor_position
    fields[#fields + 1] = cleanField(cursor and math.floor(safeNumber(cursor.nx) * 100000 + 0.5) or "")
    fields[#fields + 1] = cleanField(cursor and math.floor(safeNumber(cursor.ny) * 100000 + 0.5) or "")
    local mapMouse = data.map_mouseover
    fields[#fields + 1] = cleanField(mapMouse and mapMouse.surface or "")
    fields[#fields + 1] = cleanField(mapMouse and mapMouse.semantic_type or "")
    fields[#fields + 1] = cleanField(mapMouse and mapMouse.map_id or "")
    fields[#fields + 1] = cleanField(mapMouse and mapMouse.x and math.floor(safeNumber(mapMouse.x) * 100000 + 0.5) or "")
    fields[#fields + 1] = cleanField(mapMouse and mapMouse.y and math.floor(safeNumber(mapMouse.y) * 100000 + 0.5) or "")
    fields[#fields + 1] = cleanField(mapMouse and mapMouse.local_x and math.floor(safeNumber(mapMouse.local_x) * 100000 + 0.5) or "")
    fields[#fields + 1] = cleanField(mapMouse and mapMouse.local_y and math.floor(safeNumber(mapMouse.local_y) * 100000 + 0.5) or "")
    fields[#fields + 1] = cleanField(mapMouse and mapMouse.tooltip or "")
    fields[#fields + 1] = cleanField(mapMouse and mapMouse.unit and mapMouse.unit.name or "")
    fields[#fields + 1] = cleanField(mapMouse and mapMouse.unit and mapMouse.unit.npc_id or "")
    fields[#fields + 1] = cleanField(mapMouse and mapMouse.unit and mapMouse.unit.guid or "")
    local uiError = ""
    if lastUIError and nowSeconds() - lastUIErrorAt <= 2.5 then uiError = lastUIError end
    fields[#fields + 1] = cleanField(uiError)
    local tooltipParts = {}
    for line = 1, 3 do
        local fontString = _G["GameTooltipTextLeft" .. line]
        local text = fontString and bool(safeCall(fontString.IsVisible, fontString)) and safeCall(fontString.GetText, fontString) or nil
        if accessible(text) and text and text ~= "" then tooltipParts[#tooltipParts + 1] = safeText(text, "") end
    end
    fields[#fields + 1] = cleanField(table.concat(tooltipParts, " ~ "))
    fields[#fields + 1] = cleanField(data.tutorial_hint or "")
    fields[#fields + 1] = cleanField(#data.killed_corpses)
    for _, c in ipairs(data.killed_corpses) do
        fields[#fields + 1] = cleanField(math.floor(safeNumber(c.x) * 100000 + 0.5))
        fields[#fields + 1] = cleanField(math.floor(safeNumber(c.y) * 100000 + 0.5))
        fields[#fields + 1] = cleanField(c.guid or "")
    end
    fields[#fields + 1] = cleanField(ADDON_VERSION)
    fields[#fields + 1] = cleanField(SCHEMA_VERSION)
    fields[#fields + 1] = cleanField(latestEvent and latestEvent.sequence or 0)
    fields[#fields + 1] = cleanField(latestEvent and latestEvent.event_type or "")
    fields[#fields + 1] = cleanField(latestEvent and latestEvent.source or "")
    fields[#fields + 1] = cleanField(latestEvent and latestEvent.timestamp or 0)
    local payload = table.concat(fields, "|")
    return payload:sub(1, PIXEL_MAX_BYTES)
end

local function setPixel(index, paletteIndex)
    local cell = pixelCells[index]
    if not cell then
        cell = pixelFrame:CreateTexture(nil, "ARTWORK")
        local zero = index - 1
        local column = zero % PIXEL_COLUMNS
        local row = math.floor(zero / PIXEL_COLUMNS)
        cell:SetSize(PIXEL_CELL_SIZE, PIXEL_CELL_SIZE)
        cell:SetPoint("TOPLEFT", pixelFrame, "TOPLEFT", column * PIXEL_CELL_SIZE, -row * PIXEL_CELL_SIZE)
        pixelCells[index] = cell
    end
    local color = PIXEL_PALETTE[paletteIndex]
    cell:SetColorTexture(color[1], color[2], color[3], 1)
    cell:Show()
end

local function encodeByte(index, byte)
    for shift = 6, 0, -2 do
        setPixel(index, math.floor(byte / (2 ^ shift)) % 4 + 1)
        index = index + 1
    end
    return index
end

local function updatePixels(data, fastData)
    if not pixelFrame then return end
    local payload = namespace.NextPacket(data, fastData)
    if #payload > PIXEL_MAX_BYTES then error("AIPC packet exceeds pixel capacity") end
    local index = 1
    for _, value in ipairs(PIXEL_HEADER) do setPixel(index, value); index = index + 1 end
    index = encodeByte(index, math.floor(#payload / 256))
    index = encodeByte(index, #payload % 256)
    local checksum = 0
    for offset = 1, #payload do
        local byte = string.byte(payload, offset)
        checksum = (checksum + byte) % 256
        index = encodeByte(index, byte)
    end
    index = encodeByte(index, checksum)
    for unused = index, #pixelCells do pixelCells[unused]:Hide() end
end

-- The expensive quest/inventory snapshot remains rate-limited, while the FAST
-- transport lane gets fresh motion state for closed-loop steering. This is
-- read-only telemetry and does not emit high-frequency event history.
local function readFastState(data)
    local sampleTime = nowSeconds()
    local liveMapID = C_Map and C_Map.GetBestMapForUnit and
        safeCall(C_Map.GetBestMapForUnit, "player") or data.map_id
    local displayedMapID = _G.WorldMapFrame and _G.WorldMapFrame.GetMapID and
        safeCall(_G.WorldMapFrame.GetMapID, _G.WorldMapFrame) or nil
    local result = {
        timestamp = serverTimestamp(), monotonic_time = sampleTime,
        map_id = liveMapID, map_context = readMapContext(liveMapID, displayedMapID),
        health = safeNumber(safeCall(UnitHealth, "player")),
        max_health = safeNumber(safeCall(UnitHealthMax, "player")),
        is_dead = bool(safeCall(UnitIsDead, "player")),
        is_ghost = bool(safeCall(UnitIsGhost, "player")),
        in_vehicle = bool(safeCall(UnitInVehicle, "player")),
        has_vehicle_ui = bool(safeCall(UnitHasVehicleUI, "player")),
        on_taxi = bool(safeCall(UnitOnTaxi, "player")),
        is_in_combat = bool(safeCall(UnitAffectingCombat, "player")),
        is_mounted = bool(safeCall(IsMounted)),
        is_casting = (safeCall(UnitCastingInfo, "player") or
                      safeCall(UnitChannelInfo, "player")) ~= nil,
        player_present = unitExists("player"),
        ui_error = sampleTime-lastUIErrorAt < 3 and lastUIError or nil,
        ui_error_at = sampleTime-lastUIErrorAt < 3 and lastUIErrorAt or nil,
        ui_error_sequence = sampleTime-lastUIErrorAt < 3 and lastUIErrorSequence or nil,
        ui_error_code = sampleTime-lastUIErrorAt < 3 and lastUIErrorCode or nil,
        input_blocked = safeCall(GetCurrentKeyBoardFocus) ~= nil or
            bool(_G.GameMenuFrame and safeCall(_G.GameMenuFrame.IsShown, _G.GameMenuFrame)) or
            bool(_G.CinematicFrame and safeCall(_G.CinematicFrame.IsShown, _G.CinematicFrame)) or
            bool(_G.MovieFrame and safeCall(_G.MovieFrame.IsShown, _G.MovieFrame)),
        loading = isLoading,
    }
    local mapID = result.map_id
    local pos = mapID and C_Map and C_Map.GetPlayerMapPosition
        and safeCall(C_Map.GetPlayerMapPosition, mapID, "player")
    if pos then
        result.position = {x=optionalNumber(pos.x), y=optionalNumber(pos.y), z=0,
            source="PLAYER_MAP_POSITION", coordinate_space="NORMALIZED_MAP"}
    end
    local player = readUnit("player")
    result.player_world_position = currentPlayerWorldPosition(mapID, pos,
        player and player.world_position or nil)
    result.orientation = safeCall(GetPlayerFacing)
    result.movement = readPlayerMovement()
    -- INSPECT verification cannot wait for a multi-page full snapshot. Keep
    -- the read-only cursor/mouseover sensors current for the compact AIPC5
    -- FAST lane; Transport.lua selects only the bounded fields it needs.
    result.mouseover = readMouseover(data.active_quests)
    local target = readUnit("target")
    result.target = target and {
        guid = target.guid, npc_id = target.npc_id, name = target.name,
        level = target.level, classification = target.classification,
        reaction = target.reaction, health = target.health,
        max_health = target.max_health, attackable = target.is_attackable,
        dead = target.is_dead, lootable = target.lootable, unit_type = target.unit_type,
        world_position = target.world_position,
        screen_position = targetScreenPosition(),
    } or nil
    result.soft_targets = readSoftTargets()
    result.cursor_position = readCursorPosition()
    result.map_mouseover = readMapMouseover()
    result.quest_ui = readFastQuestUI()
    result.extra_action = readExtraAction()
    result.combat_hint = readFastCombatHint()
    result.bags_open = bagsAreOpen()
    result.world_map_open = _G.WorldMapFrame and bool(safeCall(_G.WorldMapFrame.IsShown, _G.WorldMapFrame)) or false
    result.actionbar_fast = readFastActionbar()
    -- Compact quest progress on the FAST lane. This reuses the already read
    -- snapshot and lets the controller see quest acceptance/progress without
    -- waiting for the next multi-page STATE assembly.
    local digest = {}
    for _, q in ipairs(data.active_quests or {}) do
        local done, need = 0, 0
        for _, o in ipairs(q.objectives or {}) do
            done = done + safeNumber(o.current)
            need = need + safeNumber(o.required, 1)
        end
        digest[#digest + 1] = {
            id = safeNumber(q.quest_id), complete = bool(q.is_complete),
            done = done, need = need,
        }
    end
    result.quest_digest = digest
    result.quest_state_revision = data.quest_state_revision
    return result
end

local function identityKey(unit)
    if not unit then return "" end
    return table.concat({safeText(unit.guid, ""), safeText(unit.name, ""), safeText(unit.unit_type, "")}, ":")
end

local function mapMouseoverKey(observation)
    if not observation then return "" end
    local function quantized(value)
        if type(value) ~= "number" or not accessible(value) then return "" end
        return tostring(math.floor(value * 500 + 0.5))
    end
    return table.concat({
        safeText(observation.surface, ""), safeText(observation.map_id, ""),
        quantized(observation.x), quantized(observation.y),
        quantized(observation.local_x), quantized(observation.local_y),
        safeText(observation.tooltip, ""),
    }, ":")
end

local function emitStateTransitions(data)
    if previousState.initialized then
        if previousState.target ~= identityKey(data.target) then
            emitEvent("TARGET_CHANGED", data.target or { exists = false }, "WOW_API")
        end
        local mouseKey = identityKey(data.mouseover)
        if lastMouseoverKey ~= mouseKey then
            local payload = data.mouseover or { exists = false }
            if data.map_mouseover and data.map_mouseover.tooltip then
                payload.tooltip_text = data.map_mouseover.tooltip
                payload.quest_role = data.map_mouseover.semantic_type
                payload.quest_role_source = data.map_mouseover.semantic_source
            end
            emitEvent("MOUSEOVER_CHANGED", payload, "WOW_API")
            lastMouseoverKey = mouseKey
        end
        local mapMouseKey = mapMouseoverKey(data.map_mouseover)
        if previousState.map_mouseover ~= mapMouseKey then
            emitEvent(data.map_mouseover and "MAP_MOUSEOVER_CHANGED" or "MAP_MOUSEOVER_CLEARED", data.map_mouseover or {}, "WOW_API_TOOLTIP")
        end
        if previousState.map_id ~= data.map_id then emitEvent("MAP_CHANGED", {map_id = data.map_id}, "WOW_API") end
        if previousState.zone ~= data.zone_name or previousState.subzone ~= data.subzone_name then
            emitEvent("ZONE_CHANGED", {map_id = data.map_id, zone = data.zone_name, subzone = data.subzone_name}, "WOW_API")
        end
        if previousState.moving ~= data.movement.moving then emitEvent(data.movement.moving and "MOVEMENT_STARTED" or "MOVEMENT_STOPPED", data.movement, "WOW_API") end
        if previousState.swimming ~= data.movement.swimming then emitEvent(data.movement.swimming and "SWIMMING_STARTED" or "SWIMMING_STOPPED", data.movement, "WOW_API") end
        if previousState.falling ~= data.movement.falling then emitEvent(data.movement.falling and "FALL_STARTED" or "FALL_ENDED", data.movement, "WOW_API") end
        if previousState.mounted ~= data.is_mounted then emitEvent(data.is_mounted and "MOUNTED" or "DISMOUNTED", {mounted = data.is_mounted, flying = data.movement.flying}, "WOW_API") end
        if previousState.combat ~= data.is_in_combat then emitEvent(data.is_in_combat and "COMBAT_STARTED" or "COMBAT_ENDED", {}, "WOW_API") end
        if previousState.dead ~= data.is_dead then emitEvent(data.is_dead and "PLAYER_DIED" or "PLAYER_ALIVE", {}, "WOW_API") end
        if previousState.ghost ~= data.is_ghost then emitEvent(data.is_ghost and "PLAYER_GHOST" or "PLAYER_RESURRECTED", {}, "WOW_API") end
        if previousState.quest_revision ~= data.quest_state_revision then
            emitEvent("QUEST_LOG_CHANGED", {revision = data.quest_state_revision, quests = data.active_quests}, "WOW_API")
        end
        if previousState.free_slots ~= data.inventory.free_slots or previousState.item_count ~= #data.inventory.items then
            emitEvent("BAG_UPDATED", {
                free_slots = data.inventory.free_slots, total_slots = data.inventory.total_slots,
                item_count = #data.inventory.items,
            }, "WOW_API")
        end
        local worldMapOpen = data.world_map_open
        if previousState.world_map_open ~= worldMapOpen then emitEvent(worldMapOpen and "WORLD_MAP_OPENED" or "WORLD_MAP_CLOSED", {map_id = data.map_id}, "UI_STATE") end
        local vendorOpen = data.vendor_ui and data.vendor_ui.open or false
        if previousState.vendor_open ~= vendorOpen then
            emitEvent(vendorOpen and "VENDOR_OPENED" or "VENDOR_CLOSED",
                {npc_name = data.vendor_ui and data.vendor_ui.npc_name,
                 can_repair = data.vendor_ui and data.vendor_ui.can_repair}, "WOW_API")
        end
    else
        emitEvent("STATE_SYNC", {map_id = data.map_id, character_guid = data.character_guid}, "ADDON")
        lastMouseoverKey = identityKey(data.mouseover)
    end
    previousState = {
        initialized = true, target = identityKey(data.target), map_mouseover = mapMouseoverKey(data.map_mouseover),
        map_id = data.map_id, zone = data.zone_name, subzone = data.subzone_name,
        moving = data.movement.moving, swimming = data.movement.swimming, falling = data.movement.falling,
        mounted = data.is_mounted, combat = data.is_in_combat, dead = data.is_dead, ghost = data.is_ghost,
        quest_revision = data.quest_state_revision,
        free_slots = data.inventory.free_slots, item_count = #data.inventory.items,
        world_map_open = data.world_map_open,
        vendor_open = data.vendor_ui and data.vendor_ui.open or false,
    }
    data.latest_event = latestEvent
    data.event_sequence = eventSequence
    data.events = {}
    local history = AIPlayerControllerExportDB.events or {}
    for i=math.max(1, #history-7),#history do
        -- Do not duplicate the entire quest list inside an event page.
        local e = history[i]
        local payload = e.payload
        if e.event_type == "QUEST_LOG_CHANGED" then payload = {revision=e.payload.revision} end
        data.events[#data.events+1] = {event_type=e.event_type, sequence=e.sequence, timestamp=e.timestamp, source=e.source, payload=payload}
    end
end

local function createPanel()
    panel = CreateFrame("Frame", "AIPlayerControllerExportPanel", UIParent, "BackdropTemplate")
    panel:SetSize(760, 520)
    panel:SetPoint("TOPLEFT", UIParent, "TOPLEFT", 12, -12)
    panel:SetFrameStrata("TOOLTIP")
    panel:SetBackdrop({ bgFile = "Interface/Tooltips/UI-Tooltip-Background", edgeFile = "Interface/Tooltips/UI-Tooltip-Border", edgeSize = 12 })
    panel:SetBackdropColor(0, 0, 0, 0.95)
    panel.text = panel:CreateFontString(nil, "OVERLAY", "GameFontHighlightSmall")
    panel.text:SetPoint("TOPLEFT", 10, -10)
    panel.text:SetPoint("BOTTOMRIGHT", -10, 10)
    panel.text:SetJustifyH("LEFT")
    panel.text:SetJustifyV("TOP")
    panel.text:SetText("AIPC loading...")
    panel:Hide()

    pixelFrame = CreateFrame("Frame", "AIPlayerControllerPixelBridge", UIParent)
    local parentScale = safeCall(UIParent.GetEffectiveScale, UIParent)
    if pixelFrame.SetIgnoreParentScale then
        pixelFrame:SetIgnoreParentScale(true)
        pixelFrame:SetScale(1)
    elseif accessible(parentScale) and parentScale and parentScale > 0 and pixelFrame.SetScale then
        pixelFrame:SetScale(1 / parentScale)
    end
    pixelFrame:SetSize(PIXEL_COLUMNS * PIXEL_CELL_SIZE, 128)
    pixelFrame:SetPoint("TOPLEFT", UIParent, "TOPLEFT", 12, -12)
    pixelFrame:SetFrameStrata("TOOLTIP")
    pixelFrame:Show()
end

local function refresh()
    refreshCount = refreshCount + 1
    lastRefreshAt = nowSeconds()
    if panel then panel.text:SetText("AIPC refreshing #" .. refreshCount .. "...") end
    local ok, data = xpcall(snapshot, function(message)
        return tostring(message) .. "\n" .. debugstack(2, 5, 5)
    end)
    if not ok then
        lastError = data
        if panel then panel.text:SetText("AIPC ERROR\n" .. data) end
        return
    end
    lastError = nil
    local transitionOk, transitionError = pcall(emitStateTransitions, data)
    if not transitionOk then
        lastError = tostring(transitionError)
        if panel then panel.text:SetText("AIPC EVENT ERROR\n" .. lastError) end
        return
    end
    local textOk, rendered = pcall(panelText, data)
    if not textOk then
        lastError = tostring(rendered)
        if panel then panel.text:SetText("AIPC RENDER ERROR\n" .. lastError) end
        return
    end
    latestSnapshot = data
    local pixelOk, pixelError = pcall(updatePixels, data)
    if not pixelOk then lastError = tostring(pixelError) end
    if panel then panel.text:SetText(rendered) end
end

for _, eventName in ipairs({
    "PLAYER_LOGIN", "PLAYER_ENTERING_WORLD", "QUEST_LOG_UPDATE", "QUEST_ACCEPTED", "QUEST_TURNED_IN",
    "QUEST_REMOVED", "QUEST_WATCH_UPDATE", "ACTIONBAR_SLOT_CHANGED", "SPELLS_CHANGED",
    "PLAYER_TARGET_CHANGED", "UPDATE_MOUSEOVER_UNIT", "PLAYER_REGEN_DISABLED", "PLAYER_REGEN_ENABLED",
    "UI_ERROR_MESSAGE", "GOSSIP_SHOW", "GOSSIP_CLOSED", "QUEST_GREETING", "QUEST_DETAIL",
    "QUEST_PROGRESS", "QUEST_COMPLETE", "QUEST_FINISHED", "BAG_UPDATE_DELAYED", "LOOT_OPENED", "LOOT_CLOSED",
    "CHAT_MSG_LOOT", "UNIT_SPELLCAST_SUCCEEDED", "UNIT_SPELLCAST_FAILED", "UNIT_SPELLCAST_INTERRUPTED",
    "PLAYER_STARTED_MOVING", "PLAYER_STOPPED_MOVING", "PLAYER_MOUNT_DISPLAY_CHANGED", "PLAYER_DEAD",
    "PLAYER_ALIVE", "PLAYER_UNGHOST", "ZONE_CHANGED", "ZONE_CHANGED_INDOORS", "ZONE_CHANGED_NEW_AREA",
    "LOADING_SCREEN_ENABLED", "LOADING_SCREEN_DISABLED", "UPDATE_BINDINGS",
    "MERCHANT_SHOW", "MERCHANT_CLOSED", "MERCHANT_UPDATE",
    "CHAT_MSG_MONSTER_SAY", "CHAT_MSG_MONSTER_YELL", "QUESTLINE_UPDATE",
}) do
    safeCall(frame.RegisterEvent, frame, eventName)
end
frame:SetScript("OnEvent", function(_, event, ...)
    if event == "UPDATE_BINDINGS" or event == "PLAYER_ENTERING_WORLD" then namespace.InvalidateBindings() end
    if event == "QUESTLINE_UPDATE" or event == "QUEST_TURNED_IN" or event == "QUEST_ACCEPTED"
            or event == "ZONE_CHANGED_NEW_AREA" then
        mapPoiCache.at = -1000
    end
    if event == "LOADING_SCREEN_ENABLED" then isLoading = true end
    if event == "LOADING_SCREEN_DISABLED" or event == "PLAYER_ENTERING_WORLD" then isLoading = false end
    if event == "UI_ERROR_MESSAGE" then
        local errorCode, message = ...
        lastUIError = safeText(message, "")
        lastUIErrorAt = nowSeconds()
        lastUIErrorCode = safeNumber(errorCode)
        emitEvent("UI_ERROR_MESSAGE", {
            error_code = lastUIErrorCode,
            message = lastUIError,
            observed_at = lastUIErrorAt,
        }, "WOW_EVENT")
        lastUIErrorSequence = eventSequence
    end
    if event == "QUEST_DETAIL" or event == "QUEST_PROGRESS" or event == "QUEST_COMPLETE" then
        local dialogQuestID = GetQuestID and safeCall(GetQuestID) or nil
        if event == "QUEST_DETAIL" then
            rememberQuestText(dialogQuestID, "description", GetQuestText and safeCall(GetQuestText) or nil)
            rememberQuestText(dialogQuestID, "objectives_text", GetObjectiveText and safeCall(GetObjectiveText) or nil)
            -- 0.9.52: the unit offering the quest ("npc" during the dialog).
            -- Many quests are turned in to their giver ("report back to me").
            rememberQuestText(dialogQuestID, "giver_name", safeUnitCall(UnitName, "npc"))
            rememberQuestText(dialogQuestID, "giver_guid", safeUnitCall(UnitGUID, "npc"))
        elseif event == "QUEST_PROGRESS" then
            rememberQuestText(dialogQuestID, "progress_text", GetProgressText and safeCall(GetProgressText) or nil)
        else
            rememberQuestText(dialogQuestID, "completion_text", GetRewardText and safeCall(GetRewardText) or nil)
            -- Ground truth for the turn-in NPC inference (who took the quest).
            rememberQuestText(dialogQuestID, "ender_name", safeUnitCall(UnitName, "npc"))
        end
    end
    if event == "QUEST_DETAIL" then
        questUIHint = {open = true, action = "ACCEPT", observed_at = nowSeconds()}
    elseif event == "QUEST_PROGRESS" then
        questUIHint = {open = true, action = "CONTINUE", observed_at = nowSeconds()}
    elseif event == "QUEST_COMPLETE" then
        questUIHint = {open = true, action = "COMPLETE", observed_at = nowSeconds()}
    elseif event == "QUEST_GREETING" or event == "GOSSIP_SHOW" then
        questUIHint = {open = true, action = "", observed_at = nowSeconds()}
    elseif event == "QUEST_FINISHED" or event == "GOSSIP_CLOSED" or event == "QUEST_ACCEPTED" then
        questUIHint = {open = false, action = "", observed_at = nowSeconds()}
    end
    if event == "PLAYER_LOGIN" then
        initializeDatabase()
        createPanel()
        emitEvent("ADDON_READY", {addon = ADDON_NAME, game_version = safeText(safeCall(GetBuildInfo), "")}, "ADDON")
        ticker = C_Timer.NewTicker(AIPlayerControllerExportDB.settings.snapshot_interval, refresh)
        transportTicker = C_Timer.NewTicker(TRANSPORT_INTERVAL, function()
            if latestSnapshot then
                local fastState = readFastState(latestSnapshot)
                local ok, err = pcall(updatePixels, latestSnapshot, fastState)
                if not ok then lastError = tostring(err) end
            end
        end)
        print("|cff55ff55AIPC Export loaded.|r /aipc show")
    end
    if event == "ACTIONBAR_SLOT_CHANGED" or event == "SPELLS_CHANGED" then dirty.actionbar = true end
    if event:find("^QUEST_") then dirty.quests = true; dirty.quest_ui = true end
    if event == "GOSSIP_SHOW" or event == "GOSSIP_CLOSED" then dirty.quest_ui = true end
    if event == "BAG_UPDATE_DELAYED" or event == "CHAT_MSG_LOOT" then dirty.inventory = true end
    if event == "QUEST_ACCEPTED" then
        local questID = ...
        emitEvent("QUEST_ACCEPTED", {quest_id = safeNumber(questID)}, "WOW_EVENT")
    elseif event == "QUEST_TURNED_IN" then
        local questID, xpReward, moneyReward = ...
        emitEvent("QUEST_TURNED_IN", {quest_id = safeNumber(questID), xp = safeNumber(xpReward), money = safeNumber(moneyReward)}, "WOW_EVENT")
    elseif event == "QUEST_REMOVED" then
        emitEvent("QUEST_ABANDONED_OR_REMOVED", {quest_id = safeNumber((...))}, "WOW_EVENT")
    elseif event == "LOOT_OPENED" or event == "LOOT_CLOSED" then
        emitEvent(event == "LOOT_OPENED" and "LOOT_WINDOW_OPENED" or "LOOT_WINDOW_CLOSED", {}, "WOW_EVENT")
    elseif event == "CHAT_MSG_LOOT" then
        emitEvent("LOOT_RECEIVED", {message = safeText((...), "")}, "WOW_EVENT")
    elseif event == "CHAT_MSG_MONSTER_SAY" or event == "CHAT_MSG_MONSTER_YELL" then
        local message, sender, _, _, _, _, _, _, _, _, _, guid = ...
        emitEvent("NPC_INSTRUCTION", {message = safeText(message, ""), sender = safeText(sender, ""),
            guid = safeText(guid, ""), channel = event}, "WOW_EVENT")
    elseif event:find("^UNIT_SPELLCAST_") then
        local unit, castGUID, spellID = ...
        -- 0.9.50 (live 2026-10-04): a vehicle ability is cast by "vehicle";
        -- the player's own event was a client-side FAILED while the boar
        -- did lunge.  Export both, tagged with the unit.
        if unit == "player" or unit == "vehicle" or unit == "pet" then
            local normalized = event:gsub("UNIT_", "")
            emitEvent(normalized, {cast_guid = safeText(castGUID, ""), spell_id = safeNumber(spellID),
                unit = unit}, "WOW_EVENT")
        end
        if unit == "player" then
            if event == "UNIT_SPELLCAST_SUCCEEDED" then
                combatHint = {spell_id = safeNumber(spellID) or 0, at = nowSeconds()}
            end
        end
    elseif event == "GOSSIP_SHOW" then emitEvent("NPC_DIALOG_OPENED", {}, "WOW_EVENT")
    elseif event == "GOSSIP_CLOSED" then emitEvent("NPC_DIALOG_CLOSED", {}, "WOW_EVENT")
    elseif event == "LOADING_SCREEN_ENABLED" then emitEvent("LOADING_SCREEN_STARTED", {}, "WOW_EVENT")
    elseif event == "LOADING_SCREEN_DISABLED" then emitEvent("LOADING_SCREEN_ENDED", {}, "WOW_EVENT")
    end
    if event == "PLAYER_LOGIN" or (panel and nowSeconds()-lastRefreshAt >= 0.2) then refresh() end
end)

SLASH_AIPCEXPORT1 = "/aipc"
SlashCmdList.AIPCEXPORT = function(message)
    local command = string.lower(message or "")
    if command == "show" then
        panel:Show()
        panel.text:SetText("AIPC show command received")
        refresh()
        return
    end
    if command == "hide" then panel:Hide(); return end
    if command == "export" then refresh(); print("AIPC snapshot updated in SavedVariables."); return end
    if command == "bindings" then
        namespace.InvalidateBindings()
        local page = namespace.BindingCatalogPage()
        print("AIPC binding catalog: " .. tostring(page.count or page.status) .. ". SavedVariables + paged telemetry; no bindings changed.")
        return
    end
    if command == "error" then print(lastError or "AIPC: no error"); return end
    if command == "status" then
        print(string.format("AIPC %s/%d refresh=%d last=%.2f event=%s#%d rate=%.1fs", PROTOCOL_VERSION, SCHEMA_VERSION, refreshCount, lastRefreshAt, safeText(latestEvent and latestEvent.event_type, "none"), eventSequence, safeNumber(AIPlayerControllerExportDB and AIPlayerControllerExportDB.settings and AIPlayerControllerExportDB.settings.snapshot_interval, SNAPSHOT_INTERVAL)))
        return
    end
    local rate = command:match("^rate%s+([%d%.]+)$")
    if rate then
        local seconds = tonumber(rate)
        if not seconds or seconds < 0.2 or seconds > 10 then print("AIPC rate must be between 0.2 and 10 seconds."); return end
        initializeDatabase()
        AIPlayerControllerExportDB.settings.snapshot_interval = seconds
        if ticker then ticker:Cancel() end
        ticker = C_Timer.NewTicker(seconds, refresh)
        print(string.format("AIPC snapshot rate set to %.1fs.", seconds))
        return
    end
    if command == "events" then
        print(string.format("AIPC events=%d latest=%s#%d", #(AIPlayerControllerExportDB.events or {}), safeText(latestEvent and latestEvent.event_type, "none"), eventSequence))
        return
    end
    if command == "test" then panel:Show(); panel.text:SetText("AIPC PANEL TEST OK"); return end
    print("/aipc show | hide | export | bindings | error | status | events | rate 0.2-10 | test")
end
