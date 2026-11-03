"""Import/construction boundaries, not a live quest claim."""
import os
import subprocess
import sys
from pathlib import Path

from wowbot.agent.engine import AutonomousAgent
from wowbot.agent.executor import RecordingExecutor
from wowbot.agent.models import Observation, Mode
from wowbot.runtime_profile import RuntimeProfile


def test_full_server_runtime_constructs_and_closes_with_detector_and_tracker_imports_forbidden(tmp_path):
    code = '''
import importlib.abc, sys
class Block(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        forbidden = ('torch', 'ultralytics', 'cv2', 'wowbot.agent.perception',
                     'wowbot.vision.world3d.tracking', 'wowbot.vision.world3d.candidate_tracker',
                     'wowbot.vision.world3d.learned_detector', 'wowbot.vision.world3d.v3')
        if any(fullname == x or fullname.startswith(x+'.') for x in forbidden):
            raise AssertionError('forbidden runtime dependency: '+fullname)
sys.meta_path.insert(0, Block())
from pathlib import Path
from wowbot.agent.runtime import AgentRuntime
from wowbot.agent.executor import RecordingExecutor
class Sensor:
    frame = None
    health = 'offline'
    def poll(self, now): return None
runtime = AgentRuntime(77, None, Path(sys.argv[1]), sensor=Sensor(),
                       executor=RecordingExecutor(), runtime_profile='SERVER')
assert runtime.perception is None and runtime.vision_dataset is None
assert runtime.agent.search_skill is None and runtime.agent.visual_approach is None
assert runtime.agent.status(10.)['vision_seek']['status'] == 'disabled'
runtime.close()
print('server runtime isolated')
'''
    env = {**os.environ, 'PYTHONPATH': str(Path(__file__).parents[1]/'src'),
           'AIPC_SEMANTIC_ENABLED': '0', 'AIPC_REFERENCE_CATALOG': str(tmp_path/'absent.sqlite3')}
    result = subprocess.run([sys.executable, '-B', '-c', code, str(tmp_path/'runtime')],
                            env=env, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout+result.stderr
    assert 'server runtime isolated' in result.stdout


def test_server_world_rejects_visual_observations_and_profile_survives_session_reset():
    agent = AutonomousAgent(RecordingExecutor(), runtime_profile='SERVER')
    for session in ('a', 'b'):
        agent.world.ingest(Observation.create({'session_id': session, 'frame_id': session,
            'target': {'guid': 'Creature-1'}, 'visual_candidates': [{'track_id': 'old'}]}, 10.))
        assert agent.world.runtime_profile is RuntimeProfile.SERVER
        assert agent.world.state['server_mode']['selected'] is True
        assert 'visual_candidates' not in agent.world.state
        assert not agent.world.ingest(Observation.create({'session_id': session, 'frame_id': 'v',
            'visual_candidates': [{'track_id': 'new'}]}, 11., 'WORLD3D'))
    agent.set_mode(Mode.MANUAL)
    assert agent.search_skill is None and agent.visual_approach is None


def test_server_default_sensor_decodes_real_bgra_strip_without_vision_dependencies(tmp_path):
    # Replace only the OS pixel source. Sensor selection, threaded buffering,
    # AIPC5 grid decoding/reassembly and runtime ingestion remain production code.
    code = '''
import importlib.abc, json, sys, time
class Block(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        forbidden = ('torch', 'ultralytics', 'cv2', 'wowbot.agent.perception',
                     'wowbot.vision.world3d.tracking', 'wowbot.vision.world3d.candidate_tracker',
                     'wowbot.vision.world3d.learned_detector', 'wowbot.vision.world3d.v3')
        if any(fullname == x or fullname.startswith(x+'.') for x in forbidden):
            raise AssertionError('forbidden transport dependency: '+fullname)
sys.meta_path.insert(0, Block())
from pathlib import Path
sys.path.insert(0, str(Path(sys.argv[2])/'tests'))
from test_pixel_strip_resolution_profiles import frame
from wowbot.agent import capture_selection
from wowbot.agent.runtime import AgentRuntime
from wowbot.agent.executor import RecordingExecutor
class PixelSource:
    def __init__(self, pid, backend):
        assert pid == 77 and backend is sink.backend
        self.current = None
    def capture(self): return self.current
class PassiveBackend:
    def emergency_pressed(self): return False
sink = RecordingExecutor()
sink.backend = PassiveBackend()
capture_selection.ClientCapture = PixelSource
runtime = AgentRuntime(77, None, Path(sys.argv[1]), executor=sink, runtime_profile='SERVER')
pixel = runtime.sensor.source
assert type(pixel).__name__ == 'PixelSensor'
def publish(sequence, kind, value):
    before = pixel.published_updates
    wire = 'AIPC5|synthetic|%d|0|1|%s|%s' % (sequence, kind, json.dumps(value, separators=(',', ':')))
    pixel.capture.current = (frame(1024, 768, wire), 1024, 768)
    deadline = time.monotonic()+5.
    while pixel.published_updates <= before:
        assert time.monotonic() < deadline, pixel.health
        time.sleep(.005)
    runtime.step(time.monotonic())
try:
    runtime.sensor.start()
    publish(1, 'STATE', {'character_guid':'Player-1-1234', 'character_name':'Offline',
        'addon_version':'0.9.80', 'monotonic_time':100., 'timestamp':12345,
        'health':100, 'max_health':120, 'power':20, 'max_power':100, 'power_type':1,
        'map_id':1409, 'active_quests':[], 'inventory':{'items':[]}})
    assert runtime.agent.world.state['health'] == 100
    assert runtime.agent.world.state['power'] == 20
    publish(2, 'FAST', {'monotonic_time':100.1, 'health':95, 'max_health':120,
                         'power':25, 'max_power':100, 'power_type':1})
    assert runtime.agent.world.state['health'] == 95
    assert runtime.agent.world.state['power'] == 25
    assert runtime.agent.world.state['health_sample_time'] == 100.1
    assert runtime.agent.world.state['power_sample_time'] == 100.1
    assert pixel.completed_full_states == 1 and pixel.fresh_fast_packets == 1
    assert runtime.perception is None and runtime.vision_dataset is None
    assert runtime.agent.mode.value == 'MANUAL' and not sink.commands
finally:
    runtime.close()
assert runtime.sensor._sensors['telemetry'].thread is None or not runtime.sensor._sensors['telemetry'].thread.is_alive()
print('server BGRA transport isolated')
'''
    root = Path(__file__).parents[1]
    env = {**os.environ, 'PYTHONPATH': str(root/'src'),
           'AIPC_CAPTURE_PROCESS': '0', 'AIPC_CAPTURE_BACKEND': 'gdi',
           'AIPC_PACKET_TELEMETRY': '0', 'AIPC_SEMANTIC_ENABLED': '0',
           'AIPC_REFERENCE_CATALOG': str(tmp_path/'absent.sqlite3')}
    result = subprocess.run([sys.executable, '-B', '-c', code, str(tmp_path/'runtime'), str(root)],
                            env=env, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout+result.stderr
    assert 'server BGRA transport isolated' in result.stdout


def test_common_coordinate_values_keep_legacy_import_identity():
    from wowbot.coordinates import PixelRect, ScreenPoint, BearingEstimate
    from wowbot.vision.world3d.models import PixelRect as OldRect, ScreenPoint as OldPoint
    assert OldRect is PixelRect and OldPoint is ScreenPoint
    assert PixelRect(1, 2, 5, 8).to_dict()['coordinate_space'] == 'SCREEN_PIXELS'
    assert BearingEstimate(0., 0., 1.).to_dict()['coordinate_space'] == 'CAMERA_RELATIVE_BEARING'
