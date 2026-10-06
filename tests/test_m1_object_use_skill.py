from wowbot.agent.models import Attempt, Prediction, Proposal
from wowbot.runtime import ActiveSkillRuntime, Intent, SkillStatus
from wowbot.skills import ObjectUseSkill


def _state(*, cursor=(.4, .6), object_id=77):
    return {"mouseover": {"object_id": object_id, "tooltip": "Campfire"},
            "cursor_position": {"nx": cursor[0], "ny": cursor[1]}}


def _active():
    params = {"x": .4, "y": .6, "object_id": 77, "mouseover_tooltip": "Campfire",
              "quest_ids": [10], "objective_ids": ["10:0"]}
    before = {**_state(), "active_quests": [{"quest_id": 10, "objectives": [
        {"objective_id": "0", "current": 0, "required": 1, "is_complete": False},
    ]}]}
    attempt = Attempt("action", Proposal.make("OBJECT_USE", "test", params), before,
                      "obs", 1., 5., (), Prediction("prediction", "action", "state", 1., 5., "obs"))
    return ActiveSkillRuntime().start(intent=Intent("OBJECT_USE", params, None, "10:0"),
                                       attempt=attempt, now=1., before_snapshot=before)


def test_object_use_requires_current_mouseover_identity_and_only_quest_credit_succeeds():
    skill, state = ObjectUseSkill(), _active()
    started = skill.begin(state, _state())
    assert started.status is SkillStatus.RUNNING
    assert started.commands[0].kind == "HOVER"
    # The engine sets VERIFY before the skill's own tick; this must not skip
    # hover confirmation or wait 8 seconds without dispatching a right-click.
    state.phase = "VERIFY"
    confirmed = skill.verify(state, _state(), 1.2)
    assert confirmed.commands[0].kind == "CLICK" and confirmed.commands[0].button == "RIGHT"
    event_only = {**_state(), "events": [{"event_type": "OBJECT_USED", "payload": {"object_id": 77}}]}
    assert skill.verify(state, event_only, 2.).status is SkillStatus.RUNNING
    credited = {**_state(), "active_quests": [{"quest_id": 10, "objectives": [
        {"objective_id": "0", "current": 1, "required": 1, "is_complete": True},
    ]}]}
    assert skill.verify(state, credited, 3.).status is SkillStatus.SUCCESS


def test_object_use_rejects_stale_cursor_or_wrong_hovered_object():
    assert ObjectUseSkill().begin(_active(), _state(cursor=(.41, .6))).status is SkillStatus.FAILURE
    assert ObjectUseSkill().begin(_active(), _state(object_id=88)).status is SkillStatus.FAILURE


def test_object_use_cannot_click_after_the_view_turns_during_hover_confirmation():
    skill, state = ObjectUseSkill(), _active()
    assert skill.begin(state, {**_state(), "orientation": 0.}).commands[0].kind == "HOVER"
    changed = {**_state(), "orientation": .2}
    result = skill.verify(state, changed, 1.2)
    # Never a click on the old view: re-hover the unmoved cursor and demand a
    # fresh identity again (live 21:17: failing here left the cocoon behind).
    assert result.status is SkillStatus.RUNNING
    assert [command.kind for command in result.commands] == ["HOVER"]
    turned = {**_state(), "orientation": .4}
    assert [command.kind for command in skill.verify(state, turned, 1.4).commands] == ["HOVER"]
    final = skill.verify(state, {**_state(), "orientation": .6}, 1.6)
    assert final.status is SkillStatus.FAILURE and not final.commands


def test_object_use_waits_for_a_coasting_character_then_rehovers():
    skill, state = ObjectUseSkill(), _active()
    position = {"x": 39.6, "y": -2200.0, "instance_id": 2175}
    assert skill.begin(state, {**_state(), "player_world_position": position}).commands[0].kind == "HOVER"
    coasting = {**_state(), "movement": {"moving": True},
                "player_world_position": {**position, "y": -2200.9}}
    waiting = skill.verify(state, coasting, 1.3)
    assert waiting.status is SkillStatus.RUNNING and not waiting.commands
    stopped = {**_state(), "movement": {"moving": False},
               "player_world_position": {**position, "y": -2200.9}}
    assert [command.kind for command in skill.verify(state, stopped, 1.6).commands] == ["HOVER"]
    assert skill.verify(state, stopped, 1.8).commands[0].kind == "CLICK"


def test_object_use_too_far_fails_fast_for_an_approach():
    from wowbot.runtime import FailureReason
    skill, state = ObjectUseSkill(), _active()
    skill.begin(state, _state())
    state.phase = "VERIFY"
    assert skill.verify(state, _state(), 1.2).commands[0].kind == "CLICK"
    too_far = {**_state(), "ui_error": "You are too far away.", "ui_error_at": 1.3,
               "ui_error_code": 289}
    result = skill.verify(state, too_far, 1.5)
    assert result.status is SkillStatus.FAILURE and result.reason is FailureReason.OUT_OF_RANGE
    # An old error from before the use is not this use's answer.
    skill2, state2 = ObjectUseSkill(), _active()
    skill2.begin(state2, _state())
    state2.phase = "VERIFY"
    skill2.verify(state2, _state(), 1.2)
    old = {**too_far, "ui_error_at": .5}
    assert skill2.verify(state2, old, 1.5).status is SkillStatus.RUNNING


def test_object_use_waits_for_post_hover_addon_samples_before_right_click():
    skill, state = ObjectUseSkill(), _active()
    before = {**_state(), "monotonic_time": 1.,
              "cursor_sample_time": 1., "mouseover_sample_time": 1.}
    assert skill.begin(state, before).commands[0].kind == "HOVER"
    state.phase = "VERIFY"
    assert not skill.verify(state, before, 1.1).commands
    after = {**before, "monotonic_time": 1.2,
             "cursor_sample_time": 1.2, "mouseover_sample_time": 1.2}
    assert skill.verify(state, after, 1.2).commands[0].kind == "CLICK"


def test_object_use_accepts_fresh_structured_name_when_full_tooltip_is_delayed():
    skill, state = ObjectUseSkill(), _active()
    state.intent.parameters["object_id"] = None
    state.intent.parameters["mouseover_tooltip"] = "Thick Cocoon ~ Who Lurks in the Pit ~ 0/5 rescued"
    before = {**_state(), "mouseover": {"name": "Thick Cocoon",
                                      "quest_related": True, "quest_id": 10},
              "monotonic_time": 1., "cursor_sample_time": 1.,
              "mouseover_sample_time": 1.}
    assert skill.begin(state, before).commands[0].kind == "HOVER"
    after = {**before, "monotonic_time": 1.2,
             "cursor_sample_time": 1.2, "mouseover_sample_time": 1.2}
    assert skill.verify(state, after, 1.2).commands[0].kind == "CLICK"


def test_fresh_addon_cocoon_flag_overrides_only_optical_flow_yaw_drift():
    skill, state = ObjectUseSkill(), _active()
    initial = {**_state(), "orientation": 4.48, "camera_yaw_estimate": 140.,
               "mouseover": {"object_id": 77, "tooltip": "Campfire",
                             "quest_related": True, "quest_id": 10},
               "monotonic_time": 1., "cursor_sample_time": 1.,
               "mouseover_sample_time": 1.}
    assert skill.begin(state, initial).commands[0].kind == "HOVER"
    state.phase = "VERIFY"
    refreshed = {**initial, "camera_yaw_estimate": 256., "monotonic_time": 1.2,
                 "cursor_sample_time": 1.2, "mouseover_sample_time": 1.2}
    assert skill.verify(state, refreshed, 1.2).commands[0].kind == "CLICK"


def test_reused_optical_flow_yaw_does_not_abort_wait_for_fresh_addon_sample():
    skill, state = ObjectUseSkill(), _active()
    before = {**_state(), "orientation": 1.5, "camera_yaw_estimate": -60.,
              "monotonic_time": 1., "cursor_sample_time": 1.,
              "mouseover_sample_time": 1.}
    assert skill.begin(state, before).commands[0].kind == "HOVER"
    repeated = {**before, "camera_yaw_estimate": 12., "monotonic_time": 1.2}
    waiting = skill.verify(state, repeated, 1.2)
    assert waiting.status is SkillStatus.RUNNING and not waiting.commands
    fresh = {**repeated, "monotonic_time": 1.3,
             "cursor_sample_time": 1.3, "mouseover_sample_time": 1.3}
    assert skill.verify(state, fresh, 1.3).commands[0].kind == "CLICK"


def test_interacttarget_fallback_requires_a_matching_soft_gameobject_after_click():
    skill, state = ObjectUseSkill(), _active()
    assert skill.begin(state, _state()).commands[0].kind == "HOVER"
    assert skill.verify(state, _state(), 1.2).commands[0].kind == "CLICK"
    unrelated = {**_state(), "soft_targets": [{"unit_type": "GAMEOBJECT",
                    "guid": "other", "name": "Torch"}]}
    assert not skill.verify(state, unrelated, 3.5).commands
    campfire = {**_state(), "soft_targets": [{"unit_type": "GAMEOBJECT",
                   "guid": "campfire", "object_id": 77, "name": "Campfire"}]}
    fallback = skill.verify(state, campfire, 3.6)
    assert [command.binding for command in fallback.commands] == ["INTERACTTARGET"]
    assert not skill.verify(state, campfire, 3.7).commands


def test_interacttarget_fallback_can_use_fresh_exact_hover_without_soft_gameobject():
    skill, state = ObjectUseSkill(), _active()
    before = {**_state(), "mouseover": {"object_id": 77, "tooltip": "Campfire",
                                      "quest_related": True, "quest_id": 10},
              "monotonic_time": 1., "cursor_sample_time": 1.,
              "mouseover_sample_time": 1.}
    assert skill.begin(state, before).commands[0].kind == "HOVER"
    clicked = {**before, "monotonic_time": 1.2,
               "cursor_sample_time": 1.2, "mouseover_sample_time": 1.2}
    assert skill.verify(state, clicked, 1.2).commands[0].kind == "CLICK"
    stale = {**clicked, "monotonic_time": 3.3}
    assert not skill.verify(state, stale, 3.3).commands
    fresh = {**stale, "mouseover_sample_time": 3.4, "cursor_sample_time": 3.4,
             "monotonic_time": 3.4}
    assert [c.binding for c in skill.verify(state, fresh, 3.4).commands] == ["INTERACTTARGET"]
    assert not skill.verify(state, fresh, 3.5).commands


def test_hover_only_fallback_rejects_moved_cursor_and_wrong_object():
    for change in ({"cursor_position": {"nx": .45, "ny": .6}},
                   {"mouseover": {"object_id": 88, "tooltip": "Torch",
                                  "quest_related": True, "quest_id": 10}}):
        skill, state = ObjectUseSkill(), _active()
        before = {**_state(), "mouseover": {"object_id": 77, "tooltip": "Campfire",
                                          "quest_related": True, "quest_id": 10},
                  "monotonic_time": 1., "cursor_sample_time": 1.,
                  "mouseover_sample_time": 1.}
        assert skill.begin(state, before).commands[0].kind == "HOVER"
        clicked = {**before, "monotonic_time": 1.2,
                   "cursor_sample_time": 1.2, "mouseover_sample_time": 1.2}
        assert skill.verify(state, clicked, 1.2).commands[0].kind == "CLICK"
        wrong = {**clicked, **change, "monotonic_time": 3.4,
                 "mouseover_sample_time": 3.4, "cursor_sample_time": 3.4}
        assert not skill.verify(state, wrong, 3.4).commands


def test_object_use_clicks_again_after_the_client_turned_toward_the_object():
    """Live 21:15 (706863): the right-click turned/stepped the character toward
    the cocoon; nothing opened and the cocoon slid from the click point."""
    skill, state = ObjectUseSkill(), _active()
    base = {**_state(), "orientation": 5.166, "movement": {"moving": False},
            "player_world_position": {"x": 80.6, "y": -2272.6}}
    skill.begin(state, base)
    state.phase = "VERIFY"
    assert skill.verify(state, base, 1.2).commands[0].kind == "CLICK"
    turned = {**base, "orientation": 4.829, "player_world_position": {"x": 80.84, "y": -2274.06},
              "cursor_position": {"nx": .537, "ny": .497},
              "mouseover_sample_time": 2.4, "cursor_sample_time": 2.4}
    again = skill.verify(state, turned, 2.5)
    assert [(c.kind, c.button, c.x) for c in again.commands] == [("CLICK", "RIGHT", .537)]
    # only once
    assert not skill.verify(state, {**turned, "mouseover_sample_time": 3.4}, 3.5).commands or \
        skill.verify(state, {**turned, "mouseover_sample_time": 3.4}, 3.5).commands[0].kind != "CLICK"


def test_object_use_does_not_click_again_without_a_shift():
    skill, state = ObjectUseSkill(), _active()
    skill.begin(state, _state())
    state.phase = "VERIFY"
    skill.verify(state, _state(), 1.2)
    still = {**_state(), "mouseover_sample_time": 2.4}
    result = skill.verify(state, still, 2.5)
    assert not any(command.kind == "CLICK" for command in result.commands)
