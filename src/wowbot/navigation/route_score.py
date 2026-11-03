"""Comparable estimated seconds; DangerMap weights remain geometric weights."""
from __future__ import annotations
from dataclasses import asdict, dataclass
import math


@dataclass(frozen=True, slots=True)
class TravelCalibration:
    walk_yards_per_second: float = 7.
    ride_yards_per_second: float = 14.
    steady_yards_per_second: float = 17.
    skyriding_yards_per_second: float = 35.
    expected_fight_seconds: float = 20.
    flight_transition_seconds: float = 8.
    unknown_floor_seconds: float = 10.
    recovery_seconds: float = 90.

    def __post_init__(self):
        if any(type(v) not in {int, float} or not math.isfinite(v) or v <= 0 for v in asdict(self).values()):
            raise ValueError('positive finite travel calibration required')


@dataclass(frozen=True, slots=True)
class RouteScore:
    route_id: str
    mode: str
    distance_yards: float
    eta_seconds: float | None
    combat_seconds: float
    transition_seconds: float
    uncertainty_seconds: float
    failure_probability: float
    expected_recovery_seconds: float
    confidence: float
    geometry_revision: str | int | None
    risk_revision: int
    evaluated_at: float
    exposed_entities: tuple[str, ...]
    assumptions: tuple[str, ...]

    @property
    def total_seconds(self):
        if self.eta_seconds is None:
            return None
        return self.eta_seconds+self.combat_seconds+self.transition_seconds+self.uncertainty_seconds+self.expected_recovery_seconds

    def diagnostic(self):
        return {**asdict(self), 'total_seconds': self.total_seconds, 'units': 'ESTIMATED_SECONDS'}


KIND_FIGHT_WEIGHT = {'ELITE_SPAWN': 3., 'RARE_SPAWN': 2., 'HOSTILE_CLUSTER': 2.}


def character_fight_factor(state):
    """1 at full health, up to 1.75 near death (own HP from packets/addon)."""
    health, maximum = state.get('health'), state.get('max_health')
    if type(health) not in {int, float} or type(maximum) not in {int, float} or maximum <= 0:
        return 1.
    return 1.+.75*(1.-max(0., min(1., health/maximum)))


class RouteRiskEvaluator:
    def __init__(self, calibration=None):
        self.calibration = calibration or TravelCalibration()

    def evaluate(self, route, request, state, now, *, danger_map=None, geometry_revision=None):
        config = self.calibration
        flight = (any('flight_plan' in a for a in route.anchors) or bool(request.destination.get('flight_path'))
                  or any(r.get('route_source') == 'FLIGHT_PLAN' for r in route.regions))
        mode = (request.destination.get('flight_style', 'STEADY') if flight else
                'RIDE' if state.get('is_mounted') is True else 'WALK')
        speed = {'WALK': config.walk_yards_per_second, 'RIDE': config.ride_yards_per_second,
                 'STEADY': config.steady_yards_per_second, 'SKYRIDING': config.skyriding_yards_per_second}[mode]
        distance = sum(math.dist((a['x'], a['y']), (b['x'], b['y'])) for a, b in zip(route.anchors, route.anchors[1:]))
        transition = (config.flight_transition_seconds if flight and
                      (state.get('movement') or {}).get('flying') is not True else 0.)
        exposed, combat, uncertainty = [], 0., max(0., 1.-route.confidence)*5.
        severe_exposure = 0.
        assumptions = ['default_speed_calibration', 'estimated_not_observed_travel_time']
        incomplete = not route.anchors or any(r.get('partial_flight_departure') or r.get('partial_localization_leg')
                                              for r in route.regions)
        if incomplete:
            assumptions.append('complete_trip_eta_unavailable')
        player_map = (state.get('player_world_position') or {}).get('instance_id')
        entries = danger_map.active_entries(now, exempt_entity_id=request.target_entity_id) if danger_map else ()
        seen = set()
        for entry in entries:
            if entry.danger_id in seen or getattr(entry, 'world_map_id', None) not in (None, player_map):
                continue
            observed = getattr(entry, 'observed_at', None)
            if type(observed) in {int, float} and not 0 <= now-observed <= 8.:
                continue
            seen.add(entry.danger_id)
            exposure = 0.
            floor_unknown = False
            for a, b in zip(route.anchors, route.anchors[1:]):
                if flight and a is not route.anchors[0] and b is not route.anchors[-1]:
                    continue
                from .danger import DangerMap
                separation = DangerMap._segment_distance(a, b, entry.x, entry.y)
                if separation >= entry.radius:
                    continue
                ez = getattr(entry, 'z', None)
                heights = [p.get('z') for p in (a, b)]
                if ez is not None and all(type(z) in {int, float} for z in heights):
                    if min(heights)-6. > ez or max(heights)+6. < ez:
                        continue
                else:
                    floor_unknown = True
                if flight:
                    # Ground aggro along a cruise segment is not ground
                    # exposure. Only the departure/landing vicinity counts.
                    separation = min(math.hypot(p['x']-entry.x, p['y']-entry.y)
                                     for p in (route.anchors[0], route.anchors[-1]))
                    if separation >= entry.radius:
                        continue
                exposure = max(exposure, (1.-separation/entry.radius)*entry.confidence)
            if exposure <= 0:
                continue
            exposed.append(entry.entity_id or entry.danger_id)
            if floor_unknown:
                uncertainty += config.unknown_floor_seconds*exposure
                assumptions.append('threat_floor_unknown')
            elif entry.kind in {'HOSTILE_AGGRO', 'HOSTILE_SPAWN', 'ELITE_SPAWN', 'RARE_SPAWN', 'HOSTILE_CLUSTER'}:
                profile = state.get('character_profile') or {}
                fight = profile.get('expected_fight_seconds', config.expected_fight_seconds)
                if type(fight) not in {int, float} or not math.isfinite(fight) or fight <= 0:
                    fight = config.expected_fight_seconds
                # Spec 31.2/31.4: an elite/rare/pack costs more; so does any
                # fight for a character already low on health.
                weight = KIND_FIGHT_WEIGHT.get(entry.kind, 1.)*character_fight_factor(state)
                combat += exposure*fight*weight
                if entry.kind in KIND_FIGHT_WEIGHT:
                    severe_exposure = max(severe_exposure, exposure)
            else:
                uncertainty += config.unknown_floor_seconds*exposure
        failure = min(.75, max(0., (1.-route.confidence)*.1) + .15*severe_exposure)
        if flight:
            # Spec 31.3: landing on an unknown floor is a risk of the flight itself.
            if request.destination.get('z_known') is not True:
                uncertainty += config.unknown_floor_seconds*.5
                assumptions.append('landing_floor_unknown')
        revision = geometry_revision if type(geometry_revision) in {str, int} else None
        if revision is None:
            assumptions.append('geometry_revision_unknown')
        return RouteScore(route.route_id, mode, distance, None if incomplete else distance/speed, combat, transition, uncertainty,
            failure, failure*config.recovery_seconds, route.confidence, revision,
            danger_map.revision if danger_map else 0, now, tuple(exposed), tuple(dict.fromkeys(assumptions)))
