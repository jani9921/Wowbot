"""M0 SearchSkill contract tests at its ActiveSkillRuntime boundary."""
from wowbot.agent.models import Attempt, Prediction, Proposal
from wowbot.runtime import ActiveSkillRuntime, Intent, SkillStatus
from wowbot.skills import SearchSkill


def _active(parameters: dict):
    proposal = Proposal.make("SEARCH_LOCAL_ENTITY", "m0 search", parameters)
    attempt = Attempt("search-action", proposal, {}, "frame-0", 1., 23., (),
                      Prediction("prediction", "search-action", "search", 1., 23., "frame-0"))
    runtime = ActiveSkillRuntime()
    return runtime.start(intent=Intent("SEARCH_LOCAL_ENTITY", parameters), attempt=attempt,
                         now=1., before_snapshot={})


def test_search_records_bounded_sector_coverage_then_reports_not_found():
    skill, state = SearchSkill(), _active({"purpose": "FIND_LOCAL_ENTITY"})
    seen = []
    started = skill.begin(state, {"visual_candidates": []}, "frame-0", 1.)
    assert started.status is SkillStatus.RUNNING
    seen.extend(started.commands)
    for index in range(1, 4):
        now = 1. + index * .5
        result = skill.observe(state, {"visual_candidates": []}, f"frame-{index}", now)
        assert result.status is SkillStatus.RUNNING
        seen.extend(result.commands)
    snapshot = skill.snapshot(state)
    assert snapshot["scan_index"] == 4
    assert snapshot["camera_updates"] == 4
    assert [(command.x, command.y) for command in seen] == list(skill._controller(state).sectors)
    exhausted = skill.observe(state, {"visual_candidates": []}, "frame-final", 3.3)
    assert exhausted.status is SkillStatus.FAILURE
    assert exhausted.reason.value == "TARGET_NOT_FOUND"
    assert exhausted.metadata["search_outcome"] == "NOT_FOUND_WITHIN_BUDGET"
    assert len(exhausted.metadata["search_context"]["sectors_scanned"]) == 4


def test_search_stops_coverage_when_first_viable_subject_is_found():
    candidate = {
        "source": "WORLD3D", "kind": "unknown_subject_candidate",
        "detector_kind": "unknown_subject_candidate", "track_id": "world3d:1",
        "inspectable": True, "confidence": .9, "stable_frames": 5,
        "x": .5, "y": .55, "bbox_height_fraction": .10,
        "appearance": {"body_geometry": .8, "static_scene_score": .0},
        "visual_relations": [{"type": "ABOVE", "belief": "SUPPORTED"}],
    }
    skill, state = SearchSkill(), _active({**candidate, "purpose": "IDENTIFY"})
    result = skill.begin(state, {"visual_candidates": [candidate]}, "frame-1", 1.)
    # Reaching a visually promising UNKNOWN subject is not recognition.  The
    # canonical search boundary must first hover it and wait for a newer
    # addon/tooltip identity observation.
    assert result.status is SkillStatus.RUNNING
    assert result.metadata["reason"] == "visual_cue_ready_for_hover_identification"
    assert result.commands and result.commands[0].kind == "HOVER"

    identified = skill.observe(state, {
        "visual_candidates": [candidate], "character_guid": "Player-1",
        "mouseover": {"guid": "Creature-1", "name": "Lady Jaina Proudmoore"},
        "mouseover_sample_time": 1.1,
    }, "frame-2", 1.1)
    assert identified.status is SkillStatus.SUCCESS
    assert identified.metadata["reason"] == "identity_available_during_visual_seek"
    assert identified.metadata["search_outcome"] == "FOUND"


def test_search_contract_is_wired_and_context_change_terminates_for_replan():
    skill, active = SearchSkill(), _active({
        "purpose": "FIND_LOCAL_ENTITY", "query": "npc:quest_giver", "radius": 15,
    })
    started = skill.begin(active, {
        "session_id": "s1", "map_id": 2175, "x": 1.0, "y": 2.0,
        "visual_candidates": [],
    }, "frame-0", 1.0)
    context = started.metadata["search_context"]
    assert context["origin"] == (1.0, 2.0)
    assert context["query"] == "npc:quest_giver"
    assert context["radius"] == 15.0

    changed = skill.observe(active, {
        "session_id": "s1", "map_id": 999, "visual_candidates": [],
    }, "frame-1", 1.1)
    assert changed.status is SkillStatus.FAILURE
    assert changed.reason.value == "WRONG_MAP_CONTEXT"
    assert changed.metadata["search_outcome"] == "CONTEXT_CHANGED"
