"""Live 2026-10-04 09:02: Quilboar Shadow Magic (POI 180 yd) and Down with
the Quilboar (POI 203 yd) MOVEs tied at the distance-penalty cap because
WORLD_YARDS destinations were measured against the normalized map position;
the agent headed for the farther quest through the nearer one's area."""
from wowbot.agent.models import Goal, Observation, Proposal
from wowbot.agent.proposal_ranking import ProposalRanker
from wowbot.agent.skills import SkillRegistry
from wowbot.agent.world import WorldModel


def _move(quest_id, x, y):
    return Proposal.make("MOVE", "Quest térképi helyének felderítése",
                         {"x": x, "y": y, "coordinate_space": "WORLD_YARDS", "instance_id": 2175,
                          "map_id": 1409, "quest_id": quest_id, "purpose": "LOCATE_QUEST_OBJECTIVE_REGION",
                          "require_navmesh": True}, priority=44)


def test_nearer_world_yards_quest_move_ranks_first():
    world = WorldModel()
    world.ingest(Observation.create({
        "session_id": "r", "timestamp": 1., "frame_id": "f", "monotonic_time": 1., "map_id": 1409,
        "orientation": 0., "position": {"x": .55, "y": .78}, "player_present": True,
        "player_world_position": {"x": -139., "y": -2637., "instance_id": 2175,
                                  "coordinate_space": "WORLD_YARDS"}}, 1.))
    farther, nearer = _move(55186, 18., -2509.), _move(55184, 37., -2601.)
    result = ProposalRanker.rank([farther, nearer], goal=Goal.parse("Questelj", 1.), world=world,
                                 now=1., registry=SkillRegistry(), memory=None,
                                 blocked_until={}, recent={}, evidence=())
    assert result.proposals[0].parameters["quest_id"] == 55184
    # Same utility (the tie that hit live); the real distance decides.
    assert result.scores[farther.key]["total"] == result.scores[nearer.key]["total"]
