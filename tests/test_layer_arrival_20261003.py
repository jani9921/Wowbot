"""Arrival is layer-aware (design doc §4: standing on a bridge above the target)."""
from wowbot.agent.movement_controller import ReachMovementController


def _controller(layer_z):
    controller = ReachMovementController.__new__(ReachMovementController)
    controller.destination = {"x": 10., "y": 0., "coordinate_space": "WORLD_YARDS", "layer_z": layer_z}
    return controller


def _state(z, source="NAVMESH_SURFACE"):
    return {"player_world_position": {"x": 10., "y": 0., "z": z, "z_source": source}}


def test_same_xy_on_another_layer_is_not_arrival():
    assert _controller(60.)._vertical_excess(_state(75.)) == 13.          # bridge 15 yd above
    assert _controller(60.)._vertical_excess(_state(61.5)) == 0.          # slope / step


def test_untrusted_heights_never_block_arrival():
    assert _controller(60.)._vertical_excess(_state(0., source="CLIENT")) == 0.   # false Z=0
    assert _controller(None)._vertical_excess(_state(75.)) == 0.
