"""Live 2026-10-06 (Hrun's pit, "0/5 Trapped Expedition Member rescued from
cocoons"): the learned detector saw the cocoons (quest_object_outline_like,
104 boxes up to 0.8 in one run) but the sweep walked past them and nothing
ever hovered or used one; the objective gave no object name at all."""
from types import SimpleNamespace

from wowbot.agent.models import Observation
from wowbot.agent.world_anchor_reducer import WorldAnchorReducer
from wowbot.agent.engine_runtime_projection import movement_visual_interrupt
from wowbot.agent.models import Proposal
from wowbot.agent.object_interaction_flow import (ObjectInteractionFlow, name_matches,
                                                  quest_object_candidates)
from wowbot.agent.quest_semantics import world_object_subjects
from wowbot.agent.tooltip_quest import effective_mouseover
from wowbot.runtime import SkillStatus
from wowbot.skills.object_use import ObjectUseSkill

COCOONS = {"description": "0/5 Trapped Expedition Member rescued from cocoons", "type": "INTERACT",
           "raw_type": "object", "is_complete": False, "current": 0, "required": 5}
QUEST = {"quest_id": 55639, "title": "Who Lurks in the Pit", "is_complete": False, "objectives": [COCOONS]}
BOX = {"source": "WORLD3D", "track_id": "WORLD3D:31", "kind": "unknown_object_candidate",
       "candidate_labels": ["learned_object_like", "quest_object_like", "outline_like_cue"],
       "confidence": .78, "stable_frames": 6, "x": .6, "y": .55, "bbox_height_fraction": .09}
SOFT = {"source_unit": "softinteract", "guid": "GameObject-0-3113-2175-63341-341534-00004A1B2C",
        "object_id": 341534, "name": "Thick Cocoon", "unit_type": "GAMEOBJECT"}


def _objective():
    return SimpleNamespace(objective_id="55639:0", type="INTERACT", description=COCOONS["description"],
                           raw=COCOONS, target_object=None, confidence=.9)


def test_the_cocoon_objective_names_its_object():
    subjects = world_object_subjects(COCOONS)
    assert subjects == ["cocoons"]
    assert name_matches(subjects, "Thick Cocoon") and not name_matches(subjects, "Barrow Spider")


def test_fast_structured_name_is_enough_when_the_quest_hover_is_current():
    identity = ObjectInteractionFlow.expected_identity(_objective())
    mouse = {"name": "Thick Cocoon", "quest_related": True, "quest_id": 55639}
    assert effective_mouseover({"mouseover": mouse}) == mouse
    assert ObjectInteractionFlow.mouseover_matches(identity, mouse)
    assert not ObjectInteractionFlow.mouseover_matches(identity,
        {"name": "Thick Cocoon", "quest_related": False})
    assert not ObjectInteractionFlow.mouseover_matches(identity,
        {"name": "Barrow Spider", "quest_related": True, "quest_id": 55639})


def test_only_stable_learned_quest_object_boxes_count():
    weak = {**BOX, "confidence": .15}
    live_cocoon = {**BOX, "track_id": "WORLD3D:134", "confidence": .25,
                   "stable_frames": 30}
    unit = {**BOX, "candidate_labels": ["learned_subject_like"]}
    assert quest_object_candidates({"visual_candidates": [weak, unit, BOX, live_cocoon]}) == [BOX, live_cocoon]


def test_a_seen_cocoon_box_is_approached_and_hovered():
    steps = ObjectInteractionFlow().propose_object_steps(_objective(), None, {"visual_candidates": [BOX]})
    seek = steps[0]
    assert seek.skill == "SEEK_VISUAL_CUE" and seek.parameters["purpose"] == "SEARCH_LOCAL_OBJECT"
    assert seek.parameters["track_id"] == "WORLD3D:31" and seek.priority == 90
    assert seek.parameters["expected_tooltips"] == ["cocoons"]


def _live_hovered_cocoon(height=.106):
    return {"monotonic_time": 100., "mouseover_sample_time": 99.95,
            "cursor_sample_time": 99.95,
            "mouseover": {"name": "Thick Cocoon", "quest_related": True,
                          "quest_id": 55639},
            "cursor_position": {"nx": .6, "ny": .55},
            "visual_candidates": [{**BOX, "observed_at": 99.9,
                                   "bbox_height_fraction": height,
                                   "bbox_width_fraction": .04,
                                   "lifecycle": "ACTIVE"}]}


def test_fresh_named_cocoon_is_not_range_blocked_by_small_box():
    flow = ObjectInteractionFlow()
    seen = _live_hovered_cocoon()
    steps = flow.propose_object_steps(_objective(), None, seen)
    assert [step.skill for step in steps] == ["SEEK_VISUAL_CUE"]
    assert steps[0].parameters["track_id"] == BOX["track_id"]
    assert flow.propose_object_steps(_objective(), None,
                                     _live_hovered_cocoon(.2))[0].skill == "SEEK_VISUAL_CUE"


def test_object_approach_requires_current_quest_hover_on_that_box():
    flow = ObjectInteractionFlow()
    seen = _live_hovered_cocoon()
    flow.note_result({"action_id": "range-confirm", "skill": "OBJECT_USE",
                      "outcome": "FAILURE", "reason": "out_of_range"}, seen)
    cases = ({**seen, "mouseover_sample_time": 98.},
             {**seen, "mouseover": {"name": "Barrow Spider", "quest_related": True,
                                    "quest_id": 55639}},
             {**seen, "cursor_position": {"nx": .2, "ny": .2}},
             {**seen, "mouseover": {"name": "Thick Cocoon", "quest_related": True,
                                    "quest_id": 99999}})
    for state in cases:
        assert not any(step.skill == "VISUAL_APPROACH" for step in
                       flow.propose_object_steps(_objective(), None, state))


def test_out_of_range_cocoon_approach_moves_instead_of_rehovering():
    from wowbot.agent.visual_approach import VisualApproachController
    flow = ObjectInteractionFlow()
    seen = _live_hovered_cocoon()
    flow.note_result({"action_id": "range-1", "skill": "OBJECT_USE",
                      "outcome": "FAILURE", "reason": "out_of_range"}, seen)
    approach = flow.propose_object_steps(_objective(), None, seen)[0]
    assert approach.skill == "VISUAL_APPROACH"
    assert approach.parameters["range_failures"] == 1
    servo = VisualApproachController()
    servo.start(approach.parameters, seen, "frame-1", 100.)
    commands = servo.command(seen, "frame-1", 100.)
    assert any(command.binding == "MOVEFORWARD" for command in commands)


def test_object_range_errors_use_npc_style_five_three_two_forward_pulses():
    from wowbot.agent.visual_approach import VisualApproachController
    flow = ObjectInteractionFlow()
    seen = _live_hovered_cocoon(height=.10)
    seen["cursor_position"] = {"nx": .5, "ny": .55}
    seen["visual_candidates"][0]["x"] = .5
    for attempt, required in enumerate((5, 3, 2), start=1):
        flow.note_result({"action_id": f"range-{attempt}", "skill": "OBJECT_USE",
                          "outcome": "FAILURE", "reason": "out_of_range"}, seen)
        approach = flow.propose_object_steps(_objective(), None, seen)[0]
        assert approach.skill == "VISUAL_APPROACH"
        assert approach.parameters["range_failures"] == attempt
        servo = VisualApproachController()
        assert not servo.start(approach.parameters, seen, f"start-{attempt}", 100.).terminal
        servo.forward_commands_total = required-1
        seen.update(monotonic_time=100.1, mouseover_sample_time=100.1,
                    cursor_sample_time=100.1)
        seen["visual_candidates"][0]["observed_at"] = 100.1
        assert not servo.observe(seen, f"before-{attempt}", 100.1).terminal
        servo.forward_commands_total = required
        seen.update(monotonic_time=100.2, mouseover_sample_time=100.2,
                    cursor_sample_time=100.2)
        seen["visual_candidates"][0]["observed_at"] = 100.2
        ready = servo.observe(seen, f"after-{attempt}", 100.2)
        assert ready.terminal and ready.success
        flow.note_result({"action_id": f"approach-{attempt}",
                          "skill": "VISUAL_APPROACH", "outcome": "SUCCESS"}, seen)
    flow.note_result({"action_id": "credited", "skill": "OBJECT_USE",
                      "outcome": "SUCCESS"}, seen)
    assert not flow.range_blocked(seen)
    flow.note_result({"action_id": "next-cocoon-range", "skill": "OBJECT_USE",
                      "outcome": "FAILURE", "reason": "out_of_range"}, seen)
    assert flow.propose_object_steps(_objective(), None, seen)[0].parameters["range_failures"] == 1


def test_soft_interact_cocoon_does_not_repeat_f7_after_range_error():
    flow = ObjectInteractionFlow()
    seen = {**_live_hovered_cocoon(), "soft_targets": [SOFT]}
    flow.note_result({"action_id": "soft-range", "skill": "OBJECT_USE",
                      "outcome": "FAILURE", "reason": "out_of_range"}, seen)
    steps = flow.propose_object_steps(_objective(), None, seen)
    assert [step.skill for step in steps] == ["VISUAL_APPROACH"]


def test_cursor_shift_on_same_cocoon_does_not_clear_client_range_error():
    flow = ObjectInteractionFlow()
    seen = _live_hovered_cocoon()
    flow.note_result({"action_id": "shift-range", "skill": "OBJECT_USE",
                      "outcome": "FAILURE", "reason": "out_of_range"}, seen)
    shifted = {**seen, "cursor_position": {"nx": .7, "ny": .55},
               "visual_candidates": [{**seen["visual_candidates"][0], "x": .7}]}
    assert flow.range_blocked(shifted)
    assert flow.propose_object_steps(_objective(), None, shifted)[0].skill == "VISUAL_APPROACH"
    other = {**shifted, "mouseover": {"name": "Other Object",
                                     "quest_related": True, "quest_id": 55639}}
    assert not flow.range_blocked(other)


def test_terminal_range_error_survives_intervening_seek_result():
    """19:55 live: right-click failed OUT_OF_RANGE, then rapid SEEK results
    replaced last_result before the cocoon hover and box were both fresh."""
    from wowbot.agent.quest_planning import QuestDomain
    quest = QuestDomain()
    failed_view = {**_live_hovered_cocoon(), "mouseover": {},
                   "visual_candidates": []}
    quest.note_object_interaction_result(
        {"action_id": "live-range", "skill": "OBJECT_USE",
         "outcome": "FAILURE", "reason": "out_of_range"}, failed_view, {})
    quest.note_object_interaction_result(
        {"action_id": "later-seek", "skill": "SEEK_VISUAL_CUE",
         "outcome": "SUCCESS"}, failed_view, {})
    fresh = _live_hovered_cocoon(height=.09)
    fresh.update(monotonic_time=100.4, mouseover_sample_time=100.4,
                 cursor_sample_time=100.4,
                 cursor_position={"nx": .485, "ny": .583})
    fresh["visual_candidates"][0].update(
        track_id="WORLD3D:539", x=.485, y=.583, observed_at=100.4)
    flow = quest.location_policy.object_interaction
    assert flow.range_blocked(fresh)
    steps = flow.propose_object_steps(_objective(), None, fresh)
    assert [step.skill for step in steps] == ["VISUAL_APPROACH"]
    assert steps[0].parameters["range_failures"] == 1


def test_engine_finish_latches_object_range_error_before_replanning():
    from test_agent_core import agent
    from wowbot.agent.models import Attempt, Outcome, Prediction
    value, _ = agent()
    view = _live_hovered_cocoon()
    value.world.state = view
    proposal = Proposal.make("OBJECT_USE", "live cocoon", {
        "objective_id": "55639:0", "quest_ids": [55639],
        "x": .6, "y": .55, "mouseover_tooltip": "Thick Cocoon"})
    value.pending = Attempt(
        "cocoon-range", proposal, view, "cocoon-before", 99., 107., (),
        Prediction("cocoon-prediction", "cocoon-range", "quest_credit",
                   99., 107., "cocoon-before"))
    value._finish(Outcome.FAILURE, "out_of_range", 100.)
    flow = value.planner.quest.location_policy.object_interaction
    assert flow.range_blocked(view)
    assert flow.propose_object_steps(_objective(), None, view)[0].skill == "VISUAL_APPROACH"


def test_cocoon_overlapping_avatar_is_not_falsely_in_range():
    """18:36 live: a .10-height cocoon overlapped the avatar on screen,
    but the client had just returned OUT_OF_RANGE one floor below."""
    from wowbot.agent.visual_approach import VisualApproachController
    seen = _live_hovered_cocoon()
    cocoon = seen["visual_candidates"][0]
    cocoon.update(x=.4694, y=.5775, bbox_height_fraction=.103,
                  bbox_width_fraction=.0345,
                  bbox={"left": 669, "top": 285, "right": 720, "bottom": 363})
    seen["cursor_position"] = {"nx": .4694, "ny": .5775}
    seen["visual_candidates"].append({
        "source": "WORLD3D", "track_id": "WORLD3D:self",
        "self_player_avatar": True,
        "bbox": {"left": 717, "top": 368, "right": 762, "bottom": 449},
        "bbox_width_fraction": .0304, "bbox_height_fraction": .1056})
    flow = ObjectInteractionFlow()
    flow.note_result({"action_id": "range-overlap", "skill": "OBJECT_USE",
                      "outcome": "FAILURE", "reason": "out_of_range"}, seen)
    approach = flow.propose_object_steps(_objective(), None, seen)[0]
    assert approach.skill == "VISUAL_APPROACH"
    servo = VisualApproachController()
    assessment = servo.start(approach.parameters, seen, "live-like-frame", 100.)
    assert not assessment.terminal
    assert any(command.binding == "MOVEFORWARD" for command in
               servo.command(seen, "live-like-frame", 100.))


def test_planner_uses_fresh_named_hover_even_when_box_is_small():
    from test_exile_reach_starting_mechanics import world
    from wowbot.agent.models import Goal
    from wowbot.agent.planner import Planner
    from wowbot.agent.skills import SkillRegistry
    seen = _live_hovered_cocoon()
    seen.update(monotonic_time=1., mouseover_sample_time=.95,
                cursor_sample_time=.95)
    seen["visual_candidates"][0]["observed_at"] = .9
    state = world(active_quests=[QUEST], **seen)
    proposals = Planner(SkillRegistry()).candidates(Goal.parse("Questelj", 1), state, 1.)
    assert proposals[0].skill == "OBJECT_USE"
    assert proposals[0].parameters.get("mouseover_tooltip") == "Thick Cocoon"
    assert not any(p.skill == "VISUAL_APPROACH" and
                   p.parameters.get("object_use_approach") for p in proposals)


def test_planner_approaches_same_cocoon_after_client_range_error():
    from test_exile_reach_starting_mechanics import world
    from wowbot.agent.models import Goal
    from wowbot.agent.planner import Planner
    from wowbot.agent.skills import SkillRegistry
    seen = _live_hovered_cocoon()
    seen.update(monotonic_time=1., mouseover_sample_time=.95,
                cursor_sample_time=.95)
    seen["visual_candidates"][0]["observed_at"] = .9
    planner = Planner(SkillRegistry())
    planner.quest.location_policy.object_interaction.note_result(
        {"action_id": "range-planner", "skill": "OBJECT_USE",
         "outcome": "FAILURE", "reason": "out_of_range"}, seen)
    proposals = planner.candidates(Goal.parse("Questelj", 1),
                                   world(active_quests=[QUEST], **seen), 1.)
    assert proposals[0].skill == "VISUAL_APPROACH"
    assert proposals[0].parameters.get("object_use_approach") is True
    assert not any(p.skill == "OBJECT_USE" for p in proposals)


def test_object_use_distinguishes_range_from_line_of_sight_and_blocks_same_wall():
    from wowbot.runtime import FailureReason
    context = {"used_at": 100.}
    assert ObjectUseSkill._position_error(
        context, {"ui_error_at": 100.2, "ui_error": "You are too far away."}) == FailureReason.OUT_OF_RANGE
    assert ObjectUseSkill._position_error(
        context, {"ui_error_at": 100.2, "ui_error": "Target not in line of sight."}) == FailureReason.LINE_OF_SIGHT
    assert ObjectUseSkill._position_error(
        context, {"ui_error_at": 99.8, "ui_error": "Target not in line of sight."}) is None
    flow = ObjectInteractionFlow()
    seen = {**_live_hovered_cocoon(),
            "player_world_position": {"instance_id": 2175, "x": 85., "y": -2239.}}
    flow.note_result({"action_id": "los-1", "skill": "OBJECT_USE",
                      "outcome": "FAILURE", "reason": "line_of_sight"}, seen)
    assert flow.line_of_sight_blocked(seen)
    assert flow.propose_object_steps(_objective(), None, seen) == []
    from test_exile_reach_starting_mechanics import world
    from wowbot.agent.models import Goal
    from wowbot.agent.planner import Planner
    from wowbot.agent.skills import SkillRegistry
    planner = Planner(SkillRegistry())
    planner_seen = {**seen, "monotonic_time": 1., "mouseover_sample_time": .95,
                    "cursor_sample_time": .95,
                    "visual_candidates": [{**seen["visual_candidates"][0], "observed_at": .9}]}
    planner.quest.location_policy.object_interaction.note_result(
        {"action_id": "los-1", "skill": "OBJECT_USE", "outcome": "FAILURE",
         "reason": "line_of_sight"}, planner_seen)
    proposals = planner.candidates(Goal.parse("Questelj", 1),
                                   world(active_quests=[QUEST], **planner_seen), 1.)
    assert not any(p.skill == "OBJECT_USE" for p in proposals)
    moved = {**seen, "player_world_position": {"instance_id": 2175,
                                                "x": 88., "y": -2239.}}
    assert not flow.line_of_sight_blocked(moved)
    assert flow.propose_object_steps(_objective(), None, moved)[0].skill == "SEEK_VISUAL_CUE"


def test_the_soft_interact_cocoon_is_used_with_the_interact_key():
    steps = ObjectInteractionFlow().propose_object_steps(
        _objective(), None, {"visual_candidates": [BOX], "soft_targets": [SOFT]})
    assert steps[0].skill == "SEEK_VISUAL_CUE"
    use = steps[1]
    # Issue #99: the identity-matched soft target outranks the box SEEK.
    assert (use.skill, use.parameters["activation_source"]) == ("OBJECT_USE", "INTERACT_KEY")
    assert use.priority > steps[0].priority
    skill = ObjectUseSkill()
    state = SimpleNamespace(intent=SimpleNamespace(parameters=use.parameters, objective_ref="55639:0"),
                            skill_context={}, phase=None)
    begun = skill.begin(state, {"soft_targets": [SOFT]})
    assert begun.commands[0].binding == "INTERACTTARGET"
    gone = skill.begin(state, {"soft_targets": []})
    assert gone.status is SkillStatus.FAILURE


def test_the_zone_sweep_stops_when_a_cocoon_is_seen():
    move = SimpleNamespace(proposal=Proposal.make("MOVE", "sweep", {
        "purpose": "LOCATE_QUEST_OBJECTIVE_REGION", "quest_id": 55639, "location_source": "QUEST_ZONE_SWEEP",
        "x": 80., "y": -2240.}))
    seen = {"active_quests": [QUEST], "visual_candidates": [BOX], "player_world_position": {"x": 80., "y": -2250.}}
    assert movement_visual_interrupt(move, seen)["kind"] == "QUEST_OBJECT_VISIBLE"
    done = {**seen, "active_quests": [{**QUEST, "objectives": [{**COCOONS, "is_complete": True}]}]}
    assert (movement_visual_interrupt(move, done) or {}).get("kind") != "QUEST_OBJECT_VISIBLE"


def test_the_planner_walks_to_a_seen_cocoon_before_anything_else():
    from test_exile_reach_starting_mechanics import world
    from wowbot.agent.models import Goal
    from wowbot.agent.planner import Planner
    from wowbot.agent.skills import SkillRegistry
    state = world(active_quests=[QUEST], visual_candidates=[BOX],
                  player_world_position={"x": 80., "y": -2250., "instance_id": 2175,
                                         "coordinate_space": "WORLD_YARDS"})
    proposals = Planner(SkillRegistry()).candidates(Goal.parse("Questelj", 1), state, 1)
    best = max(proposals, key=lambda proposal: proposal.priority)
    assert best.skill == "SEEK_VISUAL_CUE" and best.parameters.get("purpose") == "SEARCH_LOCAL_OBJECT"


def test_planner_uses_fast_named_cocoon_without_waiting_for_paged_event():
    from test_exile_reach_starting_mechanics import world
    from wowbot.agent.models import Goal
    from wowbot.agent.planner import Planner
    from wowbot.agent.skills import SkillRegistry
    state = world(active_quests=[QUEST], visual_candidates=[BOX],
                  mouseover={"name": "Thick Cocoon", "quest_related": True,
                             "quest_id": 55639},
                  cursor_position={"nx": .57909, "ny": .519})
    proposals = Planner(SkillRegistry()).candidates(Goal.parse("Questelj", 1), state, 1)
    uses = [p for p in proposals if p.skill == "OBJECT_USE"]
    assert uses and uses[0].parameters["mouseover_tooltip"] == "Thick Cocoon"
    wrong_quest = world(active_quests=[QUEST], visual_candidates=[BOX],
                        mouseover={"name": "Thick Cocoon", "quest_related": True,
                                   "quest_id": 99999},
                        cursor_position={"nx": .57909, "ny": .519})
    proposals = Planner(SkillRegistry()).candidates(Goal.parse("Questelj", 1), wrong_quest, 1)
    assert not any(p.skill == "OBJECT_USE" for p in proposals)


def test_delayed_cocoon_event_does_not_survive_camera_turn_at_same_cursor():
    """12:17:44 live: tooltip arrived 6 s after cursor placement, then the
    player turned; the old point clicked bare ground while cocoon was at edge."""
    cursor = (.46929138383504, .62006079485365)
    memory = {"payload": {"tooltip": "Thick Cocoon ~ Who Lurks in the Pit ~ 0/5 rescued",
                          "quest_id": 55639, "object_id": 0, "tooltip_data": {}},
              "still_for": 6.09, "ingested_at": 674612.003,
              "cursor": cursor, "event_cursor": cursor,
              "cursor_view": {"orientation": 4.777677, "camera_yaw": 3620.,
                              "player_x": 70.98, "player_y": -2255.64}}
    state = {"mouseover": False, "cursor_position": {"nx": cursor[0], "ny": cursor[1]},
             "monotonic_time": 674612.405, "orientation": .68261,
             "camera_yaw_estimate": 3164.,
             "player_world_position": {"x": 70.98, "y": -2255.64},
             "mouseover_object_memory": memory}
    assert not effective_mouseover(state).get("tooltip")
    # Even a promptly delivered event cannot authorize the old pixel after
    # rotation, and the MAX_STILL check independently guards long delays.
    memory["still_for"] = 2.
    assert not effective_mouseover(state).get("tooltip")


def test_cocoon_name_survives_pointer_slide_only_while_live_quest_hover_is_continuous():
    """12:53: the cursor slid .54 -> .475 within the cocoon, with no second
    MOUSEOVER_CHANGED; the FAST quest flag stayed true throughout."""
    model = SimpleNamespace()
    reducer = WorldAnchorReducer()
    event = {"event_type": "MOUSEOVER_CHANGED", "sequence": 6633,
             "timestamp": 98, "payload": {"quest_id": 55639,
             "tooltip": "Thick Cocoon ~ Who Lurks in the Pit ~ 0/5 rescued"}}
    first = {"mouseover": {"quest_related": True, "quest_id": 55639},
             "cursor_position": {"nx": .54, "ny": .29},
             "mouseover_sample_time": 1., "monotonic_time": 1.,
             "orientation": 1.55, "timestamp": 100, "events": [event]}
    reducer.track_mouseover_object(model, first, Observation.create(first, 1.))
    # A repeated FAST packet at a moved cursor is not new mouseover evidence.
    repeated = {**first, "events": [], "cursor_position": {"nx": .475, "ny": .29},
                "monotonic_time": 1.2}
    reducer.track_mouseover_object(model, repeated, Observation.create(repeated, 1.2))
    assert not effective_mouseover({**repeated, "mouseover_object_memory": model.mouseover_object_memory}).get("name")
    second = {**first, "events": [], "cursor_position": {"nx": .475, "ny": .29},
              "mouseover_sample_time": 2., "monotonic_time": 2., "orientation": 2.63}
    reducer.track_mouseover_object(model, second, Observation.create(second, 2.))
    assert effective_mouseover({**second, "mouseover_object_memory": model.mouseover_object_memory})[
        "name"] == "Thick Cocoon"
    lost = {**second, "mouseover": False, "monotonic_time": 3., "mouseover_sample_time": 3.}
    reducer.track_mouseover_object(model, lost, Observation.create(lost, 3.))
    assert not effective_mouseover({**lost, "mouseover_object_memory": model.mouseover_object_memory}).get("name")
    resumed = {**lost, "mouseover": {"quest_related": True, "quest_id": 55639},
               "monotonic_time": 4., "mouseover_sample_time": 4.}
    reducer.track_mouseover_object(model, resumed, Observation.create(resumed, 4.))
    assert not effective_mouseover({**resumed, "mouseover_object_memory": model.mouseover_object_memory}).get("name")


def test_planner_ranks_a_matching_soft_target_use_above_the_box_seek():
    """Issue #99: with a visible cocoon box AND the matching soft-interact
    object, ProposalRanker chose SEEK_VISUAL_CUE and the F7 use starved."""
    from test_exile_reach_starting_mechanics import world
    from wowbot.agent.models import Goal
    from wowbot.agent.planner import Planner
    from wowbot.agent.proposal_ranking import ProposalRanker
    from wowbot.agent.skills import SkillRegistry
    state = world(active_quests=[QUEST], visual_candidates=[BOX], soft_targets=[SOFT],
                  player_world_position={"x": 80., "y": -2250., "instance_id": 2175,
                                         "coordinate_space": "WORLD_YARDS"})
    registry = SkillRegistry()
    proposals = Planner(registry).candidates(Goal.parse("Questelj", 1), state, 1)
    assert any(p.skill == "SEEK_VISUAL_CUE" for p in proposals)
    ranked = ProposalRanker.rank(proposals, goal=Goal.parse("Questelj", 1), world=state, now=1.,
                                 registry=registry, memory=None, blocked_until={}, recent={},
                                 evidence=())
    assert ranked.proposals[0].skill == "OBJECT_USE"
    assert ranked.proposals[0].parameters["object_id"] == 341534
    # A soft target that is not the objective's object changes nothing.
    other = world(active_quests=[QUEST], visual_candidates=[BOX],
                  soft_targets=[{**SOFT, "object_id": 1, "name": "Crate"}],
                  player_world_position={"x": 80., "y": -2250., "instance_id": 2175,
                                         "coordinate_space": "WORLD_YARDS"})
    proposals = Planner(registry).candidates(Goal.parse("Questelj", 1), other, 1)
    assert not any(p.skill == "OBJECT_USE" for p in proposals)
