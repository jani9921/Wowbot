"""Live 2026-10-04 08:57: Austin Huxworth (turn-in NPC) was selected and on
screen as a GUID-bound World3D track, INTERACTTARGET answered "You need to be
closer" three times, and no approach ran: the bound-track source was not an
accepted anchor, and its sample (runtime clock) was newer than the addon
snapshot clock (-0.2..-3.6 s), which the freshness tests rejected."""
from wowbot.agent.models import Observation, Proposal
from wowbot.agent.skills import SkillRegistry
from wowbot.agent.world import WorldModel
from wowbot.skills.interact import InteractSkill

GUID = "Creature-0-3113-2175-63341-153211-00004182C1"
ANCHOR = {"x": .4572, "y": .6074, "source": "BOUND_WORLD3D_TRACK", "coordinate_space": "CLIENT_BOTTOM_LEFT",
          "sample_time": 489787.2376852, "identity_source": "HOVER_SELECTED_TRACK", "track_id": "WORLD3D:254"}
TARGET = {"guid": GUID, "name": "Austin Huxworth", "attackable": False, "screen_position": ANCHOR}


def test_interact_out_of_range_approaches_a_newer_bound_track():
    state = {"monotonic_time": 489785.937, "target": TARGET}
    request = InteractSkill._visual_approach_request(state, GUID, 10.)
    assert request is not None and request["screen_position"]["track_id"] == "WORLD3D:254"


def test_visual_approach_is_available_on_a_newer_bound_track():
    world = WorldModel()
    world.ingest(Observation.create({
        "session_id": "b", "timestamp": 1., "frame_id": "f", "monotonic_time": 489785.937,
        "map_id": 1409, "orientation": 0., "position": {"x": .6, "y": .8}, "player_present": True,
        "target": TARGET}, 1.))
    proposal = Proposal.make("VISUAL_APPROACH", "test", {"guid": GUID, "purpose": "INTERACT",
                                                         "screen_position": ANCHOR}, priority=102)
    assert SkillRegistry().available(proposal, world)
    stale = {**ANCHOR, "sample_time": 489780.}
    assert not SkillRegistry().available(Proposal.make(
        "VISUAL_APPROACH", "test", {"guid": GUID, "purpose": "INTERACT", "screen_position": stale},
        priority=102), world)
