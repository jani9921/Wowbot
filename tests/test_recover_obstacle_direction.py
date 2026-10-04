from wowbot.agent.models import Proposal
from wowbot.agent.skills import SkillRegistry
from wowbot.agent.world import WorldModel, Observation


def world(**extra):
    value = WorldModel()
    value.ingest(Observation.create({"session_id": "s", "frame_id": "f", "timestamp": 1,
        "map_id": 1409, "position": {"x": .5, "y": .5}, "orientation": 0,
        "player_present": True, "world_map_open": False, **extra}, 1))
    return value


def test_recover_strafes_away_from_an_obstacle_seen_on_the_left():
    obstacle = {"detector_kind": "obstacle_candidate", "x": .2}
    w = world(visual_candidates=[obstacle])
    proposal = Proposal.make("RECOVER", "test", {"attempt": 0})
    commands = SkillRegistry().commands(proposal, w)
    assert commands[0].binding == "STRAFERIGHT"


def test_recover_strafes_away_from_an_obstacle_seen_on_the_right():
    obstacle = {"detector_kind": "obstacle_candidate", "x": .8}
    w = world(visual_candidates=[obstacle])
    proposal = Proposal.make("RECOVER", "test", {"attempt": 1})
    commands = SkillRegistry().commands(proposal, w)
    assert commands[0].binding == "STRAFELEFT"


def test_recover_falls_back_to_blind_alternation_without_a_visible_obstacle():
    w = world(visual_candidates=[])
    registry = SkillRegistry()
    even = registry.commands(Proposal.make("RECOVER", "test", {"attempt": 0}), w)
    odd = registry.commands(Proposal.make("RECOVER", "test", {"attempt": 1}), w)
    assert even[0].binding == "STRAFELEFT"
    assert odd[0].binding == "STRAFERIGHT"


def test_recover_still_jumps_simultaneously_when_obstacle_aware():
    obstacle = {"detector_kind": "obstacle_candidate", "x": .2}
    w = world(visual_candidates=[obstacle])
    commands = SkillRegistry().commands(Proposal.make("RECOVER", "test", {"attempt": 0}), w)
    assert commands[0].simultaneous == ("JUMP",)
