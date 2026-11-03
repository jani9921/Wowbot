from pathlib import Path
import json, statistics, sys, time
sys.path.insert(0,sys.argv[1])
from wowbot.agent.models import Observation
from wowbot.agent.world import WorldModel
world=WorldModel()
timings=[]
for i in range(260):
 at=100.+i/30.
 started=time.perf_counter_ns()
 payload={"session_id":"perf", "frame_id":f"frame:{i}", "timestamp":at, "monotonic_time":at,
          "map_id":2022, "player_present":True, "game_build":"69587", "character_guid":"Player-1602-00001234",
          "player_world_position":{"x":i*.1,"y":0.,"z":10.,"z_known":True,"instance_id":2444,"coordinate_space":"WORLD_YARDS"},
          "position":{"x":.5+i*.00001,"y":.5}, "orientation":.1,"movement":{"moving":True},
          "target":None,"mouseover":None,"active_quests":[],"health":100,"max_health":100}
 parent=Observation.create(payload,at);world.ingest(parent)
 derived=Observation.create({"session_id":"perf","frame_id":parent.correlation_id,"timestamp":at,
     "marker":"A","provenance":{"parent_observation_id":parent.observation_id,
     "root_observation_ids":[parent.observation_id],"observed_at_monotonic":at,
     "independence_group":parent.observation_id}},at+.002,"WORLD3D")
 world.ingest(derived)
 world.belief("marker",at+.002);world.belief("player_world_position",at+.002)
 if i%10==0:world.snapshot(at+.002)
 if i>=40:timings.append((time.perf_counter_ns()-started)/1e6)
ordered=sorted(timings)
print(json.dumps({"samples":len(timings),"median_ms":statistics.median(timings),"p95_ms":ordered[int(.95*(len(ordered)-1))],"snapshot_bytes":len(json.dumps(world.snapshot(at+.002),ensure_ascii=False).encode("utf-8"))}))
