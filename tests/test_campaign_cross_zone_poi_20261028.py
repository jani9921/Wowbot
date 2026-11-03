from copy import deepcopy
from types import SimpleNamespace

from test_server_quest_poi_20261028 import scene,event,ready,newer
from test_packet_agent_bridge import bridge,deliver
from wowbot.agent.quest_poi_evidence import server_turnin_poi
from wowbot.agent.quest_location_planning import QuestLocationPlanningPolicy
from wowbot.navigation.contracts import NavigationRequest
from wowbot.navigation.global_planner import GlobalNavigator
from wowbot.navigation.mmap_navmesh import NavMeshPath


def test_neighboring_ui_zone_in_the_same_world_keeps_the_server_campaign_endpoint(bridge):
    ready(bridge);deliver(bridge,event());newer(bridge)
    state=deepcopy(bridge.world.state)
    blob=state['packet_quest_pois']['65793']['blobs'][0]
    blob['ui_map_id']=2023
    blob['points'][0].update(x=214,y=934,z=352)
    point=server_turnin_poi(state,65793)
    assert point['map_id']==2023 and point['instance_id']==2444 and point['z']==352.
    record=SimpleNamespace(quest_id=65793,current_state='COMPLETED',known_locations=[])
    proposal=QuestLocationPlanningPolicy().propose_turnins({65793:record},state,{})[0]
    assert proposal.parameters['knowledge_priority']=='SERVER_POI'
    blob['world_map_id']=2175
    assert server_turnin_poi(state,65793) is None


class Geometry:
    def find_path(self,instance,start,end):return NavMeshPath((start,end),1,1,10.)


def test_a_cross_zone_ground_route_does_not_replan_every_tick_before_the_boundary():
    state=scene();state.update(map_id=2022,monotonic_time=10.)
    destination={'x':214.,'y':934.,'z':352.,'z_known':True,'map_id':2023,
        'instance_id':2444,'coordinate_space':'WORLD_YARDS','require_navmesh':True}
    request=NavigationRequest('cross-zone','same-action','MOVE_TO_LOCATION',destination)
    planner=GlobalNavigator(navmesh=Geometry());route=planner.plan(request,state,10.)
    assert route.regions[0]['destination_ui_map_id']==2023
    assert not planner.needs_replan(route,request,state,11.)
    state['map_id']=2023
    assert planner.needs_replan(route,request,state,12.)
    updated=planner.plan(request,state,12.)
    assert not planner.needs_replan(updated,request,state,13.)
