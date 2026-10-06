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


def test_the_soft_interact_cocoon_is_used_with_the_interact_key():
    steps = ObjectInteractionFlow().propose_object_steps(
        _objective(), None, {"visual_candidates": [BOX], "soft_targets": [SOFT]})
    assert steps[0].skill == "SEEK_VISUAL_CUE"
    use = steps[1]
    assert (use.skill, use.parameters["activation_source"], use.priority) == ("OBJECT_USE", "INTERACT_KEY", 70)
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
