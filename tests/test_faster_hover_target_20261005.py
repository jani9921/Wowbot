"""Live 2026-10-05 (new character, Exile's Reach, ~1 h run).

* Emergency First Aid: Kee-La was hovered three times and then selected, but
  only the primary objective (the kit on Bjorn) was planned and the search
  MOVE went on; the kit was never used (the user did it by hand).
* 49 empty INSPECTs waited 5.6 s each; a TARGET clicked on the previous
  INSPECT's mouseover (sampled before its own hover) and then waited out the
  8 s deadline.  User: no hover ban on a known unit, make selection faster.
"""
from types import SimpleNamespace

from test_agent_core import state

from wowbot.agent.engine_runtime_projection import movement_visual_interrupt
from wowbot.agent.models import Attempt, Observation, Outcome, Prediction, Proposal
from wowbot.agent.quest_objective_planning import QuestObjectivePlanningMixin
from wowbot.agent.skills import SkillRegistry
from wowbot.agent.world import WorldModel
from wowbot.runtime import ActiveSkillRuntime, Intent, SkillStatus
from wowbot.skills import TargetSkill
from wowbot.skills.hover_confirm import hover_confirm_step

KEE_LA = "Creature-0-4253-2175-58578-156612-000043B69C"
FIRST_AID = {"quest_id": 54951, "title": "Emergency First Aid", "is_complete": False, "objectives": [
    {"description": "0/1 First Aid Kit used on Bjorn Stouthands", "is_complete": False},
    {"description": "0/1 First Aid Kit used on Kee-La", "is_complete": False}]}


def _objective(description):
    return SimpleNamespace(target_object={"item_id": 168410}, description=description,
                           raw={"type": "USE_ITEM", "raw_type": "monster", "item_id": 168410})


def test_sibling_item_objective_is_planned_when_its_unit_is_hovered():
    hovered = {"mouseover": {"guid": KEE_LA, "name": "Kee-La"}}
    at_hand = QuestObjectivePlanningMixin._item_subject_at_hand
    assert at_hand(_objective("0/1 First Aid Kit used on Kee-La"), hovered)
    assert not at_hand(_objective("0/1 First Aid Kit used on Bjorn Stouthands"), hovered)
    assert at_hand(_objective("0/1 First Aid Kit used on Kee-La"),
                   {"target": {"guid": KEE_LA, "name": "Kee-La"}})


def _move(purpose):
    proposal = Proposal.make("MOVE", "test", {"purpose": purpose, "x": -458., "y": -2606.,
                                              "quest_id": 54951})
    return SimpleNamespace(proposal=proposal)


def test_search_move_stops_when_an_objective_unit_is_under_the_cursor():
    world = {"active_quests": [FIRST_AID], "monotonic_time": 10.,
             "mouseover": {"guid": KEE_LA, "name": "Kee-La"}, "mouseover_sample_time": 9.9}
    for purpose in ("SEARCH_LOCAL_OBJECTIVE_AREA", "APPROACH_MINIMAP_QUEST_DOT"):
        assert movement_visual_interrupt(_move(purpose), world)["kind"] == "OBJECTIVE_UNIT_HOVERED"
    assert movement_visual_interrupt(_move("SEARCH_LOCAL_OBJECTIVE_AREA"),
                                     {**world, "mouseover_sample_time": 9.}) is None
    jaina = {**world, "mouseover": {"guid": "Creature-0-1-2-3-4-5", "name": "Lady Jaina Proudmoore"}}
    assert movement_visual_interrupt(_move("SEARCH_LOCAL_OBJECTIVE_AREA"), jaina) is None


def test_hover_confirm_ignores_a_mouseover_sampled_before_the_hover():
    context = {"hovered_at": 10., "hovers": 1, "hover_point": (.1, .6)}
    stale = {"mouseover": {"guid": "murloc"}, "mouseover_sample_time": 9.8}
    assert hover_confirm_step(context, stale, 10.2, expected_guid="murloc")[0] == "WAIT"
    fresh = {"mouseover": {"guid": "murloc"}, "mouseover_sample_time": 10.05}
    assert hover_confirm_step(context, fresh, 10.2, expected_guid="murloc")[0] == "CLICK"


def _active(params, deadline=8.):
    proposal = Proposal.make("TARGET", "test", params)
    attempt = Attempt("a", proposal, {"target": {}}, "o", 1., deadline, (),
                      Prediction("p", "a", "target", 1., deadline, "o"))
    runtime = ActiveSkillRuntime()
    runtime.start(intent=Intent("TARGET", params, params.get("guid")), attempt=attempt, now=1.)
    return runtime.state


def test_missed_click_hovers_again_instead_of_waiting_for_the_deadline():
    skill = TargetSkill()
    target = _active({"guid": "murloc", "hover_x": .1, "hover_y": .6, "click_current_cursor": True})
    assert skill.begin(target).commands[0].kind == "HOVER"
    clicked = skill.verify(target, {"target": {}, "mouseover": {"guid": "murloc"},
                                    "mouseover_sample_time": 1.1}, 1.5)
    assert clicked.commands[0].kind == "CLICK_CURRENT_CURSOR"
    waiting = skill.verify(target, {"target": {}, "target_sample_time": 1.9}, 1.9)
    assert waiting.status is SkillStatus.RUNNING and not waiting.commands
    again = skill.verify(target, {"target": {}, "target_sample_time": 2.3}, 2.3)
    assert again.status is SkillStatus.RUNNING and again.commands[0].kind == "HOVER"


def test_direct_click_without_a_target_change_fails_fast():
    skill = TargetSkill()
    target = _active({"guid": "npc-1", "x": .4, "y": .5})
    skill.begin(target)
    assert skill.verify(target, {"target": {}, "target_sample_time": 1.5}, 1.5).status is SkillStatus.RUNNING
    failed = skill.verify(target, {"target": {}, "target_sample_time": 1.8}, 1.8)
    assert failed.status is SkillStatus.FAILURE and failed.reason.value == "TARGET_NOT_FOUND"


def _inspect(world, payload):
    first = Observation.create(payload, 1.)
    assert world.ingest(first)
    return SimpleNamespace(observation_id=first.observation_id, deadline=6., started_at=1.,
                           baseline=payload, commands=(),
                           proposal=Proposal.make("INSPECT", "test", {"x": .4, "y": .5}))


def test_empty_inspect_answers_once_a_post_hover_sample_names_nothing():
    world = WorldModel()
    attempt = _inspect(world, state(1, mouseover=None, cursor_position={"nx": .1, "ny": .1}))
    early = state(2, mouseover=None, cursor_position={"nx": .4, "ny": .5}, mouseover_sample_time=1.2)
    assert world.ingest(Observation.create(early, 1.25))
    assert SkillRegistry().verify(attempt, world, 1.25)[0] is Outcome.PENDING
    later = state(3, mouseover=None, cursor_position={"nx": .4, "ny": .5}, mouseover_sample_time=1.45)
    assert world.ingest(Observation.create(later, 1.5))
    assert SkillRegistry().verify(attempt, world, 1.5) == (Outcome.FAILURE, "expected_observation_missing")


def _box(x, at, track="WORLD3D:7"):
    return {"source": "WORLD3D", "track_id": track, "x": x, "y": .5, "observed_at": at}


def test_hover_leads_a_moving_box_but_not_while_the_player_turns():
    from wowbot.agent.track_motion import TrackMotion, predicted_point
    motion = TrackMotion()
    for step in range(4):                       # the box walks right at .2 screen/s
        at = 10. + step*.1
        state = {"monotonic_time": at, "orientation": 1., "visual_candidates": [_box(.4+.02*step, at)]}
        motion.observe(state)
    box = state["visual_candidates"][0]
    assert abs(box["screen_velocity"]["x"] - .2) < 1e-6
    x, y = predicted_point(box, {"monotonic_time": 10.5})      # box seen at 10.3, hover at 10.5
    assert abs(x - (.46 + .2*(.2+.06))) < 1e-6 and y == .5
    far = predicted_point({**box, "screen_velocity": {"x": 3., "y": 0.}}, {"monotonic_time": 10.5})
    assert abs(far[0] - (.46+.12)) < 1e-6                     # bounded shift
    turning = TrackMotion()
    for step in range(4):
        at = 10. + step*.1
        state = {"monotonic_time": at, "orientation": 1.+.1*step,
                 "visual_candidates": [_box(.4+.02*step, at)]}
        turning.observe(state)
    assert "screen_velocity" not in state["visual_candidates"][0]
    assert predicted_point(state["visual_candidates"][0], {"monotonic_time": 10.5}) == (.46, .5)


def test_hover_confirm_requires_a_post_hover_sample_time():
    # Issue #88: a retained mouseover without sample time must not click.
    from wowbot.skills.hover_confirm import hover_confirm_step
    context = {"hovered_at": 100., "hovers": 1, "hover_point": (.5, .5)}
    state = {"mouseover": {"guid": "NPC-1"}, "mouseover_sample_time": None}
    verdict, commands = hover_confirm_step(context, state, 100.1, expected_guid="NPC-1")
    assert verdict == "WAIT" and not commands
    state["mouseover_sample_time"] = 100.05
    verdict, commands = hover_confirm_step(context, state, 100.1, expected_guid="NPC-1")
    assert verdict == "CLICK"


def test_compact_fast_mouseover_gets_the_packet_sample_time():
    # Issue #88: the addon's compact FAST fallbacks omit mouseover_sample_time;
    # the reducer must pair the new GUID with the packet's own sample time.
    from wowbot.agent.world_addon_reducer import WorldAddonReducer
    state = {"monotonic_time": 42.5, "mouseover": {"guid": "NPC-1"}}
    WorldAddonReducer._stamp_unit_samples(state)
    assert state["mouseover_sample_time"] == 42.5
    explicit = {"monotonic_time": 42.5, "mouseover": {"guid": "NPC-1"}, "mouseover_sample_time": 40.}
    WorldAddonReducer._stamp_unit_samples(explicit)
    assert explicit["mouseover_sample_time"] == 40.
