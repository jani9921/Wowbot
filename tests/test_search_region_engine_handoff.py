from wowbot.agent.engine import AutonomousAgent
from wowbot.agent.executor import RecordingExecutor
from wowbot.agent.models import Goal, Mode, Observation


def test_search_area_handoff_first_requests_navigation_coverage_cell(monkeypatch):
    agent = AutonomousAgent(RecordingExecutor())
    agent.goal = Goal.parse("questelj", 1.)
    agent.mode = Mode.FULL_AI
    payload = {"session_id": "s", "frame_id": "f", "timestamp": 1., "map_id": 1,
               "position": {"x": .5, "y": .5}, "orientation": 0., "player_present": True,
               "active_quests": [{"quest_id": 1, "state": "ACTIVE", "objectives": []}]}
    agent.world.ingest(Observation.create(payload, 1.))
    # Isolate the boundary: the planner emits a normal SEARCH_AREA visual
    # proposal, and engine must turn it into the first navigation cell.
    from wowbot.agent.models import Proposal
    proposal = Proposal.make("SEEK_VISUAL_CUE", "search", {
        "purpose": "SEARCH_LOCAL_OBJECTIVE_AREA", "search_area": {"map_id": 1, "x": .5, "y": .5, "radius": .02},
        "quest_id": 1, "objective_id": "1:obj", "objective_type": "EXPLORE"}, priority=55)
    agent.navigation.begin_search_region("1:1:obj:1", proposal.parameters["search_area"])
    waypoint = agent.navigation.next_search_waypoint("1:1:obj:1", agent.world.state)
    assert waypoint is not None and waypoint["purpose"] == "SEARCH_REGION_COVERAGE"
