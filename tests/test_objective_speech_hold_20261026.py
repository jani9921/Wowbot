"""Archivist Edress talks ~37 s after the gossip and gives "Archivist Edress
consulted" only after her last line (live 2026-10-26 21:52:58-21:53:35); the
agent walked off.  Wait only for an objective NPC we just talked to."""
from wowbot.agent.objective_speech_planning import ObjectiveSpeechHold

EDRESS = "Creature-0-3769-2444-47-187466-00005824C6"


def state(now, *, ui=False, lines=(), done=False, combat=False, objective="Archivist Edress consulted"):
    return {"monotonic_time": now, "is_in_combat": combat, "quest_ui": {"open": ui},
            "target": {"guid": EDRESS, "name": "Archivist Edress"},
            "active_quests": [{"quest_id": 66048, "is_complete": False, "objectives": [
                {"description": f"{int(done)}/1 {objective}", "is_complete": done}]}],
            "events": [{"event_type": "NPC_INSTRUCTION", "sequence": index,
                        "payload": {"sender": sender, "message": f"line {index}"}}
                       for index, sender in lines]}


def test_hold_through_the_speech_until_the_credit():
    hold = ObjectiveSpeechHold()
    assert hold.propose(state(0.)) == []                          # walking up: no talk yet
    hold.propose(state(1., ui=True))                              # gossip open
    assert hold.propose(state(2.)) == []                          # no line yet: free (live 10-27)
    (wait,) = hold.propose(state(2.5, lines=[(1, "Archivist Edress")]))
    assert wait.skill == "WAIT_EVENT" and wait.parameters["speaker_name"] == "archivist edress"
    (wait,) = hold.propose(state(20., lines=[(1, "Archivist Edress")]))   # 17.5 s silence: still
    assert wait.priority > 118                                    # above approach / sweep moves
    hold.propose(state(22., lines=[(1, "Archivist Edress"), (2, "Archivist Edress")]))
    assert hold.propose(state(35., lines=[(2, "Archivist Edress")]))
    assert hold.propose(state(36., lines=[(2, "Archivist Edress")], done=True)) == []   # credited


def test_no_hold_for_greetings_other_speakers_or_combat():
    hold = ObjectiveSpeechHold()
    hold.propose(state(0., lines=[(1, "Archivist Edress")]))      # greeting before the talk
    hold.propose(state(5., ui=True, lines=[(1, "Archivist Edress")]))
    assert hold.propose(state(14., lines=[(1, "Archivist Edress")])) == []   # no line after the talk
    other = ObjectiveSpeechHold()
    other.propose(state(0., ui=True, objective="Fao the Relentless consulted"))
    assert other.propose(state(2., lines=[(1, "Archivist Edress")], objective="Fao the Relentless consulted")) == []
    fight = ObjectiveSpeechHold()
    fight.propose(state(0., ui=True))
    assert fight.propose(state(1., lines=[(1, "Archivist Edress")], combat=True)) == []


def test_silence_ends_the_hold():
    hold = ObjectiveSpeechHold()
    hold.propose(state(0., ui=True))
    hold.propose(state(1., lines=[(1, "Archivist Edress")]))
    assert hold.propose(state(20., lines=[(1, "Archivist Edress")]))
    assert hold.propose(state(21.5, lines=[(1, "Archivist Edress")])) == []


def test_soft_interact_talk_without_a_target_is_recognised_from_the_server():
    """Live 23:06:34: F7 talked to Edress through soft-interact, no target;
    her window was open 0.6 s.  The server shows her 2.2 yd away."""
    def near(now, **kw):
        value = state(now, **kw)
        value["target"] = None
        value["player_world_position"] = {"x": 1790., "y": 1170.}
        value["reference_knowledge"] = {"quests": {"66048": {"objectives": [
            {"description": "Archivist Edress consulted", "credit_object_id": 187466,
             "credit_name": "Archivist Edress"}]}}}
        value["packet_entities"] = {EDRESS: {"guid": EDRESS, "kind": "CREATURE", "entry_id": 187466,
                                             "position": {"x": 1791.5, "y": 1171.6, "z": 200.}}}
        return value
    hold = ObjectiveSpeechHold()
    hold.propose(near(0., lines=[(1, "Archivist Edress")]))      # her first line, 2 s early
    hold.propose(near(2., ui=True, lines=[(1, "Archivist Edress")]))
    (wait,) = hold.propose(near(3., lines=[(1, "Archivist Edress")]))
    assert wait.parameters["speaker_name"] == "archivist edress"
    far = near(0., ui=True)
    far["packet_entities"][EDRESS]["position"] = {"x": 1800., "y": 1180., "z": 200.}
    assert ObjectiveSpeechHold().propose(far) == [] and ObjectiveSpeechHold().propose(near(1.)) == []


def test_the_planner_records_the_talk_while_the_window_owns_the_input():
    """Live 23:06:34: the open-dialog early return never called the hold, so
    Edress's talk was not seen and nothing waited for her speech."""
    from wowbot.agent.models import Goal, Observation
    from wowbot.agent.planner import Planner
    from wowbot.agent.skills import SkillRegistry
    from wowbot.agent.world import WorldModel
    from test_agent_core import state as base

    def world(now, **extra):
        payload = base(now, state_age=.1, is_mounted=False,
                       player_world_position={"x": 1790., "y": 1170., "z": 200., "instance_id": 2444,
                                              "coordinate_space": "WORLD_YARDS"},
                       target={"guid": EDRESS, "name": "Archivist Edress"},
                       active_quests=[{"quest_id": 66048, "is_complete": False, "objectives": [
                           {"description": "0/1 Archivist Edress consulted", "current": 0, "required": 1,
                            "is_complete": False}]}], **extra)
        model = WorldModel()
        model.ingest(Observation.create(payload, now))
        return model
    planner, goal = Planner(SkillRegistry()), Goal.parse("Questelj", 1.)
    planner.candidates(goal, world(100., quest_ui={"open": True, "action": "GOSSIP_OPTION_SELECT"}), 100.)
    line = [{"event_type": "NPC_INSTRUCTION", "sequence": 7,
             "payload": {"sender": "Archivist Edress", "message": "The walls of the Obsidian Citadel..."}}]
    proposals = planner.candidates(goal, world(103., quest_ui={"open": False}, events=line), 103.)
    assert any(p.skill == "WAIT_EVENT" and p.parameters.get("objective_kind") == "NPC_SPEECH"
               for p in proposals)


def test_a_silent_npc_after_the_talk_holds_nothing():
    """Live 2026-10-27 15:45:07 and 15:52:32: Wrathion said nothing after the
    gossip; the old first-line wait held 15 s and blocked his reopened row."""
    def wrathion(now, **kw):
        value = state(now, objective="Assist Wrathion", **kw)
        value["target"] = {"guid": "Creature-0-3769-2444-47-186681-00005824C7", "name": "Wrathion"}
        return value
    hold = ObjectiveSpeechHold()
    hold.propose(wrathion(0., ui=True))
    assert hold.talked_at == {"wrathion": 0.}
    for now in (1., 4., 7.):
        assert hold.propose(wrathion(now)) == []
    (wait,) = hold.propose(wrathion(8., lines=[(1, "Wrathion")]))    # he does speak: wait
    assert wait.parameters["speaker_name"] == "wrathion"
