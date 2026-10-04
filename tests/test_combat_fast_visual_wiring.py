from types import SimpleNamespace

from wowbot.agent.runtime_perception_phase import update_runtime_perception


class RecordingPerception:
    def __init__(self):
        self.geometry = None

    def update(self, frame, now, *, allow, geometry, context, world_map_open):
        self.geometry = geometry
        return []


def test_active_combat_requests_fast_visual_servo_tracking_profile():
    perception = RecordingPerception()
    runtime = SimpleNamespace(
        perception=perception,
        sensor=SimpleNamespace(frame=object()),
        agent=SimpleNamespace(
            world=SimpleNamespace(state={}),
            pending=SimpleNamespace(proposal=SimpleNamespace(skill="COMBAT")),
            planner=SimpleNamespace(map_zoom_count=0),
        ),
    )

    update_runtime_perception(runtime, {"transport_kind": "FAST"}, 1.)

    assert perception.geometry["fast_visual_servo"] is True
    assert perception.geometry["navigation_active"] is False
