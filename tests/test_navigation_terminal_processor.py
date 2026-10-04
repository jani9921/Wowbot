from types import SimpleNamespace

from wowbot.agent.models import Outcome, Proposal
from wowbot.agent.navigation_terminal import NavigationTerminalProcessor


class Navigation:
    def __init__(self):
        self.results = []
        self.cancelled = False
        self.moves = []

    def observe_verified_move(self, before, after, destination):
        self.moves.append((before, after, destination))

    def mark_recovery(self):
        pass

    def report_recovery_result(self, *, success, now):
        self.results.append((success, now))
        return SimpleNamespace(
            state=SimpleNamespace(value="IDLE"), reason="STUCK_RECOVERED",
            correlation_id="stuck:1", action=None)

    def cancel_movement(self):
        self.cancelled = True


def test_verified_local_recovery_waypoint_closes_stuck_step():
    navigation = Navigation()
    attempt = SimpleNamespace(proposal=Proposal.make(
        "MOVE", "local recovery", {
            "map_id": 1, "x": .6, "y": .5,
            "_stuck_recovery_waypoint": True}))
    result = NavigationTerminalProcessor(navigation).process(
        attempt, Outcome.SUCCESS, "reach_arrival_verified", None,
        {"position": {"x": .5, "y": .5}},
        {"position": {"x": .6, "y": .5}},
        latest_observation_id="obs:2", now=2.)
    assert navigation.results == [(True, 2.)]
    assert navigation.cancelled is True
    assert result.recovery_succeeded is True
