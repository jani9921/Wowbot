"""Live 2026-10-13 05:39 (Bjorn Stouthands, Westward Bound turn-in): after
the turn-in an older range block sent a VISUAL_APPROACH (102) instead of the
follow-up Interact (95); it ran into a tree root and held W for 30 s."""
from types import SimpleNamespace

from test_agent_core import state
from wowbot.agent.quest_target_planning import QuestSelectedTargetMixin
from wowbot.agent.visual_approach import VisualApproachController, VisualApproachPhase

TARGET = {"guid": "bjorn", "attackable": False, "dead": False}
TRACK = {"source": "WORLD3D", "track_id": "WORLD3D:bjorn", "x": .51, "y": .62,
         "confidence": .8, "lifecycle": "ACTIVE", "bbox_height_fraction": .08}


def _sample(t, x):
    return state(t, target=TARGET, visual_candidates=[{**TRACK, "observed_at": t}],
                 player_world_position={"x": x, "y": 0., "instance_id": 2175,
                                        "coordinate_space": "WORLD_YARDS"})


def test_an_approach_running_on_the_spot_stops_after_a_few_seconds():
    controller = VisualApproachController()
    controller.start({"guid": "bjorn", "track_id": "WORLD3D:bjorn", "purpose": "INTERACT",
                      "range_block_started_at": 0.}, _sample(1., 0.), "v:1", 1.)
    stopped_at = None
    for index, t in enumerate((1.2, 1.6, 2.0, 2.6, 3.2, 3.8, 4.4, 5.0), start=2):
        if controller.observe(_sample(t, .1), f"v:{index}", t).reason == "visual_approach_blocked":
            stopped_at = t
            break
        controller.command(_sample(t, .1), f"v:{index}", t)
    # ~3 s on the spot instead of the 30 s safety deadline.
    assert stopped_at is not None and stopped_at <= 4.5
    assert controller.phase == VisualApproachPhase.FAILED


def test_an_approach_that_keeps_moving_is_not_blocked():
    controller = VisualApproachController()
    controller.start({"guid": "bjorn", "track_id": "WORLD3D:bjorn", "purpose": "INTERACT",
                      "range_block_started_at": 0.}, _sample(1., 0.), "v:1", 1.)
    for index, t in enumerate((1.2, 1.6, 2.0, 2.6, 3.2, 3.8, 4.4, 5.0), start=2):
        reason = controller.observe(_sample(t, (t-1.)*3.), f"v:{index}", t).reason
        controller.command(_sample(t, (t-1.)*3.), f"v:{index}", t)
        assert reason != "visual_approach_blocked"


def test_blocked_approach_is_followed_by_jump_then_sidestep():
    policy = QuestSelectedTargetMixin()

    def world(last):
        return SimpleNamespace(runtime_context={"last_result": last})
    blocked = {"skill": "VISUAL_APPROACH", "outcome": "FAILURE", "reason": "visual_approach_blocked"}
    steps = []
    for _ in range(3):
        result = []
        if policy._blocked_approach_recovery(world(blocked), "bjorn", result):
            steps.append(result[0].parameters["recovery_step"])
    assert steps == ["JUMP_FORWARD", "STRAFE"]          # bounded: then plain approach again
    ok = {"skill": "VISUAL_APPROACH", "outcome": "SUCCESS", "reason": "visual_interaction_range_supported"}
    assert not policy._blocked_approach_recovery(world(ok), "bjorn", [])
    result = []
    assert policy._blocked_approach_recovery(world(blocked), "bjorn", result)
    assert result[0].parameters["recovery_step"] == "JUMP_FORWARD"   # reset after a success


def test_an_opened_dialog_is_range_evidence_for_the_follow_up_talk():
    from wowbot.agent.execution_bookkeeping import ExecutionBookkeeper
    from wowbot.agent.models import Outcome, Proposal
    from wowbot.agent.planner import Planner
    from wowbot.agent.skills import SkillRegistry
    from wowbot.agent.world import WorldModel
    planner, world = Planner(SkillRegistry()), WorldModel()
    world.state = {"target": dict(TARGET), "active_quests": []}
    planner.quest.interaction_range_blocks["bjorn"] = {"started_at": 1.}
    attempt = SimpleNamespace(proposal=Proposal.make("QUEST_DIALOG", "turn in", {"action": "COMPLETE"}),
                              commands=())
    ExecutionBookkeeper().record_terminal(attempt, Outcome.SUCCESS, "quest_dialog_verified", 5.,
                                          planner=planner, world=world, recovery_resume=None)
    assert "bjorn" not in planner.quest.interaction_range_blocks
    assert planner.quest.recently_verified_in_range("bjorn", 6.)


def test_selected_known_starter_is_talked_to_instead_of_walking_to_the_next_pin():
    """Live 05:47: Alaria (55639, learned starter 156803) was selected 10 yd
    from her "!" pin; the agent left for Hjalmar's pin and fell into the pit."""
    from wowbot.agent.map_poi_planning import MapPoiPlanningPolicy

    def giver(quest_id, x, y):
        return {"quest_id": quest_id, "x": .5, "y": .5, "source": "QUESTLINE_API", "is_campaign": True,
                "world_position": {"x": x, "y": y, "instance_id": 2175, "coordinate_space": "WORLD_YARDS"}}
    alaria = {"guid": "Creature-0-4234-2175-22002-156803-0001CCD4AD", "name": "Alaria",
              "attackable": False, "dead": False}
    state = {"player_world_position": {"x": 102., "y": -2258., "instance_id": 2175},
             "monotonic_time": 1., "active_quests": [], "target": alaria,
             "map_pois": {"available_quests": [giver(55639, 97., -2249.), giver(58915, 355., -2264.)]},
             "reference_knowledge": {"quests": {"55639": {"quest_roles": [
                 {"npc_id": 156803, "role": "QUEST_STARTER"}]}}}}
    policy = MapPoiPlanningPolicy()
    [talk] = policy.quest_giver_moves(SimpleNamespace(state=state))
    assert talk.skill == "INTERACT" and talk.parameters["guid"] == alaria["guid"]
    assert talk.parameters["quest_id"] == 55639
    # Another selected NPC (not the starter) does not stop the pin route.
    other = {**state, "target": {**alaria, "guid": "Creature-0-4234-2175-22002-999999-0001"}}
    assert all(p.skill == "MOVE" for p in MapPoiPlanningPolicy().quest_giver_moves(SimpleNamespace(state=other)))


def test_a_known_non_starter_next_to_a_giver_pin_is_not_selected():
    """Live 05:54: by Alaria's pin (starter 156803) the agent selected and
    talked to Bjorn (156891); Alaria only when the cursor drifted onto her."""
    from wowbot.agent.quest_giver_evidence import known_other_than_pin_starters
    pin = {"quest_id": 55639, "x": .5, "y": .5, "source": "QUESTLINE_API",
           "world_position": {"x": 92., "y": -2247., "instance_id": 2175, "coordinate_space": "WORLD_YARDS"}}
    state = {"player_world_position": {"x": 92.6, "y": -2250.5, "instance_id": 2175},
             "active_quests": [], "map_pois": {"available_quests": [pin]},
             "reference_knowledge": {"quests": {"55639": {"quest_roles": [
                 {"npc_id": 156803, "role": "QUEST_STARTER"}]}}}}
    bjorn = "Creature-0-4234-2175-22002-156891-00004CD4AD"
    alaria = "Creature-0-4234-2175-22002-156803-0001CCD4AD"
    assert known_other_than_pin_starters(state, bjorn)
    assert not known_other_than_pin_starters(state, alaria)
    # Without TDB starter knowledge any nearby NPC may still be the giver.
    unknown = {**state, "reference_knowledge": {}}
    assert not known_other_than_pin_starters(unknown, bjorn)


def test_a_quest_symbol_seen_a_moment_ago_still_counts():
    """Live 05:55:00: the World3D list was empty for ~1 s while Bjorn was
    hovered; "no ! visible" let the pin rule select him."""
    from wowbot.agent.quest_giver_evidence import quest_symbol_visible
    from wowbot.agent.target_planning import TargetPlanningPolicy
    policy = TargetPlanningPolicy()
    seen = {"monotonic_time": 10., "visual_candidates": [
        {"source": "WORLD3D", "kind": "unknown_symbol_candidate", "track_id": "WORLD3D:7"}]}
    assert quest_symbol_visible(policy._with_recent_symbol(seen))
    assert quest_symbol_visible(policy._with_recent_symbol({"monotonic_time": 11.5, "visual_candidates": []}))
    assert not quest_symbol_visible(policy._with_recent_symbol({"monotonic_time": 14., "visual_candidates": []}))
