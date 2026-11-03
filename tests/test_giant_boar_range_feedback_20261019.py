"""Large friendly vehicle, repeated range feedback and same-attempt recovery."""
from copy import deepcopy

from wowbot.agent.models import Attempt, Goal, Observation, Prediction, Proposal
from wowbot.agent.planner import Planner
from wowbot.agent.skills import SkillRegistry
from wowbot.agent.visual_approach import VisualApproachController
from wowbot.agent.world import WorldModel
from wowbot.runtime import ActiveSkillRuntime, Intent, SkillStatus
from wowbot.skills import InteractSkill


GUID = "Creature-0-1465-2175-71046-156595-000053399A"
QUEST = {"quest_id": 55879, "is_complete": False, "objectives": [
    {"description": "0/1 Ride the Giant Boar", "type": "INTERACT_NPC", "current": 0,
     "required": 1, "target_entity": {"npc_id": 156595, "name": "Giant Boar"}}]}


def scene(now=1., *, error=False):
    anchor = {"x": .51, "y": .75, "sample_time": now, "track_id": "giant",
              "coordinate_space": "CLIENT_BOTTOM_LEFT", "source": "BOUND_WORLD3D_TRACK",
              "identity_source": "HOVER_SELECTED_TRACK", "track_association": "CONFIRMED_GUID_NAMEPLATE"}
    target = {"guid": GUID, "npc_id": 156595, "name": "Giant Boar", "attackable": False,
              "dead": False, "screen_position": anchor, "visual_track_id": "giant"}
    state = {"target": target, "target_sample_time": now, "monotonic_time": now,
             "active_quests": [QUEST], "mouseover": {"guid": GUID, "npc_id": 156595},
             "mouseover_sample_time": now, "cursor_sample_time": now,
             "cursor_position": {"nx": .51, "ny": .75},
             "visual_candidates": [{"source": "WORLD3D", "track_id": "giant", "x": .51, "y": .75,
                                    "observed_at": now, "confidence": .8, "lifecycle": "ACTIVE",
                                    "bbox_height_fraction": .326}],
             "quest_ui": {"open": False}, "in_vehicle": False,
             "ui_error_sequence": 10, "events": [{"sequence": 10, "event_type": "OTHER"}]}
    if error:
        state.update(ui_error="You need to be closer to interact with that target.",
                     ui_error_code=852, ui_error_at=1.1, ui_error_sequence=11,
                     events=[{"sequence": 11, "event_type": "UI_ERROR_MESSAGE", "payload": {
                         "error_code": 852, "message": "You need to be closer to interact with that target.",
                         "observed_at": 1.1}}])
    return state


def active():
    before = scene()
    proposal = Proposal.make("INTERACT", "ride", {"guid": GUID})
    attempt = Attempt("giant-a", proposal, before, "obs1", 1., 15., (),
                      Prediction("giant-p", "giant-a", "vehicle", 1., 15., "obs1"))
    return ActiveSkillRuntime().start(intent=Intent("INTERACT", proposal.parameters, GUID),
                                      attempt=attempt, now=1., before_snapshot=before)


def test_range_recovery_requires_real_steps_even_when_giant_box_is_already_large():
    skill, run = InteractSkill(), active()
    skill.begin(run, scene())
    failed = scene(1.1, error=True)
    result = skill.verify(run, failed, 1.1)
    request = result.metadata["approach_request"]
    assert request.get("range_failures") == 1
    controller = VisualApproachController()
    assessment = controller.start(request, failed, "r1", 1.1)
    assert not assessment.terminal
    assert any(c.binding == "MOVEFORWARD" for c in controller.command(failed, "r1", 1.1))


def test_same_error_after_approach_is_consumed_once_and_new_press_gets_a_fresh_timer():
    skill, run = InteractSkill(), active()
    skill.begin(run, scene())
    original = deepcopy(run.before_snapshot)
    skill.verify(run, scene(1.1, error=True), 1.1)
    skill.resume_after_approach(run, scene(2., error=True), now=2.)
    result = skill.verify(run, scene(2.1, error=True), 2.1)
    assert result.status is SkillStatus.RUNNING and not result.commands
    assert not result.metadata.get("approach_request")
    assert run.skill_context["interaction"]["approach_attempts"] == 1
    assert run.skill_context["interaction"]["last_interact_at"] == 2.
    assert run.before_snapshot == original  # quest verification baseline is immutable
    newer = scene(2.2, error=True)
    newer["ui_error_sequence"] = 12
    newer["events"][0]["sequence"] = 12
    retry = skill.verify(run, newer, 2.2)
    assert retry.metadata["approach_request"]["range_failures"] == 2


def test_vehicle_entry_verifies_after_recovery_despite_retained_old_error():
    skill, run = InteractSkill(), active()
    skill.begin(run, scene())
    skill.verify(run, scene(1.1, error=True), 1.1)
    skill.resume_after_approach(run, scene(2., error=True), now=2.)
    seated = {**scene(2.2, error=True), "in_vehicle": True}
    assert skill.verify(run, seated, 2.2).status is SkillStatus.SUCCESS


def test_old_ui_error_cannot_reopen_range_block_after_newer_successful_approach(monkeypatch):
    world = WorldModel()
    data = {**scene(1.25, error=True), "timestamp": 1.25, "session_id": "giant", "map_id": 1409}
    world.ingest(Observation.create(data, 1.25))
    planner = Planner(SkillRegistry())
    planner.quest.approach_verified_at[GUID] = 1.2
    monkeypatch.setattr("wowbot.agent.quest_target_planning.time.monotonic", lambda: 1.25)
    result = planner.quest.propose(world.planning_snapshot(1.25), Goal.parse("Questelj", 1.25))
    assert any(p.skill == "INTERACT" for p in result)
    assert not any(p.skill == "VISUAL_APPROACH" for p in result)


def test_friendly_range_recovery_cannot_use_a_retained_harmful_spell_range():
    data = scene()
    data["actionbar"] = [{"is_harmful": True, "in_range": True}]
    controller = VisualApproachController()
    assessed = controller.start({"guid": GUID, "track_id": "giant", "purpose": "INTERACT",
                                 "range_failures": 1}, data, "o1", 1.)
    assert not assessed.terminal
