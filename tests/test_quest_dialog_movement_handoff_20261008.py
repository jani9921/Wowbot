"""Live 2026-10-08: MOVE started before an NPC's ACCEPT dialog arrived."""
from types import SimpleNamespace

from test_agent_core import agent, state
from test_agent_core import quest_npc_boxes
from wowbot.agent.active_skill_supervision import ActiveSkillSupervisor
from wowbot.agent.models import Goal, Observation, Outcome, Proposal
from wowbot.agent.planner import Planner
from wowbot.agent.skills import SkillRegistry
from wowbot.agent.visual_approach import (VisualApproachController,
                                          VisualApproachPhase,
                                          VisualServoMeasurement)
from wowbot.agent.world import WorldModel
from wowbot.runtime.verification_engine import VerificationEngine


def _world(**extra):
    world = WorldModel()
    world.ingest(Observation.create({
        "session_id": "quest-dialog-handoff", "frame_id": "f1", "timestamp": 1.,
        "monotonic_time": 1., "map_id": 1409, "orientation": 0.,
        "position": {"x": .5, "y": .5}, "player_present": True,
        "active_quests": [], "target": None, "events": [], **extra}, 1.))
    return world


def test_open_accept_dialog_outranks_api_giver_move_and_map():
    world = _world(quest_ui={"open": True, "action": "ACCEPT", "quest_id": 55196,
                             "x": .42, "y": .87})
    planner = Planner(SkillRegistry())
    proposals = planner.candidates(Goal.parse("Questelj", 1.), world, 1.)
    assert proposals and proposals[0].skill == "QUEST_DIALOG"
    assert proposals[0].parameters["quest_id"] == 55196
    assert not any(p.skill in {"MOVE", "VISUAL_APPROACH", "OPEN_MAP"} for p in proposals)


def test_agent_uses_open_accept_dialog_instead_of_a_new_quest_route():
    bot, executor = agent("Questelj")
    payload = state(1., quest_ui={"open": True, "action": "ACCEPT",
                                  "quest_id": 55196, "x": .42, "y": .87})
    bot.tick(payload, 1.)
    assert bot.pending and bot.pending.proposal.skill == "QUEST_DIALOG"
    assert not any(command.binding in {"MOVEFORWARD", "TOGGLEWORLDMAP"}
                   for command in executor.commands)


def test_open_dialog_without_click_coordinates_waits_instead_of_walking():
    world = _world(quest_ui={"open": True, "action": "ACCEPT", "quest_id": 55196,
                             "x": 0, "y": 0})
    planner = Planner(SkillRegistry())
    proposals = planner.candidates(Goal.parse("Questelj", 1.), world, 1.)
    assert proposals[0].skill == "WAIT"
    assert proposals[0].parameters["waiting_for"] == ["QUEST_OR_GOSSIP_UI_DETAILS"]
    for skill in ("MOVE", "VISUAL_APPROACH", "SEEK_VISUAL_CUE", "OPEN_MAP"):
        proposal = Proposal.make(skill, "test", {"x": .5, "y": .4})
        assert not planner.registry.available(proposal, world)


def test_selected_marked_giver_keeps_world_map_closed():
    guid = "Creature-0-1-2-3-156833-1"
    boxes = quest_npc_boxes(.5, .6, "giver")
    world = _world(target={"guid": guid, "attackable": False},
                   mouseover={"guid": guid, "attackable": False},
                   cursor_position={"nx": .5, "ny": .6},
                   visual_candidates=boxes,
                   world_map_open=False)
    planner = Planner(SkillRegistry())
    proposals = []
    planner.map_search_policy.add_quest_fallbacks(
        proposals, Goal.parse("Questelj", 1.), world, 1., blocked_until={})
    assert not any(p.skill == "OPEN_MAP" for p in proposals)


def test_movement_supervision_cancels_when_dialog_arrives_after_start():
    supervisor = ActiveSkillSupervisor(
        m0_skills=None, verification_engine=VerificationEngine(),
        interaction_runtime=None, combat_runtime=None, loot_runtime=None,
        registry=None)
    attempt = SimpleNamespace(proposal=Proposal.make("MOVE", "to giver", {
        "purpose": "LOCATE_API_QUEST_GIVER", "x": 100., "y": 100.}))
    step = supervisor._movement(attempt, {"quest_ui_open": True}, None, "o2", 2., None, None)
    assert step.terminal_outcome is Outcome.CANCELLED
    assert step.stop_movement
    assert step.reason == "interaction_ui_opened_during_move"


def test_fast_dialog_edge_releases_movement_before_detail_page():
    bot, executor = agent("Menj oda", {"destination": {"map_id": 1609, "x": .5, "y": .4}})
    bot.tick(state(1.), 1.)
    before = len(executor.commands)
    fast = state(1.05, transport_kind="FAST", fast_sequence=2,
                 quest_ui_open=True, quest_ui_action="ACCEPT")
    result = bot.fast_movement_control(fast, 1.05)
    assert result["reason"] == "fast_interaction_ui_opened"
    assert len(executor.commands) == before


def test_interaction_range_probe_requires_selected_exact_guid():
    controller = VisualApproachController()
    controller.range_probe_enabled = True
    controller.intent = {"guid": "npc-1", "purpose": "INTERACT"}
    controller.phase = VisualApproachPhase.ADVANCING
    controller.last_interaction_probe_at = 0.
    controller.forward_updates_since_probe = 3
    controller.samples.append(VisualServoMeasurement(
        observation_id="o1", at=.7, track_id="t1", x=.5, y=.5,
        bbox_height=.13, bbox_scale_delta=.004, center_error=0.,
        confidence=.9, source="WORLD3D", lifecycle="ACTIVE", predicted=False,
        camera_motion_x=None, camera_motion_y=None, player_x=None,
        player_y=None, player_heading=None, player_speed=None,
        player_moving=None, telemetry_sample_time=.7, obstacle_evidence=0.,
        visual_sample_time=.7))
    assert controller.range_probe_enabled
    wrong = controller.command({"target": {"guid": "other"}}, "o2", .7)
    assert not any(command.binding == "INTERACTTARGET" for command in wrong)
    controller.forward_updates_since_probe = 3
    correct = controller.command({"target": {"guid": "npc-1"}}, "o3", 1.)
    assert correct and correct[0].binding == "INTERACTTARGET"


def test_fast_growing_npc_box_brakes_before_generic_size_threshold():
    controller = VisualApproachController()
    target = {"guid": "henry", "attackable": False, "dead": False}
    initial = {"target": target, "visual_candidates": [{
        "source": "WORLD3D", "track_id": "henry-box", "x": .51, "y": .62,
        "bbox_height_fraction": .15, "confidence": .8, "lifecycle": "ACTIVE",
        "observed_at": 1.}]}
    controller.start({"guid": "henry", "track_id": "henry-box",
                      "purpose": "INTERACT", "ready_bbox_height": .19},
                     initial, "o1", 1.)
    closer = {**initial, "visual_candidates": [{
        **initial["visual_candidates"][0], "bbox_height_fraction": .166,
        "observed_at": 1.2}]}
    assessment = controller.observe(closer, "o2", 1.2)
    assert assessment.terminal and assessment.success
    assert all(command.binding != "MOVEFORWARD"
               for command in controller.command(closer, "o2", 1.2))
