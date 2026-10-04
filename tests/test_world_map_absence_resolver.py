from wowbot.agent.world_map_absence_resolver import MapAbsenceStep, WorldMapAbsenceResolver


def _resolver():
    return WorldMapAbsenceResolver(max_parent_hops=2)


def test_step_1_verifies_tracked_quest_first():
    directive = _resolver().next_step(
        tracked_quest_confirmed=False, marker_found_at_current_level=None,
        parent_hops_taken=0, marker_found_at_parent_level=None, parent_zone=None)
    assert directive.step is MapAbsenceStep.VERIFY_TRACKED_QUEST


def test_step_2_inspects_current_map_level():
    directive = _resolver().next_step(
        tracked_quest_confirmed=True, marker_found_at_current_level=None,
        parent_hops_taken=0, marker_found_at_parent_level=None, parent_zone=None)
    assert directive.step is MapAbsenceStep.INSPECT_CURRENT_LEVEL


def test_marker_found_at_current_level_is_immediately_done():
    directive = _resolver().next_step(
        tracked_quest_confirmed=True, marker_found_at_current_level=True,
        parent_hops_taken=0, marker_found_at_parent_level=None, parent_zone=None)
    assert directive.step is MapAbsenceStep.DONE_FOUND


def test_no_parent_zone_available_gives_up_rather_than_guessing():
    directive = _resolver().next_step(
        tracked_quest_confirmed=True, marker_found_at_current_level=False,
        parent_hops_taken=0, marker_found_at_parent_level=None, parent_zone=None)
    assert directive.step is MapAbsenceStep.DONE_NOT_FOUND


def test_step_3_steps_out_to_the_parent_zone_when_absent_at_current_level():
    directive = _resolver().next_step(
        tracked_quest_confirmed=True, marker_found_at_current_level=False,
        parent_hops_taken=0, marker_found_at_parent_level=None, parent_zone="Elwynn Forest")
    assert directive.step is MapAbsenceStep.STEP_OUT_TO_PARENT
    assert directive.target_zone == "Elwynn Forest"


def test_step_4_inspects_the_parent_zone_after_stepping_out():
    directive = _resolver().next_step(
        tracked_quest_confirmed=True, marker_found_at_current_level=False,
        parent_hops_taken=1, marker_found_at_parent_level=None, parent_zone="Elwynn Forest")
    assert directive.step is MapAbsenceStep.INSPECT_PARENT_ZONE


def test_step_5_zooms_into_the_target_zone_once_found_in_the_parent():
    directive = _resolver().next_step(
        tracked_quest_confirmed=True, marker_found_at_current_level=False,
        parent_hops_taken=1, marker_found_at_parent_level=True, parent_zone="Elwynn Forest")
    assert directive.step is MapAbsenceStep.ZOOM_INTO_TARGET_ZONE
    assert directive.target_zone == "Elwynn Forest"


def test_not_found_in_parent_zone_either_gives_up():
    directive = _resolver().next_step(
        tracked_quest_confirmed=True, marker_found_at_current_level=False,
        parent_hops_taken=1, marker_found_at_parent_level=False, parent_zone="Elwynn Forest")
    assert directive.step is MapAbsenceStep.DONE_NOT_FOUND


def test_bounded_parent_hops_prevents_climbing_forever():
    directive = _resolver().next_step(
        tracked_quest_confirmed=True, marker_found_at_current_level=False,
        parent_hops_taken=2, marker_found_at_parent_level=None, parent_zone="Azeroth")
    assert directive.step is MapAbsenceStep.DONE_NOT_FOUND
