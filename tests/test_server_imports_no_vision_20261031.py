"""REV4 visual retirement (P4 audit 6.4/6.5 prerequisite): the SERVER path
loads no wowbot.vision module, no legacy visual navigation module and no
numpy/OpenCV/torch, so the vision package can later go without touching it.

The addon-confirmed entity memory, the addon tooltip/map-mouseover parser and
the minimap offset geometry were never vision; they moved out of the package
and its old modules re-export the very same objects."""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROBE = r"""
import importlib, json, sys
sys.path.insert(0, sys.argv[1])
for name in ("wowbot.agent.engine", "wowbot.agent.runtime", "wowbot.agent.world", "wowbot.agent.planner",
             "wowbot.navigation.service", "wowbot.agent.skills", "wowbot.skills",
             "wowbot.execution.command_dispatch", "wowbot.agent.gui"):
    importlib.import_module(name)
from wowbot.runtime_profile import RuntimeProfile
from wowbot.agent.world import WorldModel
from wowbot.agent.models import Goal, Observation
from wowbot.agent.planner import Planner
from wowbot.agent.skills import SkillRegistry
world = WorldModel(runtime_profile=RuntimeProfile.SERVER)
world.ingest(Observation.create({"session_id": "t:p", "timestamp": 1., "frame_id": "f", "map_id": 1409,
    "world_map_open": False, "position": {"x": .5, "y": .5}, "orientation": 0., "player_present": True,
    "is_in_combat": False, "is_casting": False, "target": {}, "active_quests": []}, 1.))
Planner(SkillRegistry()).candidates(Goal.parse("Questelj", 1.), world, 1.)
print(json.dumps({"profile": world.state.get("runtime_profile"), "modules": sorted(sys.modules)}))
"""
LEGACY_NAVIGATION = {"wowbot.navigation.engine", "wowbot.navigation.graph_builder", "wowbot.navigation.local",
                     "wowbot.navigation.spatial_context", "wowbot.navigation.local_world_bridge"}


def test_the_server_path_loads_no_vision_module():
    run = subprocess.run([sys.executable, "-I", "-c", PROBE, str(ROOT / "src")],
                         capture_output=True, text=True, timeout=120, check=True)
    result = json.loads(run.stdout.strip().splitlines()[-1])
    assert result["profile"] == "SERVER"
    modules = set(result["modules"])
    assert sorted(m for m in modules if m == "wowbot.vision" or m.startswith("wowbot.vision.")) == []
    assert sorted(modules & LEGACY_NAVIGATION) == []
    assert sorted(modules & {"numpy", "cv2", "torch", "ultralytics", "onnxruntime"}) == []


def test_the_moved_values_are_the_same_objects():
    from wowbot import coordinates, entity_memory, map_mouseover
    from wowbot.vision import entity_memory as old_memory, map_mouseover as old_mouseover
    from wowbot.vision.minimap_quest_area import offsets_to_world
    assert old_memory.EntityMemory is entity_memory.EntityMemory
    assert old_memory.EntityMemoryProfile is entity_memory.EntityMemoryProfile
    assert old_mouseover.classify_tooltip is map_mouseover.classify_tooltip
    assert old_mouseover.normalize_map_mouseover is map_mouseover.normalize_map_mouseover
    assert old_mouseover.MapMouseover is map_mouseover.MapMouseover
    assert offsets_to_world is coordinates.offsets_to_world
    # Log filters and tests key on the historical logger name.
    assert entity_memory._logger.name == "wowbot.vision.entity_memory"
