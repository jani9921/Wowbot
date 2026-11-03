"""Design spec 30.1: the Travel system chooses the mode by comparing candidate
trips with explicit legs (GROUND / MOUNTED_GROUND / FLIGHT / MIXED), scored
in declared estimate seconds; infeasible candidates keep typed blockers."""
from wowbot.navigation.travel_planner import TravelOptions, TravelPlanner


def plan(yards, **options):
    return TravelPlanner().plan(yards, TravelOptions(**options))


def test_short_hops_walk_long_ones_ride_with_explicit_legs():
    assert plan(30.).mode == "GROUND"
    ride = plan(120.)
    assert ride.mode == "MOUNTED_GROUND" and ride.chosen.legs == ("MOUNT", "RIDE", "DISMOUNT")
    assert plan(120., mount_blockers=("indoors",)).mode == "GROUND"


def test_flight_wins_far_trips_and_is_the_only_way_to_an_unreachable_height():
    far = plan(400., flight_style="SKYRIDING", flight_blockers=())
    assert far.mode == "FLIGHT" and far.chosen.legs == ("MOUNT", "TAKEOFF", "FLIGHT", "LAND", "GROUND")
    near = plan(30., flight_style="STEADY", flight_blockers=())
    assert near.mode == "GROUND"
    up = plan(30., flight_style="STEADY", flight_blockers=(), ground_unreachable="target_height_needs_flight")
    assert up.mode == "FLIGHT"
    blocked = {c.mode: c for c in up.candidates}["GROUND"]
    assert not blocked.feasible and blocked.blockers == ("target_height_needs_flight",)


def test_mixed_trip_walks_to_open_sky_first_and_failures_cost():
    mixed = plan(500., flight_style="SKYRIDING", flight_blockers=(), needs_open_sky_walk=True,
                 open_sky_walk_yards=20.)
    assert mixed.mode == "MIXED" and mixed.chosen.legs[0] == "GROUND"
    fresh = plan(60., mounted=True, flight_style="SKYRIDING", flight_blockers=())
    failed = plan(60., mounted=True, flight_style="SKYRIDING", flight_blockers=(), flight_failed_recently=True)
    assert {c.mode: c for c in failed.candidates}["FLIGHT"].risk_seconds > 0
    assert fresh.snapshot()["units"] == "ESTIMATED_SECONDS"


def test_danger_on_the_ground_route_counts():
    calm = plan(60.)
    risky = plan(60., ground_danger_seconds=30.)
    assert calm.mode == "MOUNTED_GROUND"
    walk = {c.mode: c for c in risky.candidates}["GROUND"]
    assert walk.danger_seconds == 30. and risky.mode == "MOUNTED_GROUND"
