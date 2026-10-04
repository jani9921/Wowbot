from wowbot.agent.engine import AutonomousAgent
from wowbot.agent.executor import RecordingExecutor
from wowbot.agent.models import Mode


def agent(goal="Questelj", params=None):
    executor = RecordingExecutor()
    value = AutonomousAgent(executor, memory=None)
    value.set_goal(goal, 1., params)
    value.set_mode(Mode.FULL_AI)
    return value, executor


def state(t=1., **overrides):
    result = {"session_id": "test:player-1", "timestamp": t, "monotonic_time": t,
              "frame_id": f"test:{t}", "map_id": 1609, "position": {"x": .5, "y": .5},
              "orientation": 0., "player_present": True, "is_dead": False, "is_in_combat": False,
              "target": None, "mouseover": None, "active_quests": [], "actionbar": [], "events": [],
              "event_sequence": 0, "inventory": {"items": [], "free_slots": 10},
              "quest_ui": {"open": False, "entries": []}}
    result.update(overrides)
    return result


def test_move_already_at_destination_still_creates_a_trackable_attempt():
    # Live-observed 2026-09-14: MOVE toward a quest waypoint already within
    # stop_distance made ReachMovementController.start() land on ARRIVED on
    # its own first internal observe() call, so command() correctly returned
    # no movement -- but the "no commands -> return early" gate in engine.py
    # then discarded that terminal result entirely (start()'s return value is
    # never captured). self.pending stayed None, so every following tick just
    # called start() fresh again with the identical outcome: MOVE displayed
    # unchanged, zero displacement, for 64+ real seconds live before the user
    # hit the F12 kill switch. mark_location_reached() never got a chance to
    # run either, so the same MOVE proposal kept being regenerated forever.
    #
    # stop_distance is set generously wide (.05) so the goal itself is not
    # yet considered complete (GoalManager's completion contract uses a fixed
    # .003) while still being within the movement skill's own arrival
    # tolerance on the very first tick -- exactly the "arrived before ever
    # sending a command" situation that was silently dropped before.
    value, exe = agent("Menj oda",
                        {"destination": {"map_id": 1609, "x": .51, "y": .5, "stop_distance": .05}})
    value.tick(state(), 1)
    assert not exe.commands  # already there; nothing to send this tick
    assert value.pending is not None and value.pending.proposal.skill == "MOVE"

    value.tick(state(2), 2)
    assert value.last_result["outcome"] == "SUCCESS"
    assert value.last_result["reason"] == "reach_arrival_verified"
