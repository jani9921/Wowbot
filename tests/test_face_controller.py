import pytest

from wowbot.navigation.facing import FaceController, FaceStatus


class _Bindings:
    def __init__(self, actions=("TURNLEFT", "TURNRIGHT")):
        self.actions = set(actions)

    def contains(self, action):
        return action in self.actions


def test_face_controller_uses_bounded_turn_and_hysteresis():
    controller = FaceController(_Bindings())
    right = controller.face_screen_x(.8)
    assert right.status is FaceStatus.ADJUSTING and right.commands[0].binding == "TURNRIGHT"
    assert controller.face_screen_x(.51).status is FaceStatus.ALIGNED
    # Retained alignment uses the wider exit band and cannot chatter at .53.
    assert controller.face_screen_x(.53).status is FaceStatus.ALIGNED
    assert controller.face_screen_x(.56).status is FaceStatus.ADJUSTING


def test_face_controller_fails_closed_for_missing_turn_binding_or_lost_target():
    assert FaceController(_Bindings(())).face_screen_x(.8).status is FaceStatus.FAILED
    assert FaceController().face_screen_x(None).status is FaceStatus.TARGET_LOST


def test_face_controller_full_lifecycle_and_timeout():
    controller = FaceController(_Bindings())
    controller.begin({"guid": "Creature-1"}, 10., timeout=1.)
    assert controller.tick({"screen_position": {"x": .7}}, 10.2).status is FaceStatus.ADJUSTING
    assert controller.tick({"screen_position": {"x": .51}}, 10.4).status is FaceStatus.ALIGNED
    assert controller.is_aligned()
    assert controller.tick({"screen_position": {"x": .51}}, 11.1).reason == "facing_timeout"
    assert not controller.is_aligned()


def test_face_controller_estimation_and_cancel_are_input_free():
    controller = FaceController(_Bindings())
    controller.begin({"track_id": "WORLD3D:1"}, 1.)
    assert controller.estimate_error({"x": .4}) == pytest.approx(-.1)
    controller.cancel()
    assert not controller.is_aligned()


def test_default_facing_recovery_timeout_is_1800ms():
    controller = FaceController(_Bindings())
    controller.begin({"guid": "Creature-1"}, 10.)
    assert controller.tick({"screen_position": {"x": .8}}, 11.79).status is FaceStatus.ADJUSTING
    assert controller.tick({"screen_position": {"x": .8}}, 11.81).reason == "facing_timeout"
