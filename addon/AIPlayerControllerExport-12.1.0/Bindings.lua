-- Read-only catalog. Never calls SetBinding/SaveBindings or inspects secrets.
local _, ns = ...
local catalog, revision, pageCursor
local function public(v)
    return not (issecretvalue and issecretvalue(v)) and not (canaccessvalue and not canaccessvalue(v))
end
local function read(fn, ...)
    if type(fn) ~= "function" then return nil end
    local ok, value = pcall(fn, ...)
    if ok and public(value) then return value end
end
function ns.InvalidateBindings() catalog = nil end
local function scan()
    local count = read(GetNumBindings)
    if type(count) ~= "number" or count < 0 or count > 10000 then return false end
    local rows = {}
    for i = 1, count do
        local ok, action, category, key1, key2 = pcall(GetBinding, i)
        if not ok or not public(action) or not public(category) or not public(key1) or not public(key2) then return false end
        if type(action) ~= "string" then return false end
        local normalContext = Enum and Enum.BindingContext and Enum.BindingContext.None
        local function normalAction(key)
            if type(key) ~= "string" or key == "" or normalContext == nil then return "" end
            local value = read(GetBindingAction, key, false, normalContext)
            return type(value)=="string" and value or ""
        end
        rows[#rows+1] = {action=action, category=type(category)=="string" and category or "",
                         primary=type(key1)=="string" and key1 or "", secondary=type(key2)=="string" and key2 or "",
                         normal_primary_action=normalAction(key1), normal_secondary_action=normalAction(key2)}
    end
    catalog = rows
    revision = (revision or 0)+1
    pageCursor = 0
    AIPlayerControllerExportDB = AIPlayerControllerExportDB or {}
    AIPlayerControllerExportDB.binding_catalog = {rows=rows, revision=revision,
        binding_set=read(GetCurrentBindingSet), character_guid=read(UnitGUID,"player"),
        source="GET_BINDING", saved_at=read(GetServerTime)}
    return true
end
function ns.BindingCatalogPage()
    if not catalog and not scan() then return {status="unavailable"} end
    local total = math.max(1, math.ceil(#catalog/16))
    -- Advance exactly one page per call rather than deriving it from
    -- elapsed wall-clock time: BindingCatalogPage() is itself only invoked
    -- as part of the slow/paged snapshot builder (irregular ~0.3-1Hz
    -- cadence -- AIPlayerControllerExport.lua's binding_catalog_page
    -- field), so a time-based page index could skip pages entirely (two
    -- calls landing more than one 3s window apart) or repeat the same page
    -- for several calls in a row (calls landing close together) -- a
    -- "coupon collector" problem with no guarantee of ever completing.
    -- Live-confirmed 2026-09-12: binding-catalog export stalled partway
    -- (22/23, then 19/23 on a separate run, neither involving a fresh
    -- keybind change to explain the reset) without ever finishing.
    -- Advancing by exactly one page per call instead guarantees full
    -- coverage after `total` calls, with no possibility of a page being
    -- skipped, regardless of how irregular the read cadence is.
    local page = (pageCursor or 0) % total
    pageCursor = page + 1
    local rows = {}
    for i=page*16+1, math.min(#catalog,(page+1)*16) do rows[#rows+1]=catalog[i] end
    return {status="ok", revision=revision, page=page, pages=total, count=#catalog,
            binding_set=read(GetCurrentBindingSet), rows=rows, source="GET_BINDING"}
end
