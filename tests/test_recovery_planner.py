from types import SimpleNamespace

from wowbot.agent.models import Proposal
from wowbot.agent.recovery_planning import RecoveryPlanner


class World:
    def __init__(self, state=None, position=(.5, .5)):
        self.state = state or {}
        self._position = position

    def player_position(self): return self._position

    latest = SimpleNamespace(observation_id="obs:latest")


class Registry:
    def available(self, proposal, world): return True


class Autonomy:
    def __init__(self): self.resets = []
    def reset(self, now, trigger): self.resets.append((now, trigger))
    def choose(self, proposals, proposal, goal, world, now): return proposal


class Navigation:
    def __init__(self, directives, active=False, local_waypoint=None):
        self.directives = iter(directives)
        self.stuck_recovery_active = active
        self.marked = []
        self.rebuilt = []
        self.local_waypoint = local_waypoint

    def next_stuck_recovery(self, *args): return next(self.directives)
    def observe_external_hard_stuck(self, *args): return next(self.directives)
    def report_recovery_result(self, *, success, now): return next(self.directives)
    def mark_current_route_danger(self, state, now, *, correlation_id=None, **kwargs):
        self.marked.append((state, now, correlation_id, kwargs)); return True
    def rebuild_current_corridor(self, state, observation_id, now):
        self.rebuilt.append((state, observation_id, now)); return True
    def new_local_recovery_waypoint(self, state, observation_id, now):
        return self.local_waypoint


def directive(action, *, scope=None):
    return SimpleNamespace(action=action, state=SimpleNamespace(value="TEST"),
                           correlation_id="stuck:test", replan_scope=scope)


def test_stationary_watchdog_does_not_preempt_before_threshold():
    planner = RecoveryPlanner()
    planner.stationary_position, planner.stationary_since = (.5, .5), 1.
    proposal = Proposal.make("WAIT", "observe")
    decision = planner.apply(
        proposal, world=World(), goal=object(), last_result={},
        navigation=Navigation([]), registry=Registry(), autonomy=Autonomy(),
        failures={}, now=120.)
    assert decision.proposal is proposal


def test_stationary_watchdog_requires_stop_and_observe_before_recovery():
    planner = RecoveryPlanner()
    planner.stationary_position, planner.stationary_since = (.5, .5), 1.
    decision = planner.apply(
        Proposal.make("WAIT", "observe"), world=World(), goal=object(), last_result={},
        navigation=Navigation([directive("STOP_AND_OBSERVE")]), registry=Registry(),
        autonomy=Autonomy(), failures={}, now=122.)
    assert decision.proposal.skill == "WAIT"
    assert decision.proposal.parameters["stuck_recovery_state"] == "TEST"


def test_stationary_watchdog_executes_after_the_observation_gate():
    planner, autonomy = RecoveryPlanner(), Autonomy()
    planner.stationary_position, planner.stationary_since = (.5, .5), 1.
    navigation = Navigation(
        [directive("STOP_AND_OBSERVE"), directive("BACKWARD")], active=False)
    first = planner.apply(
        Proposal.make("WAIT", "nothing actionable"), world=World(), goal=object(),
        last_result={}, navigation=navigation, registry=Registry(),
        autonomy=autonomy, failures={}, now=122.)
    assert first.proposal.skill == "WAIT"

    # This mock exposes the same active resolver state NavigationService would
    # expose after the first decision.  The next independent planning sample
    # must not be starved by another generic WAIT/INSPECT proposal.
    navigation.stuck_recovery_active = True
    second = planner.apply(
        Proposal.make("INSPECT", "background unknown"), world=World(), goal=object(),
        last_result={}, navigation=navigation, registry=Registry(),
        autonomy=autonomy, failures={}, now=123.)
    assert second.proposal.skill == "RECOVER"
    assert second.proposal.parameters["recovery_step"] == "BACKWARD"
    assert autonomy.resets == [(123., "STUCK_CONFIRMED")]


def test_supported_stuck_can_propose_one_bounded_recovery():
    planner, autonomy = RecoveryPlanner(), Autonomy()
    result = {"skill": "MOVE", "outcome": "FAILURE", "reason": "supported_stuck",
              "action_id": "move:1", "key": "move-key"}
    decision = planner.apply(
        Proposal.make("INSPECT", "new cue"), world=World(), goal=object(),
        last_result=result, navigation=Navigation([directive("BACKWARD")]),
        registry=Registry(), autonomy=autonomy, failures={"move-key": 1}, now=5.)
    assert decision.proposal.skill == "RECOVER"
    assert decision.proposal.parameters["attempt"] == 1
    assert decision.recovery_for == "move:1"
    assert autonomy.resets == [(5., "STUCK_CONFIRMED")]


def test_combat_suppresses_stationary_watchdog():
    planner = RecoveryPlanner()
    planner.stationary_position, planner.stationary_since = (.5, .5), 1.
    proposal = Proposal.make("COMBAT", "survival")
    decision = planner.apply(
        proposal, world=World({"is_in_combat": True}), goal=object(), last_result={},
        navigation=Navigation([]), registry=Registry(), autonomy=Autonomy(),
        failures={}, now=500.)
    assert decision.proposal is proposal


def test_path_loop_marks_danger_and_rebuilds_corridor_before_resuming():
    planner, autonomy = RecoveryPlanner(), Autonomy()
    navigation = Navigation([
        directive("MARK_DANGER"),
        directive("REBUILD_CORRIDOR", scope="LOCAL"),
    ], active=True)
    failed = {"skill": "MOVE", "outcome": "FAILURE", "reason": "supported_stuck",
              "action_id": "move:path-loop", "key": "move-key"}

    decision = planner.apply(
        Proposal.make("MOVE", "old route", {"x": 10., "y": 0.}),
        world=World({"position": {"x": 4., "y": 0.}}), goal=object(),
        last_result=failed, navigation=navigation, registry=Registry(),
        autonomy=autonomy, failures={"move-key": 1}, now=5.)

    assert navigation.marked[0][2] == "stuck:test"
    assert navigation.rebuilt == [({"position": {"x": 4., "y": 0.}}, "obs:latest", 5.)]
    assert decision.proposal.skill == "WAIT"
    assert decision.proposal.parameters["replan_scope"] == "LOCAL"
    assert decision.recovery_for == "move:path-loop"
    assert autonomy.resets == [(5., "STUCK_LOCAL_REPLAN")]


def test_new_local_waypoint_becomes_normal_verified_move_not_direct_input():
    planner, autonomy = RecoveryPlanner(), Autonomy()
    navigation = Navigation(
        [directive("NEW_LOCAL_WAYPOINT")], active=True,
        local_waypoint={"map_id": 1, "x": .6, "y": .5,
                        "_stuck_recovery_waypoint": True})
    decision = planner.apply(
        Proposal.make("MOVE", "old", {"map_id": 1, "x": .9, "y": .9}),
        world=World({"position": {"x": .5, "y": .5}}), goal=object(),
        last_result={}, navigation=navigation, registry=Registry(),
        autonomy=autonomy, failures={}, now=5.)
    assert decision.proposal.skill == "MOVE"
    assert decision.proposal.parameters["_stuck_recovery_waypoint"] is True
    assert autonomy.resets == [(5., "STUCK_NEW_LOCAL_WAYPOINT")]


def test_temporary_blacklist_is_applied_then_ladder_terminates():
    planner = RecoveryPlanner()
    navigation = Navigation(
        [directive("BLACKLIST_TEMP"), directive("FAILED")], active=True)
    decision = planner.apply(
        Proposal.make("MOVE", "old", {"x": .9, "y": .9}),
        world=World({"position": {"x": .5, "y": .5}}), goal=object(),
        last_result={}, navigation=navigation, registry=Registry(),
        autonomy=Autonomy(), failures={}, now=5.)
    assert navigation.marked[0][3] == {
        "ttl": 300., "cost": 30., "kind": "TEMP_ROUTE_BLACKLIST"}
    assert decision.proposal.skill == "WAIT"
    assert decision.proposal.parameters["replan_scope"] == "GLOBAL"
