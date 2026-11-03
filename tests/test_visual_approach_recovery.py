import pytest

from test_agent_core import state
from wowbot.agent.visual_approach import VisualApproachController, VisualApproachPhase


def recovery():
    controller = VisualApproachController()
    target = {"guid": "henry", "attackable": False, "dead": False}
    old = {"source": "CONFIRMED_MOUSEOVER_ANCHOR", "track_association": "CANDIDATE",
           "x": .772, "y": .885, "sample_time": 1., "track_id": "WORLD3D:459"}
    track = {"source": "WORLD3D", "track_id": "WORLD3D:459", "x": .772, "y": .885,
             "confidence": .54, "lifecycle": "ACTIVE", "observed_at": 1.,
             "detector_kind": "unknown_subject_candidate", "bbox_height_fraction": .10}
    controller.start({"guid": "henry", "purpose": "INTERACT", "track_id": "WORLD3D:459",
                      "screen_position": old, "ready_bbox_height": .13},
                     state(1., target=target, visual_candidates=[track]), "v1", 1.)
    # A contradictory pointer response after the turn rejects the track.
    controller.last_pointer_hover_at = 1.01
    wrong = state(1.2, target=target, visual_candidates=[{**track, "observed_at": 1.2}],
                  mouseover={"guid": "kee-la"}, mouseover_sample_time=1.2,
                  cursor_position={"nx": .772, "ny": .885}, cursor_sample_time=1.2)
    controller.observe(wrong, "v2", 1.2)
    assert controller.intent["track_id"] is None
    assert "WORLD3D:459" in controller.rejected_reacquire_track_ids
    fresh = {**track, "x": .536, "y": .664, "observed_at": 3.}
    screen = {"source": "BOUND_WORLD3D_TRACK", "identity_source": "HOVER_SELECTED_TRACK",
              "track_association": "CONFIRMED_GUID_NAMEPLATE", "track_id": "WORLD3D:459",
              "x": .536, "y": .664, "sample_time": 3.}
    current = state(3., target={**target, "screen_position": screen},
                    visual_candidates=[fresh], mouseover=None, mouseover_sample_time=3.,
                    cursor_position={"nx": .772, "ny": .885}, cursor_sample_time=3.)
    return controller, current


def test_fresh_selected_binding_reprobes_rejected_track_at_its_current_position():
    controller, current = recovery()
    controller.observe(current, "v3", 3.)
    commands = controller.command(current, "v3", 3.)
    assert len(commands) == 1 and commands[0].kind == "HOVER"
    assert (commands[0].x, commands[0].y) == (.536, .664)

    confirmed = {**current, "monotonic_time": 3.1, "mouseover": {"guid": "henry"},
                 "mouseover_sample_time": 3.1, "cursor_sample_time": 3.1,
                 "cursor_position": {"nx": .536, "ny": .664},
                 "visual_candidates": [{**current["visual_candidates"][0], "observed_at": 3.1}]}
    controller.observe(confirmed, "v4", 3.1)
    assert controller.intent["track_id"] == "WORLD3D:459"
    assert "WORLD3D:459" not in controller.rejected_reacquire_track_ids
    assert controller.identity_reconfirmations == 1
    assert any(command.binding == "MOVEFORWARD"
               for command in controller.command(confirmed, "v4", 3.1))


@pytest.mark.parametrize("wrong_guid", ["kee-la", None])
def test_selected_binding_is_not_movement_authority_without_confirming_hover(wrong_guid):
    controller, current = recovery()
    controller.observe(current, "v3", 3.)
    controller.command(current, "v3", 3.)
    answered = {**current, "monotonic_time": 5., "mouseover": {"guid": wrong_guid},
                "mouseover_sample_time": 5., "cursor_sample_time": 5.,
                "cursor_position": {"nx": .536, "ny": .664}}
    controller.observe(answered, "v4", 5.)
    assert "WORLD3D:459" in controller.rejected_reacquire_track_ids
    commands = controller.command(answered, "v4", 5.)
    assert not any(command.binding == "MOVEFORWARD" or command.kind == "HOVER"
                   for command in commands)


def test_stale_selected_binding_does_not_repeat_the_old_hover_point():
    controller, current = recovery()
    current["target"]["screen_position"]["sample_time"] = 1.
    controller.observe(current, "v3", 3.)
    commands = controller.command(current, "v3", 3.)
    assert not any(command.kind == "HOVER" or command.binding == "MOVEFORWARD"
                   for command in commands)


def test_a_matching_guid_at_the_old_cursor_point_does_not_confirm_the_new_probe():
    controller, current = recovery()
    controller.observe(current, "v3", 3.)
    controller.command(current, "v3", 3.)
    answered = {**current, "monotonic_time": 3.1, "mouseover": {"guid": "henry"},
                "mouseover_sample_time": 3.1, "cursor_sample_time": 3.1}
    controller.observe(answered, "v4", 3.1)
    assert controller.identity_recheck_requested_at is not None
    assert "WORLD3D:459" in controller.rejected_reacquire_track_ids
    assert controller.command(answered, "v4", 3.1) == ()
