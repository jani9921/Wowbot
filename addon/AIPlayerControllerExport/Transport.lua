-- AIPC5 extends the existing color-grid transport with typed JSON and complete
-- snapshot pages. No SavedVariables file polling is needed for live delivery.
local addonName, ns = ...
local session = tostring(GetServerTime()) .. "-" .. tostring(math.floor(GetTime() * 1000))
local sequence, cursor, round, laneSlot = 0, 1, 0, 0
local pages = {}
local sourceSequence = 0
local sourceTime
local stateTime
local stateKind = "STATE"
local function compactText(value, limit)
    if type(value) ~= "string" or #value == 0 or #value > limit then return nil end
    return value
end
local function compactMouseoverName(mouse, limit)
    if type(mouse) ~= "table" then return nil end
    local name = compactText(mouse.name, limit)
    if name then return name end
    local data = mouse.tooltip_data
    -- Retail game objects have no UnitName/GUID. Keep the current structured
    -- tooltip's short name on FAST instead of waiting for paged STATE.
    if mouse.quest_related and (mouse.guid == nil or mouse.guid == "")
            and type(data) == "table" and data.is_unit ~= true
            and not (type(data.unit_guid) == "string" and #data.unit_guid > 0)
            and not (type(data.guid) == "string" and #data.guid > 0) then
        return compactText(data.unit_name, limit)
    end
    return nil
end
-- Live 2026-10-02: every FAST packet fell back to the bounded variants, which
-- carried no world position, so movement saw a 1-3 s old position from the
-- paged STATE and reported "stuck" while running.  Keep X/Y (0.01 yd) and the
-- instance on every bounded packet; Python restores the remaining metadata.
local function compactWorldPosition(value)
    if type(value) ~= "table" or type(value.x) ~= "number" or type(value.y) ~= "number"
            or value.instance_id == nil then
        return false
    end
    return {x=math.floor(value.x*100+.5)/100, y=math.floor(value.y*100+.5)/100,
        instance_id=value.instance_id, coordinate_space="WORLD_YARDS"}
end
local function compactSoftTargets(values)
    local result = {}
    if type(values) ~= "table" then return result end
    for i=1,math.min(3,#values) do
        local value = values[i]
        if type(value) == "table" then
            result[#result+1] = {
                source_unit=compactText(value.source_unit,16),
                guid=compactText(value.guid,128),name=compactText(value.name,96),
                npc_id=value.npc_id,unit_type=compactText(value.unit_type,24),
                is_attackable=value.is_attackable,is_dead=value.is_dead,
                evidence_role="CANDIDATE_HINT",confirmed=false,
            }
        end
    end
    return result
end
local function available(v)
    return not (issecretvalue and issecretvalue(v)) and not (canaccessvalue and not canaccessvalue(v))
end
local function quote(s)
    return '"' .. s:gsub('[%z\1-\31\\"]', function(c)
        if c == '"' then return '\\"' end
        if c == '\\' then return '\\\\' end
        return string.format('\\u%04x', string.byte(c))
    end) .. '"'
end
local function encode(v, depth)
    depth = depth or 0
    if depth > 12 or not available(v) or v == nil then return "null" end
    local kind = type(v)
    if kind == "boolean" then return v and "true" or "false" end
    if kind == "number" then
        if v ~= v or v == math.huge or v == -math.huge then return "null" end
        return tostring(v)
    end
    if kind == "string" then return quote(v) end
    if kind ~= "table" then return "null" end
    local keys, count, array = {}, 0, true
    for k in pairs(v) do
        if available(k) then
            count = count + 1
            keys[#keys+1] = k
            if type(k) ~= "number" or k < 1 or k ~= math.floor(k) then array = false end
        end
    end
    array = array and count > 0 and #v == count
    local parts = {}
    if array then
        for i=1,#v do parts[#parts+1] = encode(v[i], depth+1) end
        return "[" .. table.concat(parts, ",") .. "]"
    end
    table.sort(keys, function(a,b) return tostring(a) < tostring(b) end)
    for _,k in ipairs(keys) do
        parts[#parts+1] = quote(tostring(k)) .. ":" .. encode(v[k], depth+1)
    end
    return "{" .. table.concat(parts, ",") .. "}"
end
local function split(text)
    local result, start = {}, 1
    while start <= #text do
        local last = math.min(#text, start + 849)
        -- Preserve UTF-8 boundaries; the Python pixel decoder validates UTF-8.
        while last < #text do
            local b = string.byte(text, last+1)
            if b < 128 or b >= 192 then break end
            last = last-1
        end
        result[#result+1] = text:sub(start,last)
        start = last+1
    end
    return result
end
function ns.EncodeJSON(value) return encode(value) end
function ns.NextPacket(data, fastData)
    -- The pixel bridge is a single visible channel. Three fresh FAST_STATE
    -- packets followed by one paged STATE packet (0.9.58; was five).
    -- Live 2026-10-06: the client ran ~37 ticks/s, the capture kept ~80 %
    -- of them, and each page was shown only once before the next snapshot
    -- was encoded: 23 % of the ~6-page snapshots ever completed (tooltips,
    -- quest credit and events seconds late).  More page slots plus every
    -- snapshot shown at least twice (below) let a lost page come back.
    laneSlot = (laneSlot + 1) % 4
    if laneSlot ~= 0 then
        local sample = fastData or data
        local v = {
            telemetry_lane="FAST_STATE", fast_sample_time=sample.monotonic_time,
            timestamp=sample.timestamp, monotonic_time=sample.monotonic_time,
            map_id=sample.map_id,
            map_context=sample.map_context and {
                active_map_id=sample.map_context.active_map_id,
                parent_map_id=sample.map_context.parent_map_id,
                player_map_id=sample.map_context.player_map_id,
                displayed_map_id=sample.map_context.displayed_map_id,
                map_name=sample.map_context.map_name,
                parent_map_name=sample.map_context.parent_map_name,
                world_map_open=sample.map_context.world_map_open} or false,
            position=sample.position and {x=sample.position.x,y=sample.position.y},
            player_world_position=sample.player_world_position, orientation=sample.orientation,
            health=sample.health, max_health=sample.max_health, is_dead=sample.is_dead, is_ghost=sample.is_ghost,
            is_in_combat=sample.is_in_combat, is_mounted=sample.is_mounted, is_casting=sample.is_casting,
            movement=sample.movement and {speed=sample.movement.speed,moving=sample.movement.moving,
                falling=sample.movement.falling,swimming=sample.movement.swimming,
                indoors=sample.movement.indoors} or false,
            player_present=sample.player_present, ui_error=sample.ui_error,
            ui_error_at=sample.ui_error_at, ui_error_sequence=sample.ui_error_sequence,
            ui_error_code=sample.ui_error_code,
            input_blocked=sample.input_blocked, loading=sample.loading,
            target=sample.target and {guid=sample.target.guid, name=sample.target.name, npc_id=sample.target.npc_id,
                health=sample.target.health, max_health=sample.target.max_health, attackable=sample.target.attackable,
                dead=sample.target.dead, world_position=sample.target.world_position,
                screen_position=sample.target.screen_position} or false,
            target_sample_time=sample.monotonic_time,
            soft_targets=compactSoftTargets(sample.soft_targets),
            mouseover=sample.mouseover and {guid=sample.mouseover.guid, name=compactMouseoverName(sample.mouseover,96),
                npc_id=sample.mouseover.npc_id, unit_type=sample.mouseover.unit_type,
                structured_unit=sample.mouseover.structured_unit,
                is_attackable=sample.mouseover.is_attackable, is_dead=sample.mouseover.is_dead,
                lootable=sample.mouseover.lootable,
                quest_related=sample.mouseover.quest_related, quest_id=sample.mouseover.quest_id,
                quest_role=sample.mouseover.quest_role, quest_role_source=sample.mouseover.quest_role_source,
                identity_source=sample.mouseover.identity_source,
                tooltip_text=sample.mouseover.tooltip,
                tooltip_data=sample.mouseover.tooltip_data and {
                    raw_type=sample.mouseover.tooltip_data.raw_type,
                    is_unit=sample.mouseover.tooltip_data.is_unit,
                    unit_name=sample.mouseover.tooltip_data.unit_name,
                    id=sample.mouseover.tooltip_data.id,
                    guid=sample.mouseover.tooltip_data.guid,
                    unit_guid=sample.mouseover.tooltip_data.unit_guid,
                    quest_id=sample.mouseover.tooltip_data.quest_id,
                    item_id=sample.mouseover.tooltip_data.item_id,
                    object_id=sample.mouseover.tooltip_data.object_id} or false} or false,
            mouseover_sample_time=sample.monotonic_time,
            cursor_position=sample.cursor_position and {nx=sample.cursor_position.nx,ny=sample.cursor_position.ny} or false,
            cursor_sample_time=sample.monotonic_time,
            map_mouseover=sample.map_mouseover and {surface=sample.map_mouseover.surface,
                semantic_type=sample.map_mouseover.semantic_type, semantic_source=sample.map_mouseover.semantic_source,
                map_id=sample.map_mouseover.map_id, x=sample.map_mouseover.x, y=sample.map_mouseover.y,
                local_x=sample.map_mouseover.local_x, local_y=sample.map_mouseover.local_y,
                tooltip=sample.map_mouseover.tooltip, quest_id=sample.map_mouseover.quest_id} or false,
            map_mouseover_sample_time=sample.monotonic_time,
            quest_ui=sample.quest_ui and {open=sample.quest_ui.open,
                action=sample.quest_ui.action,x=sample.quest_ui.x,y=sample.quest_ui.y,
                quest_id=sample.quest_ui.quest_id} or false,
            extra_action=sample.extra_action and {visible=sample.extra_action.visible,
                usable=sample.extra_action.usable,action=sample.extra_action.action,
                action_type=sample.extra_action.action_type,action_id=sample.extra_action.action_id} or false,
            quest_digest=sample.quest_digest or false,
            quest_state_revision=sample.quest_state_revision,
            actionbar_fast=sample.actionbar_fast,
            combat_hint=sample.combat_hint and {spell_id=sample.combat_hint.spell_id,at=sample.combat_hint.at} or false,
        }
        local text = encode(v)
        if #text > 850 then
            -- Inspection evidence has priority over health/target duplication
            -- already present in the paged snapshot. Keep movement feedback as
            -- well, so an incidental mouseover cannot starve closed-loop motion.
            v = {
                telemetry_lane=v.telemetry_lane, fast_sample_time=v.fast_sample_time,
                timestamp=v.timestamp, monotonic_time=v.monotonic_time,
                map_id=v.map_id, map_context=v.map_context, position=v.position,
                player_world_position=v.player_world_position, orientation=v.orientation,
                movement=v.movement,
                -- Survival/control minimum in every FAST variant (issue #72).
                health=v.health, max_health=v.max_health, is_dead=v.is_dead,
                is_ghost=v.is_ghost, is_in_combat=v.is_in_combat, is_casting=v.is_casting,
                player_present=v.player_present, loading=v.loading,
                input_blocked=v.input_blocked,
                target=v.target and {guid=v.target.guid,name=v.target.name,npc_id=v.target.npc_id,
                    attackable=v.target.attackable,dead=v.target.dead,
                    world_position=v.target.world_position or false} or false,
                target_sample_time=v.target_sample_time,
                soft_targets=v.soft_targets,
                -- Tooltip addons can append kilobytes of descriptive text.
                -- Preserve the time-critical unit identity and discard only
                -- bulky presentation text on the compact lane.
                mouseover=v.mouseover and {guid=v.mouseover.guid,name=v.mouseover.name,
                    npc_id=v.mouseover.npc_id,unit_type=v.mouseover.unit_type,
                    structured_unit=v.mouseover.structured_unit,
                    is_attackable=v.mouseover.is_attackable,is_dead=v.mouseover.is_dead,
                    quest_related=v.mouseover.quest_related,quest_id=v.mouseover.quest_id,
                    identity_source=v.mouseover.identity_source,
                    tooltip_data=v.mouseover.tooltip_data and {
                        raw_type=v.mouseover.tooltip_data.raw_type,
                        is_unit=v.mouseover.tooltip_data.is_unit,
                        unit_name=v.mouseover.tooltip_data.unit_name,
                        unit_guid=v.mouseover.tooltip_data.unit_guid} or false} or false,
                mouseover_sample_time=v.mouseover_sample_time,
                cursor_position=v.cursor_position, cursor_sample_time=v.cursor_sample_time,
                map_mouseover=v.map_mouseover and {surface=v.map_mouseover.surface,
                    map_id=v.map_mouseover.map_id,x=v.map_mouseover.x,y=v.map_mouseover.y,
                    local_x=v.map_mouseover.local_x,local_y=v.map_mouseover.local_y,
                    quest_id=v.map_mouseover.quest_id} or false,
                map_mouseover_sample_time=v.map_mouseover_sample_time,
                quest_ui=v.quest_ui,
                extra_action=v.extra_action,
                quest_digest=v.quest_digest, quest_state_revision=v.quest_state_revision,
                actionbar_fast=v.actionbar_fast, combat_hint=v.combat_hint,
            }
            text = encode(v)
        end
        if #text > 850 then
            -- A long identity may still overflow the first compact packet.
            -- Keep the GUID/name/cursor inspection edge even in the guaranteed
            -- bounded control core; never make identity wait for a paged full
            -- snapshot whose assembly can outlive a short hover.
            v = {
                telemetry_lane="FAST_STATE", fast_sample_time=sample.monotonic_time,
                timestamp=sample.timestamp, monotonic_time=sample.monotonic_time,
                map_id=sample.map_id,
                map_context=sample.map_context and {
                    active_map_id=sample.map_context.active_map_id,
                    parent_map_id=sample.map_context.parent_map_id,
                    player_map_id=sample.map_context.player_map_id,
                    displayed_map_id=sample.map_context.displayed_map_id,
                    world_map_open=sample.map_context.world_map_open} or false,
                position=sample.position and {x=sample.position.x,y=sample.position.y} or false,
                player_world_position=sample.player_world_position or false,
                orientation=sample.orientation, movement=sample.movement and {
                    speed=sample.movement.speed,moving=sample.movement.moving,
                    falling=sample.movement.falling,swimming=sample.movement.swimming,
                    indoors=sample.movement.indoors} or false,
                target=sample.target and {guid=sample.target.guid,name=sample.target.name,npc_id=sample.target.npc_id,
                    attackable=sample.target.attackable,dead=sample.target.dead,
                    world_position=sample.target.world_position or false} or false,
                target_sample_time=sample.monotonic_time,
                mouseover=sample.mouseover and {guid=sample.mouseover.guid,
                    name=compactMouseoverName(sample.mouseover,96),npc_id=sample.mouseover.npc_id,
                    unit_type=sample.mouseover.unit_type,
                    structured_unit=sample.mouseover.structured_unit,
                    is_attackable=sample.mouseover.is_attackable,
                    quest_related=sample.mouseover.quest_related,quest_id=sample.mouseover.quest_id,
                    identity_source=sample.mouseover.identity_source} or false,
                mouseover_sample_time=sample.monotonic_time,
                cursor_position=sample.cursor_position and {
                    nx=sample.cursor_position.nx,ny=sample.cursor_position.ny} or false,
                cursor_sample_time=sample.monotonic_time,
                quest_ui=sample.quest_ui and {open=sample.quest_ui.open,
                    action=sample.quest_ui.action,x=sample.quest_ui.x,y=sample.quest_ui.y,
                    quest_id=sample.quest_ui.quest_id} or false,
                extra_action=sample.extra_action and {visible=sample.extra_action.visible,
                    usable=sample.extra_action.usable,action=sample.extra_action.action,
                    action_type=sample.extra_action.action_type,action_id=sample.extra_action.action_id} or false,
                health=sample.health,max_health=sample.max_health,
                is_dead=sample.is_dead,is_ghost=sample.is_ghost,
                is_in_combat=sample.is_in_combat,is_casting=sample.is_casting,
                player_present=sample.player_present,loading=sample.loading,
                input_blocked=sample.input_blocked,
                actionbar_fast=sample.actionbar_fast,
                combat_hint=sample.combat_hint and {spell_id=sample.combat_hint.spell_id,at=sample.combat_hint.at} or false,
            }
            text = encode(v)
        end
        if #text > 850 then
            -- The previous last-resort packet dropped mouseover and cursor
            -- together.  Under a normal, but field-rich Retail sample that
            -- made a visually successful hover invisible to INSPECT until a
            -- much later paged STATE completed.  Keep both control feedback
            -- and the bounded identity/cursor edge in the guaranteed core.
            -- Only pathological presentation strings are discarded.
            -- The *_sample_time copies of monotonic_time are omitted from
            -- here on (Python restores them) to make room for the position.
            v = {
                telemetry_lane="FAST_STATE",
                player_world_position=compactWorldPosition(sample.player_world_position),
                timestamp=sample.timestamp, monotonic_time=sample.monotonic_time,
                map_id=sample.map_id,
                map_context=sample.map_context and {
                    active_map_id=sample.map_context.active_map_id,
                    parent_map_id=sample.map_context.parent_map_id,
                    world_map_open=sample.map_context.world_map_open} or false,
                position=sample.position and {x=sample.position.x,y=sample.position.y} or false,
                orientation=sample.orientation, movement=sample.movement and {
                    speed=sample.movement.speed,moving=sample.movement.moving,
                    indoors=sample.movement.indoors} or false,
                target=sample.target and {guid=compactText(sample.target.guid,128),
                    name=compactText(sample.target.name,96),npc_id=sample.target.npc_id,
                    attackable=sample.target.attackable,dead=sample.target.dead} or false,
                mouseover=sample.mouseover and {
                    guid=compactText(sample.mouseover.guid,128),
                    name=compactMouseoverName(sample.mouseover,64),
                    npc_id=sample.mouseover.npc_id,
                    unit_type=compactText(sample.mouseover.unit_type,24),
                    structured_unit=sample.mouseover.structured_unit,
                    is_attackable=sample.mouseover.is_attackable,
                    is_dead=sample.mouseover.is_dead,
                    quest_related=sample.mouseover.quest_related,quest_id=sample.mouseover.quest_id,
                    identity_source=compactText(sample.mouseover.identity_source,32)} or false,
                cursor_position=sample.cursor_position and {
                    nx=sample.cursor_position.nx,ny=sample.cursor_position.ny} or false,
                quest_ui=sample.quest_ui and {open=sample.quest_ui.open,
                    action=sample.quest_ui.action,x=sample.quest_ui.x,y=sample.quest_ui.y,
                    quest_id=sample.quest_ui.quest_id} or false,
                extra_action=sample.extra_action and {visible=sample.extra_action.visible,
                    usable=sample.extra_action.usable,action=sample.extra_action.action,
                    action_type=sample.extra_action.action_type,action_id=sample.extra_action.action_id} or false,
                health=sample.health,max_health=sample.max_health,
                is_dead=sample.is_dead,is_ghost=sample.is_ghost,
                is_in_combat=sample.is_in_combat,is_casting=sample.is_casting,
                player_present=sample.player_present,loading=sample.loading,
                input_blocked=sample.input_blocked,
                actionbar_fast=sample.actionbar_fast,
                combat_hint=sample.combat_hint and {spell_id=sample.combat_hint.spell_id,at=sample.combat_hint.at} or false,
            }
            text = encode(v)
        end
        if #text > 850 and sample.is_in_combat then
            -- Live regression 2026-09-28: a field-rich hostile target pushed
            -- FAST through every generic fallback. The absolute inspection
            -- packet below intentionally omits combat/actionbar fields, so
            -- Python retained only the slower full snapshot, rejected every
            -- ability as cooldown_unknown, and resumed MOVE while attacked.
            -- In combat, survival/control facts outrank hover presentation.
            v = {
                telemetry_lane="FAST_STATE",
                player_world_position=compactWorldPosition(sample.player_world_position),
                monotonic_time=sample.monotonic_time, map_id=sample.map_id,
                orientation=sample.orientation,
                health=sample.health,max_health=sample.max_health,
                is_dead=sample.is_dead,is_ghost=sample.is_ghost,
                is_in_combat=sample.is_in_combat,is_casting=sample.is_casting,
                player_present=sample.player_present,input_blocked=sample.input_blocked,
                loading=sample.loading,
                movement=sample.movement and {
                    speed=sample.movement.speed,moving=sample.movement.moving,
                    indoors=sample.movement.indoors} or false,
                target=sample.target and {
                    guid=compactText(sample.target.guid,128),
                    npc_id=sample.target.npc_id,attackable=sample.target.attackable,
                    dead=sample.target.dead,health=sample.target.health,
                    max_health=sample.target.max_health} or false,
                actionbar_fast=sample.actionbar_fast,
                combat_hint=sample.combat_hint and {spell_id=sample.combat_hint.spell_id,at=sample.combat_hint.at} or false,
            }
            text = encode(v)
        end
        if #text > 850 then
            -- Absolute bounded edge packet.  This still retains the three
            -- signals needed by closed-loop control: motion, selected target,
            -- and simultaneous mouseover/cursor identity.  Normal Retail
            -- GUIDs and unit names fit; deliberately oversized strings are
            -- omitted by compactText rather than evicting the entire sensor.
            v = {
                telemetry_lane="FAST_STATE",
                player_world_position=compactWorldPosition(sample.player_world_position),
                monotonic_time=sample.monotonic_time, map_id=sample.map_id,
                map_context=sample.map_context and {
                    active_map_id=sample.map_context.active_map_id,
                    parent_map_id=sample.map_context.parent_map_id,
                    world_map_open=sample.map_context.world_map_open} or false,
                orientation=sample.orientation,
                movement=sample.movement and {
                    speed=sample.movement.speed,moving=sample.movement.moving,
                    indoors=sample.movement.indoors} or false,
                target=sample.target and {
                    guid=compactText(sample.target.guid,128),
                    name=compactText(sample.target.name,96),npc_id=sample.target.npc_id,
                    attackable=sample.target.attackable,dead=sample.target.dead} or false,
                mouseover=sample.mouseover and {
                    guid=compactText(sample.mouseover.guid,128),
                    name=compactMouseoverName(sample.mouseover,64),
                    npc_id=sample.mouseover.npc_id,
                    structured_unit=sample.mouseover.structured_unit,
                    is_attackable=sample.mouseover.is_attackable,
                    is_dead=sample.mouseover.is_dead,
                    quest_related=sample.mouseover.quest_related,quest_id=sample.mouseover.quest_id} or false,
                cursor_position=sample.cursor_position and {
                    nx=sample.cursor_position.nx,ny=sample.cursor_position.ny} or false,
                is_dead=sample.is_dead,is_ghost=sample.is_ghost,
                is_in_combat=sample.is_in_combat,player_present=sample.player_present,
                input_blocked=sample.input_blocked,loading=sample.loading,
            }
            text = encode(v)
        end
        if #text > 850 and not sample.is_in_combat then
            -- Final non-combat edge: retain the exact game-object name and
            -- pointer with movement/target control even in a rich sample.
            v = {
                telemetry_lane="FAST_STATE", monotonic_time=sample.monotonic_time,
                map_id=sample.map_id,
                player_world_position=compactWorldPosition(sample.player_world_position),
                orientation=sample.orientation,
                movement=sample.movement and {speed=sample.movement.speed,
                    moving=sample.movement.moving,indoors=sample.movement.indoors} or false,
                target=sample.target and {guid=compactText(sample.target.guid,128),
                    npc_id=sample.target.npc_id,attackable=sample.target.attackable,
                    dead=sample.target.dead} or false,
                mouseover=sample.mouseover and {
                    guid=compactText(sample.mouseover.guid,128),
                    name=compactMouseoverName(sample.mouseover,64),
                    quest_related=sample.mouseover.quest_related,
                    quest_id=sample.mouseover.quest_id} or false,
                cursor_position=sample.cursor_position and {
                    nx=sample.cursor_position.nx,ny=sample.cursor_position.ny} or false,
                is_dead=sample.is_dead,is_ghost=sample.is_ghost,
                is_in_combat=sample.is_in_combat,input_blocked=sample.input_blocked,
            }
            text = encode(v)
        end
        if #text <= 850 then
            if sourceTime ~= sample.monotonic_time then
                sourceTime=sample.monotonic_time
                sourceSequence=sourceSequence+1
            end
            return "AIPC5|" .. session .. "|" .. sourceSequence .. "|0|1|FAST|" .. text
        end
    end
    -- Every snapshot at least two full rounds: a page lost in the first is
    -- re-sent in the second and the assembler fills the gap.
    if #pages == 0 or (cursor == 1 and round >= 2 and stateTime ~= data.monotonic_time) then
        local v = {}
        for k,value in pairs(data) do
            if k ~= "heartbeat" and k ~= "latest_event" and k ~= "visible_units" then v[k]=value end
        end
        local encoded = encode(v)
        if #encoded > 128000 then error("AIPC snapshot exceeds 128KB; export refused without truncation") end
        stateKind = "STATE"
        -- Compress only already-sanitized JSON. Never pass secret API values to
        -- encoding functions. Missing compression support keeps the JSON path.
        if C_EncodingUtil and C_EncodingUtil.CompressString and C_EncodingUtil.EncodeBase64
            and Enum and Enum.CompressionMethod and Enum.CompressionMethod.Zlib then
            local ok, compressed = pcall(C_EncodingUtil.CompressString, encoded, Enum.CompressionMethod.Zlib)
            if ok and available(compressed) and type(compressed) == "string" then
                local baseOK, packed = pcall(C_EncodingUtil.EncodeBase64, compressed)
                if baseOK and available(packed) and type(packed) == "string" and #packed < #encoded then
                    encoded, stateKind = packed, "STATE_Z"
                end
            end
        end
        pages=split(encoded)
        sequence=sequence+1
        stateTime=data.monotonic_time
        round=0
        cursor=1
    end
    local result="AIPC5|" .. session .. "|" .. sequence .. "|" .. (cursor-1) .. "|" .. #pages .. "|" .. stateKind .. "|" .. pages[cursor]
    cursor=cursor+1
    if cursor > #pages then cursor=1; round=round+1 end
    return result
end
