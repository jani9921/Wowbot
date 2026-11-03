from dataclasses import replace
import pytest
from wowbot.navigation.contracts import GlobalRoute, NavigationRequest
from wowbot.navigation.danger import DangerMap
from wowbot.navigation.route_score import RouteRiskEvaluator, TravelCalibration
from wowbot.navigation.global_planner import GlobalNavigator


def route(*, flight=False, height=0.):
    return GlobalRoute('flight' if flight else 'ground',
        ({'x': 0., 'y': 0., 'z': height}, {'x': 100., 'y': 0., 'z': height,
          **({'flight_plan': {}} if flight else {})}),
        ({'route_source': 'FLIGHT_PLAN' if flight else 'TRINITYCORE_MMAP'},), 100., .95, 10., 30.)


def request(**changes):
    return NavigationRequest('r', 'c', 'MOVE_TO_LOCATION',
        {'x': 100., 'y': 0., 'instance_id': 2444, 'coordinate_space': 'WORLD_YARDS', **changes})


def test_scores_have_explainable_seconds_and_keep_unknown_revisions_unknown():
    score = RouteRiskEvaluator().evaluate(route(), request(), {}, 10.)
    assert score.eta_seconds == pytest.approx(100/7)
    assert score.total_seconds >= score.eta_seconds
    assert score.geometry_revision is None and score.diagnostic()['units'] == 'ESTIMATED_SECONDS'
    assert 'geometry_revision_unknown' in score.assumptions


def test_other_floor_and_stale_hostiles_do_not_become_expected_fights():
    danger = DangerMap()
    for name, height, observed in [('other-floor', 100., 10.), ('stale', 0., 1.)]:
        danger.add(danger_id=name, kind='HOSTILE_AGGRO', x=50., y=0., z=height,
                   radius=20., cost=1000., confidence=1., now=10., ttl=30., source='PACKET_ENTITY', observed_at=observed)
    score = RouteRiskEvaluator().evaluate(route(), request(), {}, 10., danger_map=danger)
    assert score.combat_seconds == 0. and score.exposed_entities == ()


def test_same_floor_exposure_is_calibrated_in_seconds_not_danger_points():
    danger = DangerMap()
    danger.add(danger_id='mob', kind='HOSTILE_AGGRO', x=50., y=0., z=0., radius=20.,
               cost=1000., confidence=1., now=10., ttl=8., source='PACKET_ENTITY')
    score = RouteRiskEvaluator(TravelCalibration(expected_fight_seconds=12.)).evaluate(
        route(), request(), {}, 10., danger_map=danger)
    assert score.combat_seconds == 12. and score.combat_seconds != 1000.
    assert danger.route_cost([{'x': 0., 'y': 0., 'z': 100.}, {'x': 100., 'y': 0., 'z': 100.}], 10.) == 100.


def test_unknown_floor_is_uncertainty_not_a_confirmed_fight_and_partial_eta_is_unknown():
    danger = DangerMap()
    danger.add(danger_id='mob', kind='HOSTILE_AGGRO', x=50., y=0., radius=20., cost=1000.,
               confidence=1., now=10., ttl=8., source='PACKET_ENTITY')
    score = RouteRiskEvaluator().evaluate(route(), request(), {}, 10., danger_map=danger)
    assert score.combat_seconds == 0. and 'threat_floor_unknown' in score.assumptions
    partial = replace(route(), regions=({'partial_flight_departure': True},))
    assert RouteRiskEvaluator().evaluate(partial, request(), {}, 10.).total_seconds is None


def test_real_global_entry_compares_only_proved_ground_alternative():
    planner = GlobalNavigator()
    flight = route(flight=True)
    ground = route()
    planner._plan_route = lambda r, *args, **kwargs: flight if r.destination.get('flight') else ground
    selected = planner.plan(request(flight=True, flight_style='STEADY', travel_mode_policy='AUTO'), {'is_mounted': True}, 10.)
    assert selected is ground  # short mounted walk beats takeoff+landing
    assert len(planner.last_route_scores['candidates']) == 2
    assert planner.last_route_scores['selected_route_id'] == 'ground'


def test_live_danger_preserves_provenance_and_original_sample_deadline():
    danger = DangerMap()
    state = {'nearby_attackable_entities': [{'guid': 'mob', 'attackable': True, 'source': 'PACKET_ENTITY',
             'world_position': {'x': 1., 'y': 2., 'z': 3., 'instance_id': 2444, 'sample_time': 1.}}]}
    danger.observe_hostiles(state, 2.)
    entry = danger.active_entries(2.)[0]
    assert entry.source == 'PACKET_ENTITY' and entry.z == 3. and entry.world_map_id == 2444
    danger.observe_hostiles(state, 10.)
    assert danger.active_entries(10.) == ()
