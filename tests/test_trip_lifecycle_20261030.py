from dataclasses import replace
from wowbot.navigation.contracts import NavigationRequest, ArrivalEnvelope, GlobalRoute
from wowbot.navigation.travel import TravelRequest, TripExecutor, TripStatus, TransitionSystem
from wowbot.navigation.service import NavigationService
from wowbot.agent.movement_controller import MovementAssessment, MovementPhase


def request(**changes):
    dest = {'x': 10., 'y': 0., 'z': 100., 'z_known': True, 'coordinate_space': 'WORLD_YARDS',
            'instance_id': 2444, 'objective_id': '7:1', **changes}
    return NavigationRequest('travel-1', 'observation-1', 'MOVE_TO_LOCATION', dest,
                             arrival=ArrivalEnvelope(radius=3.))


def state(*, x=10., z=100., at=10., **changes):
    return {'monotonic_time': at, 'orientation': 0., 'movement': {'flying': False, 'falling': False},
            'player_world_position': {'x': x, 'y': 0., 'z': z, 'z_known': True, 'sample_time': at,
                                      'instance_id': 2444, 'coordinate_space': 'WORLD_YARDS'}, **changes}


def test_original_semantic_goal_survives_horizon_and_ground_handoffs_and_dict_mutation():
    original = request()
    trip = TripExecutor()
    trip.start(original, 10.)
    original.destination['x'] = 999.
    ground = replace(original, request_id='travel-1:ground', destination={**original.destination, 'x': 8.})
    trip.start(ground, 12., continuing=True)
    assert trip.request.destination['x'] == 10. and trip.request.goal_id == '7:1'
    assert trip.started_at == 10.
    assert trip.observe(state(x=8.), 10., terminal=True, success=True) is TripStatus.SUCCEEDED


def test_final_xy_does_not_certify_another_floor_stale_position_flying_or_wrong_facing():
    for sample, reason in [(state(z=1.), 'floor'), (state(at=1.), 'stale'),
                           (state(movement={'flying': True}), 'touchdown')]:
        trip = TripExecutor()
        trip.start(request(), 10.)
        assert trip.observe(sample, 10., terminal=True, success=True) is TripStatus.RUNNING
        assert reason in trip.reason
    trip = TripExecutor()
    trip.start(request(face_on_arrival=True, face_towards={'x': 0., 'y': 0.}), 10.)
    assert trip.observe(state(), 10., terminal=True, success=True) is TripStatus.RUNNING
    assert trip.reason == 'trip_facing_not_verified'
    assert trip.observe(state(orientation=3.141592653589793), 10., terminal=True, success=True) is TripStatus.SUCCEEDED


def test_final_arrival_deadline_is_bounded_and_cancel_does_not_become_failure():
    trip = TripExecutor()
    trip.start(replace(request(), timeout=2.), 10.)
    assert trip.observe(state(z=1., at=13.), 13., terminal=True, success=True) is TripStatus.FAILED
    trip.start(request(), 20.)
    trip.cancel('combat_preemption')
    assert trip.status is TripStatus.CANCELLED and trip.reason == 'combat_preemption'


def test_transitions_need_fresh_observed_changes_not_button_ack():
    transition = TransitionSystem()
    transition.observe(state(is_mounted=False), 10.)
    transition.observe(state(is_mounted=False, mount_command_ack=True), 10.)
    assert transition.events == []
    transition.observe(state(is_mounted=True), 10.)
    transition.observe(state(at=1., movement={'flying': True}), 10.)
    assert [e['kind'] for e in transition.events] == ['MOUNT']
    transition.observe(state(movement={'flying': True}), 10.)
    transition.observe(state(movement={'flying': False}), 10.)
    assert [e['kind'] for e in transition.events] == ['MOUNT', 'TAKEOFF', 'LAND']


def test_navigation_result_is_actually_gated_by_the_original_trip_floor():
    service = NavigationService()
    service.start_request(request(), state(x=0.), 10.)
    service._observe_control = lambda *args, **kwargs: MovementAssessment(MovementPhase.ARRIVED, True, True, 'reach_arrival_verified')
    result = service.observe(state(z=1.), 'sample-2', 10.)
    assert result.success is False and result.terminal is False
    assert 'floor' in service.snapshot(10.)['trip']['reason']
    assert service.observe(state(), 'sample-3', 10.).success is True


def test_spec_30_1_trip_legs_name_the_mount_and_the_walk_to_open_sky():
    from types import SimpleNamespace
    from wowbot.navigation.travel import TripExecutor
    request = SimpleNamespace(request_id="r", correlation_id="c", target_entity_id=None, timeout=90.,
                              arrival=SimpleNamespace(desired_range=None, radius=3.),
                              destination={"coordinate_space": "WORLD_YARDS", "instance_id": 0, "x": 500., "y": 0.,
                                           "flight": True, "flight_departure": {"point": {"x": 5., "y": 0.}}})
    route = SimpleNamespace(route_id="route:1", anchors=({"x": 0., "y": 0.}, {"x": 5., "y": 0.}),
                            regions=({"partial_flight_departure": True},))
    trip = TripExecutor()
    trip.start(request, 0.)
    trip.route(route, request, state={"is_mounted": False})
    assert [leg["kind"] for leg in trip.snapshot()["legs"]] == ["GROUND", "MOUNT", "TAKEOFF", "FLIGHT", "LAND", "GROUND"]
    assert trip.snapshot()["legs"][1]["expected_evidence"] == "mounted_state_observed"
    ground = SimpleNamespace(route_id="route:2", anchors=({"x": 0., "y": 0.}, {"x": 50., "y": 0.}), regions=())
    plain = SimpleNamespace(**{**vars(request), "destination": {"coordinate_space": "WORLD_YARDS", "instance_id": 0,
                                                                "x": 50., "y": 0.}, "request_id": "r2"})
    trip.start(plain, 1.)
    trip.route(ground, plain, state={"is_mounted": True})
    assert [leg["kind"] for leg in trip.snapshot()["legs"]] == ["RIDE"]
