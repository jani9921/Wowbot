from pathlib import Path
from types import SimpleNamespace
import pytest
from wowbot.agent.models import Observation, Goal, Proposal
from wowbot.agent.world import WorldModel
from wowbot.agent.planner import Planner
from wowbot.agent.skills import SkillRegistry
from wowbot.skills.quest_item import UseItemSkill


def snapshot(at=10., *, complete='COMPLETE', quests=None, **changes):
    return {'session_id': 's', 'frame_id': str(at), 'monotonic_time': at,
            'player_present': True, 'active_quests': quests if quests is not None else [
                {'quest_id': 7, 'objectives': [{'description': 'Collect', 'type': 'COLLECT', 'current': 0, 'required': 1}]}],
            'collection_coverage': {'active_quests': complete, 'inventory': complete},
            'inventory': {'items': []}, **changes}


def test_partial_empty_list_never_erases_existing_quest_or_claims_absence():
    world = WorldModel()
    world.ingest(Observation.create(snapshot(), 10.))
    world.ingest(Observation.create(snapshot(11., complete='UNKNOWN', quests=[]), 11.))
    assert world.quest_model.records[7].current_state == 'ACTIVE'
    assert world.state['active_quests'][0]['quest_id'] == 7
    proposal = Planner(SkillRegistry()).candidates(Goal.parse('Questelj', 10.), world, 11.)[0]
    assert proposal.skill == 'WAIT' and proposal.parameters['reason'] == 'questlog_baseline_incomplete'
    world.ingest(Observation.create(snapshot(12., quests=[]), 12.))
    assert world.quest_model.records[7].current_state == 'ABSENT'
    assert world.query.field_resolution('active_quests', 12.).value == []


def test_partial_members_update_but_other_quests_remain_known_without_being_resampled():
    world = WorldModel()
    world.ingest(Observation.create(snapshot(), 10.))
    world.ingest(Observation.create(snapshot(11., complete='PARTIAL', quests=[{'quest_id': 8, 'objectives': []}]), 11.))
    assert set(world.quest_model.records) == {7, 8}
    assert world.quest_model.records[7].last_updated_at == 10.


def test_inventory_partial_blocks_coordinate_item_and_vendor_inputs():
    world = WorldModel()
    world.ingest(Observation.create(snapshot(complete='PARTIAL'), 10.))
    assert world.state['inventory']['complete'] is False
    assert UseItemSkill.resolve_inventory_item(world.state, {'activation_source': 'INVENTORY_COORDINATE'}) is None
    assert not SkillRegistry().available(Proposal.make('SELL_VENDOR', 'sell'), world)


def test_missing_objective_list_is_not_a_completed_objective_or_a_new_empty_record():
    world = WorldModel()
    world.ingest(Observation.create(snapshot(), 10.))
    world.ingest(Observation.create(snapshot(11., quests=[{'quest_id': 7, 'objectives': [], 'objectives_coverage': 'UNKNOWN'}]), 11.))
    assert world.quest_model.records[7].objectives


def test_new_fast_revision_cannot_certify_old_state_quest_collection():
    world = WorldModel()
    full = snapshot(quest_state_revision=1)
    full['collection_coverage']['quest_revision'] = 1
    world.ingest(Observation.create(full, 10.))
    world.ingest(Observation.create({'session_id': 's', 'frame_id': 'fast-2', 'transport_kind': 'FAST',
                                    'monotonic_time': 11., 'quest_state_revision': 2}, 11.))
    assert world.state['collection_coverage']['active_quests'] == 'PARTIAL'
    assert world.quest_model.records[7].current_state == 'ACTIVE'


@pytest.mark.parametrize('broken', [None, 'not-a-list', {'quest_id': 99}, [None]])
def test_malformed_complete_collection_cannot_erase_quest_membership(broken):
    world = WorldModel()
    world.ingest(Observation.create(snapshot(), 10.))
    world.ingest(Observation.create(snapshot(11., active_quests=broken), 11.))
    assert world.quest_model.records[7].current_state == 'ACTIVE'
    assert world.state['active_quests'][0]['quest_id'] == 7
    assert world.state['collection_coverage']['active_quests'] == 'UNKNOWN'


def test_missing_inventory_cannot_be_certified_complete_by_a_detached_coverage_flag():
    world = WorldModel()
    world.ingest(Observation.create(snapshot(inventory=None), 10.))
    assert world.state['inventory']['complete'] is False
    assert world.state['collection_coverage']['inventory'] == 'UNKNOWN'


def test_old_inventory_snapshot_cannot_authorize_a_bag_coordinate_click():
    from wowbot.agent.collection_coverage import inventory_ready
    assert not inventory_ready({'monotonic_time': 20., 'inventory': {'complete': True, 'sample_time': 10.}})
    assert inventory_ready({'monotonic_time': 11., 'inventory': {'complete': True, 'sample_time': 10.}})


def test_lua_producer_distinguishes_empty_complete_partial_and_unavailable_questlog():
    lupa = pytest.importorskip('lupa')
    source = (Path(__file__).parents[1]/'addon/AIPlayerControllerExport/AIPlayerControllerExport.lua').read_text(encoding='utf-8')
    function = source[source.index('local function readQuests()'):source.index('local function readQuestText(')]
    prelude = '''
local collectionCoverage = {}
local function accessible(v) return v ~= nil end
local function safeCall(f, ...) if not f then return nil end local ok,v=pcall(f,...); if ok then return v end end
local function safeNumber(v, default) return type(v)=="number" and v or default end
local function safeText(v, default) return type(v)=="string" and v or default or "" end
local function bool(v) return v == true end
'''
    result = lupa.LuaRuntime().execute(prelude+function+'''
local first=readQuests(); local unknown=collectionCoverage.active_quests
C_QuestLog={GetNumQuestLogEntries=function() return 0 end}
local second=readQuests(); local complete=collectionCoverage.active_quests
C_QuestLog={GetNumQuestLogEntries=function() return 1 end, GetInfo=function() return nil end}
local third=readQuests(); return unknown,complete,collectionCoverage.active_quests,#first,#second,#third
''')
    assert result == ('UNKNOWN', 'COMPLETE', 'PARTIAL', 0, 0, 0)


@pytest.mark.parametrize('backend', ['lua51', 'luajit21', 'lua54'])
def test_lua_both_complete_addon_files_compile_without_running_client_code(backend):
    lupa = pytest.importorskip('lupa.'+backend)
    lua = lupa.LuaRuntime()
    compile_only = lua.eval('function(code) local fn,err=(loadstring or load)(code); return fn ~= nil, err end')
    root = Path(__file__).parents[1]/'addon'
    for name in ('AIPlayerControllerExport', 'AIPlayerControllerExport-12.1.0'):
        for path in (root/name).glob('*.lua'):
            ok, error = compile_only(path.read_text(encoding='utf-8'))
            assert ok, (path.name, error)


def test_complete_toc_load_registers_aipc_command_in_lua51_without_client_input():
    lupa = pytest.importorskip('lupa.lua51')
    lua = lupa.LuaRuntime()
    lua.execute('''
GetServerTime=function() return 1000 end
GetTime=function() return 10 end
UIParent={}; SlashCmdList={}
function CreateFrame()
    return {SetOwner=function() end, RegisterEvent=function() end, SetScript=function() end}
end
''')
    package = Path(__file__).parents[1]/'addon/AIPlayerControllerExport'
    namespace = lua.table()
    load_chunk = lua.eval('function(s) local f,e=loadstring(s); assert(f,e); return f end')
    toc = (package/'AIPlayerControllerExport.toc').read_text(encoding='utf-8')
    for line in toc.splitlines():
        if line.strip().endswith('.lua'):
            load_chunk((package/line.strip()).read_text(encoding='utf-8'))('AIPlayerControllerExport', namespace)
    assert lua.globals().SLASH_AIPCEXPORT1 == '/aipc'
    assert lua.eval('type(SlashCmdList.AIPCEXPORT)') == 'function'
