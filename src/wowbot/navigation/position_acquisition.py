"""Own-position prerequisites for planning; no input or independent world state."""
from wowbot.value_helpers import number


def observed_height(state):
    point = state.get('player_world_position') or {}
    value = number(point.get('observed_z'))
    return value if value is not None else number(point.get('z')) if point.get('z_observed') is True else None


def scope(state):
    return (state.get('session_id'), state.get('character_guid'),
            (state.get('player_world_position') or {}).get('instance_id'),
            (state.get('packet_telemetry') or {}).get('selected_pid'))


def blocked(state):
    movement = state.get('movement') or {}
    return bool(state.get('loading') or state.get('input_blocked') or state.get('player_present') is False
                or state.get('is_dead') or state.get('is_ghost') or state.get('in_vehicle')
                or state.get('on_taxi') or state.get('is_in_combat') or state.get('is_casting')
                or state.get('is_channeling') or movement.get('flying') or movement.get('falling')
                or state.get('world_map_open') or state.get('quest_ui_open') or state.get('gossip_open')
                or any((state.get(key) or {}).get('open') for key in
                       ('quest_ui', 'gossip_ui', 'vendor_ui', 'taxi_ui', 'loot_ui')))


def required(destination, state):
    """Only the live grounded packet-assisted 3D path needs this first fix.

    Keep the existing vision/legacy and already-airborne contracts. A held
    server height at unchanged XY is an observation, not a reason to probe.
    """
    point = state.get('player_world_position') or {}
    return bool(destination.get('coordinate_space') == 'WORLD_YARDS'
                and destination.get('require_navmesh') is True and state.get('packet_telemetry')
                and observed_height(state) is None and not blocked(state)
                and point.get('instance_id') is not None
                and point.get('instance_id') == destination.get('instance_id')
                and number(point.get('x')) is not None and number(point.get('y')) is not None)


class ServerPositionWait:
    """The first own server height before a grounded 3D route (REV4 split).

    Moved out of ``NavigationService`` (SRC_MELY_AUDIT 4.3).  It owns the
    wait (start time, session/world scope) and its diagnostic trace.  The
    service still owns the request, its budget and deadline, the single
    movement controller's measurement tap and the resumed plan.
    """

    def __init__(self) -> None:
        self.wait: dict | None = None
        self.trace: dict | None = None

    def forget_other(self, request_id) -> None:
        if self.trace is not None and self.trace['request_id'] != request_id:
            self.trace = None

    def begin(self, request_id, state, now, timeout_seconds) -> None:
        self.wait = {'started_at': now, 'scope': scope(state)}
        self.trace = {'request_id': request_id, 'phase': 'AWAITING_PACKET', 'started_at': now,
                      'timeout_seconds': timeout_seconds, 'proposed_probe': None}

    def status(self, state, now, budget, request_started_at, request_budget) -> str | None:
        if self.wait is None:
            return None
        if scope(state) != self.wait['scope']:
            return 'server_position_probe_context_changed'
        if blocked(state):
            return 'server_position_probe_interrupted'
        if (now-self.wait['started_at'] >= budget
                or now-request_started_at >= request_budget):
            return 'server_position_probe_timeout'
        return 'READY' if observed_height(state) is not None else 'WAITING'

    def cancel(self) -> None:
        if self.wait is not None and self.trace is not None:
            self.trace['phase'] = 'CANCELLED'

    def snapshot(self) -> dict | None:
        trace = self.trace
        if trace is None:
            return None
        return {**trace, 'active': self.wait is not None,
                'proposed_probe': dict(trace['proposed_probe']) if trace.get('proposed_probe') else None}
