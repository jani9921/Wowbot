"""Steady Flight on the character's own mount: capability gate and 3D plan.

User 2026-10-25: "first plain riding in the air, then vehicles in the air".
"""
import pytest

from wowbot.agent.flight_capability import can_fly, flight_blockers, flying_mount_action, on_flying_mount
from wowbot.navigation.flight_route import FlightPlan, plan_flight


class Geometry:
    """Flat ground at z=10 with a 40 yd high ridge at x 100-140 and a house
    (VMAPS roof at 25) at x 200-210; nothing known beyond x 900."""

    def supports(self, instance_id):
        return instance_id == 2444

    def terrain_height(self, instance_id, x, y):
        if x > 900:
            return None, False
        return (50. if 100 <= x <= 140 else 10.), False

    def vmap_surfaces_at(self, instance_id, point):
        return [25., 10.] if 200 <= point["x"] <= 210 else []

    def project_position(self, instance_id, point, z_hint=None):
        return {"x": point["x"], "y": point["y"], "z": 10.} if point["x"] <= 900 else None

    def walkable_points_near(self, instance_id, point, radius):
        return []


def test_the_plan_climbs_over_the_ridge_and_the_house_then_lands():
    plan, reason = plan_flight(Geometry(), 2444, {"x": 0., "y": 0., "z": 10.}, {"x": 400., "y": 0.})
    assert reason == "planned" and plan.distance == pytest.approx(400.)
    assert plan.landing == {"x": 400., "y": 0., "z": 10.}
    assert plan.target_z(0.) == pytest.approx(10. + 12.)          # flat start, ridge beyond 60 yd
    assert plan.target_z(60.) == pytest.approx(50. + 12.)         # the ridge is ahead
    assert plan.target_z(170.) == pytest.approx(25. + 12.)        # the roof is ahead
    assert plan.target_z(395.) < 15.                               # descending onto the landing
    assert plan.target_z(400.) == pytest.approx(10.)
    assert plan.along(250., 30.) == pytest.approx(250.)
    assert FlightPlan.from_dict(plan.to_dict()) == plan


def test_unknown_ground_or_no_landing_does_not_plan():
    assert plan_flight(Geometry(), 2444, {"x": 0., "y": 0.}, {"x": 1000., "y": 0.}) == (None, "no_landing_point")
    plan, reason = plan_flight(Geometry(), 2444, {"x": 850., "y": 0.}, {"x": 850., "y": 300.})
    assert reason == "planned"
    assert plan_flight(Geometry(), 2444, {"x": 0., "y": 0.}, {"x": 20., "y": 0.}) == (None, "too_short")
    assert plan_flight(Geometry(), 1, {"x": 0., "y": 0.}, {"x": 400., "y": 0.}) == (None, "no_world_geometry")


MOUNT_SLOT = {"slot": 13, "action": "MULTIACTIONBAR1BUTTON1", "binding_primary": "SHIFT-1", "kind": "summonmount",
              "id": 1589, "is_usable": True,
              "mount": {"mount_id": 1589, "mount_type_id": 402, "mount_collected": True, "mount_usable": True,
                        "mount_active": False}}


def flyable(**changes):
    state = {"flight": {"flyable_area": True, "gliding": False},
             "mount_capability": {"flying_riding_known": True},
             "movement": {"indoors": False, "flying": False},
             "actionbar": [dict(MOUNT_SLOT)], "is_mounted": False, "is_in_combat": False}
    state.update(changes)
    return state


def test_flying_needs_explicit_evidence_for_every_condition():
    assert can_fly(flyable()) and flying_mount_action(flyable())["action"] == "MULTIACTIONBAR1BUTTON1"
    assert "zone_not_flyable" in flight_blockers(flyable(flight={"flyable_area": False}))
    assert "flyable_area_unknown" in flight_blockers(flyable(flight={}))
    assert "no_flying_riding_skill" in flight_blockers(flyable(mount_capability={}))
    assert "indoors_or_unknown" in flight_blockers(flyable(movement={}))
    assert "skyriding_style_set_flight_style_to_steady" in flight_blockers(
        flyable(flight={"flyable_area": True, "gliding": True}))
    ground = dict(MOUNT_SLOT, mount={**MOUNT_SLOT["mount"], "mount_type_id": 230})
    assert "no_bound_flying_mount_on_actionbar" in flight_blockers(flyable(actionbar=[ground]))
    unbound = dict(MOUNT_SLOT, binding_primary="", binding_secondary="")
    assert "no_bound_flying_mount_on_actionbar" in flight_blockers(flyable(actionbar=[unbound]))


def test_the_active_mount_decides_whether_the_mounted_character_can_fly():
    active = dict(MOUNT_SLOT, mount={**MOUNT_SLOT["mount"], "mount_active": True})
    assert on_flying_mount(flyable(is_mounted=True, actionbar=[active]))
    assert can_fly(flyable(is_mounted=True, actionbar=[active]))
    assert "mounted_on_a_non_flying_mount" in flight_blockers(flyable(is_mounted=True))
    assert on_flying_mount(flyable(is_mounted=True, movement={"indoors": False, "flying": True}))


class Platform(Geometry):
    """The destination at z 95 under a platform roof (z 183-188) within 12 yd;
    an open spot on the same layer 23 yd away (live 2026-10-26 17:22-17:34)."""

    def terrain_height(self, instance_id, x, y):
        return 95., False

    def vmap_surfaces_at(self, instance_id, point):
        return [188.5, 182.75] if abs(point["x"]-1107.) < 14 else []

    def project_position(self, instance_id, point, z_hint=None):
        return {"x": point["x"], "y": point["y"], "z": 95.7}

    def walkable_points_near(self, instance_id, point, radius):
        near = [{"x": 1112., "y": 372., "z": 95.1}]
        return near + ([{"x": 1084., "y": 372., "z": 94.3}] if radius > 20 else [])


def test_a_covered_destination_lands_on_an_open_spot_of_its_layer_nearby():
    plan, reason = plan_flight(Platform(), 2444, {"x": 1300., "y": 372., "z": 185.6},
                               {"x": 1107., "y": 372., "z": 95., "z_known": True})
    assert reason == "planned" and plan.landing == {"x": 1084., "y": 372., "z": 94.3}
