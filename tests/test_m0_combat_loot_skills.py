from wowbot.agent.models import Attempt, Prediction, Proposal
from wowbot.runtime import ActiveSkillRuntime, FailureReason, Intent, SkillStatus
from wowbot.skills import CombatSkill, LootSkill
from wowbot.skills.combat import CombatPhase


def active(skill, params, before, *, deadline=8):
    proposal = Proposal.make(skill, "test", params)
    attempt = Attempt("a", proposal, before, "o", 1, deadline, (),
                      Prediction("p", "a", "expected", 1, deadline, "o"))
    runtime = ActiveSkillRuntime()
    runtime.start(intent=Intent(skill, params, params.get("guid")), attempt=attempt,
                  now=1, before_snapshot=before)
    return runtime.state


def combat_state(*, health=100, dead=False, ui_error=None):
    return {"target": {"guid": "mob-1", "attackable": True, "dead": dead, "health": health},
            "actionbar": [{"id": 1, "kind": "spell", "action": "ACTIONBUTTON1",
                           "is_harmful": True, "is_usable": True, "in_range": True,
                           "cooldown_remaining": 0}], "ui_error": ui_error}


def test_combat_requires_exact_live_target_then_emits_bounded_action():
    skill = CombatSkill()
    state = active("COMBAT", {"guid": "mob-1"}, combat_state())
    started = skill.begin(state, combat_state(), 1)
    assert started.status is SkillStatus.RUNNING
    assert started.commands[0].binding == "ACTIONBUTTON1"
    wrong = skill.begin(active("COMBAT", {"guid": "mob-1"}, combat_state()),
                        {"target": {"guid": "other", "attackable": True}}, 1)
    assert wrong.status is SkillStatus.FAILURE


def test_canonical_combat_rotation_uses_fast_state_and_per_attempt_usage_history():
    skill = CombatSkill()
    first = {"id": 1, "kind": "spell", "action": "ACTIONBUTTON1",
             "is_harmful": True, "is_usable": True, "in_range": True,
             "cooldown_remaining": 0}
    second = {"id": 2, "kind": "spell", "action": "ACTIONBUTTON2",
              "is_harmful": True, "is_usable": True, "in_range": True,
              "cooldown_remaining": 0}
    initial = combat_state()
    initial["actionbar"] = [first, second]
    runtime = active("COMBAT", {"guid": "mob-1"}, initial)
    started = skill.begin(runtime, initial, 1.)
    assert started.commands[0].binding == "ACTIONBUTTON1"

    after = {**initial, "actionbar_fast": [[1, False, True, 2.0], [2, True, True, 0]]}
    rotated = skill.verify(runtime, after, 2.)
    assert rotated.commands[0].binding == "ACTIONBUTTON2"
    assert runtime.skill_context["combat"]["ability_uses"] == {1: 1, 2: 1}


def test_combat_does_not_repeat_charge_from_the_same_fast_sample():
    skill = CombatSkill()
    charge = {"id": 100, "name": "Charge", "kind": "spell", "action": "ACTIONBUTTON1",
              "is_harmful": True, "is_usable": True, "in_range": True,
              "cooldown_remaining": 0}
    initial = combat_state()
    initial.update(actionbar=[charge], fast_sequence=77)
    runtime = active("COMBAT", {"guid": "mob-1"}, initial)
    assert skill.begin(runtime, initial, 1.).commands[0].binding == "ACTIONBUTTON1"

    repeated = skill.verify(runtime, initial, 2.)
    assert repeated.status is SkillStatus.RUNNING
    assert repeated.commands == ()
    assert runtime.skill_context["combat"]["ability_uses"] == {100: 1}


def test_combat_starts_auto_attack_when_melee_ability_lacks_rage():
    skill = CombatSkill()
    charge = {"id": 100, "name": "Charge", "kind": "spell", "action": "ACTIONBUTTON1",
              "is_harmful": True, "is_usable": False, "in_range": False,
              "cooldown_remaining": 3}
    slam = {"id": 1464, "name": "Slam", "kind": "spell", "action": "ACTIONBUTTON2",
            "is_harmful": True, "is_usable": False, "lacks_resource": True,
            "in_range": True, "cooldown_remaining": 0}
    initial = combat_state()
    initial.update(actionbar=[charge, slam], fast_sequence=10, monotonic_time=1.)
    initial["target"]["screen_position"] = {"x": .52, "y": .48, "sample_time": 1.}
    runtime = active("COMBAT", {"guid": "mob-1"}, initial)

    started = skill.begin(runtime, initial, 1.)
    assert started.commands == (started.commands[0],)
    assert started.commands[0].kind == "CLICK"
    assert started.commands[0].button == "RIGHT"
    assert started.metadata["auto_attack_fallback"] is True

    # Once rage/usable telemetry changes, the same committed combat skill
    # proceeds to Slam rather than repeatedly right-clicking or retrying Charge.
    with_rage = {**initial, "fast_sequence": 11, "actionbar_fast": [
        [100, False, False, 3.], [1464, True, True, 0.],
    ]}
    rotated = skill.verify(runtime, with_rage, 2.)
    assert rotated.commands[0].binding == "ACTIONBUTTON2"


def test_combat_visual_follow_centres_fresh_track_then_reacquires_last_bearing():
    skill = CombatSkill()
    initial = combat_state()
    runtime = active("COMBAT", {"guid": "mob-1"}, initial)
    skill.begin(runtime, initial, 1.)
    visible = combat_state()
    visible["monotonic_time"] = 2.
    visible["target"]["screen_position"] = {
        "x": .78, "y": .46, "sample_time": 2., "track_id": "world3d:7"}

    follow = skill.verify(runtime, visible, 2.)
    assert follow.metadata["local_navigation_request"]["kind"] == "COMBAT_TRACK_FOLLOW"
    assert runtime.phase == "RECOVER_FACING"

    occluded = combat_state()
    occluded["monotonic_time"] = 2.2
    reacquire = skill.verify(runtime, occluded, 2.2)
    assert reacquire.metadata["local_navigation_request"]["kind"] == "COMBAT_TRACK_REACQUIRE"
    assert reacquire.metadata["local_navigation_request"]["target_screen_x"] == .78


def test_combat_visually_approaches_out_of_range_target_on_each_fresh_track_sample():
    skill = CombatSkill()
    remote = combat_state()
    remote["actionbar"][0]["in_range"] = False
    remote["monotonic_time"] = 1.
    remote["target"]["screen_position"] = {"x": .55, "y": .48, "sample_time": 1.}
    runtime = active("COMBAT", {"guid": "mob-1"}, remote)

    first = skill.begin(runtime, remote, 1.)
    assert first.metadata["local_navigation_request"]["kind"] == "COMBAT_TRACK_APPROACH"
    assert runtime.phase == "APPROACH_TARGET"

    remote["monotonic_time"] = 1.1
    remote["target"]["screen_position"] = {"x": .51, "y": .48, "sample_time": 1.1}
    second = skill.verify(runtime, remote, 1.1)
    assert second.metadata["local_navigation_request"]["kind"] == "COMBAT_TRACK_APPROACH"


def test_combat_fsm_exposes_every_required_m2_state_and_real_phase_transitions():
    assert {phase.value for phase in CombatPhase} == {
        "IDLE", "SELECT_TARGET", "ACQUIRE_TARGET", "APPROACH_TARGET", "ENGAGE",
        "SELECT_ABILITY", "EXECUTE_ABILITY", "VERIFY_ABILITY", "RECOVER_RANGE",
        "RECOVER_FACING", "RECOVER_LOS", "RECOVER_TARGET", "CONFIRM_KILL",
        "POST_COMBAT", "FAILED",
    }
    skill = CombatSkill()
    runtime = active("COMBAT", {"guid": "mob-1"}, combat_state())
    started = skill.begin(runtime, combat_state(), 1.)
    assert started.commands and runtime.phase == CombatPhase.EXECUTE_ABILITY.value
    waiting = skill.verify(runtime, combat_state(), 1.2)
    assert waiting.status is SkillStatus.RUNNING
    assert runtime.phase == CombatPhase.VERIFY_ABILITY.value
    finished = skill.verify(runtime, combat_state(health=0, dead=True), 2.)
    assert finished.status is SkillStatus.SUCCESS
    assert runtime.phase == CombatPhase.POST_COMBAT.value

    wrong = active("COMBAT", {"guid": "mob-1"}, combat_state())
    failed = skill.begin(wrong, {"target": {"guid": "other", "attackable": True}}, 1.)
    assert failed.status is SkillStatus.FAILURE
    assert wrong.phase == CombatPhase.RECOVER_TARGET.value


def test_combat_verifies_death_and_reports_typed_range_failure():
    skill = CombatSkill()
    state = active("COMBAT", {"guid": "mob-1"}, combat_state())
    skill.begin(state, combat_state(), 1)
    dead = skill.verify(state, combat_state(health=0, dead=True), 2)
    assert dead.status is SkillStatus.SUCCESS
    state = active("COMBAT", {"guid": "mob-1"}, combat_state())
    skill.begin(state, combat_state(), 1)
    ranged = skill.verify(state, combat_state(ui_error="You need to be closer."), 2)
    assert ranged.status is SkillStatus.FAILURE
    assert ranged.reason.value == "OUT_OF_RANGE"


def test_combat_keeps_same_active_attempt_for_bounded_los_reposition_then_recast():
    skill = CombatSkill()
    live = combat_state(ui_error="No line of sight")
    live["target"]["screen_position"] = {"x": .72, "y": .48, "sample_time": 2.}
    live["monotonic_time"] = 2.
    state = active("COMBAT", {"guid": "mob-1"}, combat_state())
    skill.begin(state, combat_state(), 1.)

    correction = skill.verify(state, live, 2.)
    assert correction.status is SkillStatus.RUNNING
    request = correction.metadata["local_navigation_request"]
    assert request["reason"] == "LINE_OF_SIGHT"
    assert request["expected_guid"] == "mob-1"
    assert state.phase == "RECOVER_LOS"

    # The next action is a re-cast within the same active COMBAT attempt;
    # it must not immediately interpret the retained old UI error as a new
    # planner-level failure.
    retry = skill.verify(state, live, 2.1)
    assert retry.status is SkillStatus.RUNNING
    assert retry.commands and retry.commands[0].binding == "ACTIONBUTTON1"


def test_los_recovery_has_two_lateral_probes_then_one_world_geometry_replan():
    skill = CombatSkill()
    runtime = active("COMBAT", {"guid": "mob-1"}, combat_state())
    skill.begin(runtime, combat_state(), 1.)
    live = combat_state(ui_error="No line of sight")
    live["target"]["screen_position"] = {"x": .72, "y": .48, "sample_time": 2.}
    live["target"]["world_position"] = {"x": 14., "y": 8., "instance_id": 2175}
    live["player_world_position"] = {"x": 1., "y": 1., "instance_id": 2175}
    live["monotonic_time"] = 2.

    first = skill._local_recovery_request(runtime, live, FailureReason.LINE_OF_SIGHT, 2.)
    second = skill._local_recovery_request(runtime, live, FailureReason.LINE_OF_SIGHT, 2.2)
    third = skill._local_recovery_request(runtime, live, FailureReason.LINE_OF_SIGHT, 2.4)
    terminal = skill._local_recovery_request(runtime, live, FailureReason.LINE_OF_SIGHT, 2.6)

    assert first.metadata["local_navigation_request"]["attempt"] == 0
    assert second.metadata["local_navigation_request"]["attempt"] == 1
    assert third.metadata["los_recovery_phase"] == "LOCAL_REPLAN"
    assert third.metadata["los_reposition_request"]["kind"] == "LOS_REPOSITION"
    assert third.metadata["timeout"] == 2.5
    assert terminal.status is SkillStatus.FAILURE
    assert terminal.metadata["los_recovery_phase"] == "TARGET_UNREACHABLE"


def test_los_local_replan_fails_closed_without_world_geometry():
    skill = CombatSkill()
    runtime = active("COMBAT", {"guid": "mob-1"}, combat_state())
    skill.begin(runtime, combat_state(), 1.)
    live = combat_state(ui_error="No line of sight")
    live["target"]["screen_position"] = {"x": .5, "y": .5, "sample_time": 2.}
    live["monotonic_time"] = 2.
    runtime.skill_context["combat"]["local_recovery_attempts"]["LINE_OF_SIGHT"] = 2

    result = skill._local_recovery_request(
        runtime, live, FailureReason.LINE_OF_SIGHT, 2.)

    assert result.status is SkillStatus.FAILURE
    assert result.reason is FailureReason.LINE_OF_SIGHT
    assert result.metadata["los_recovery_phase"] == "LOCAL_REPLAN_UNAVAILABLE"


def test_combat_uses_one_same_attempt_canonical_world_approach_for_range():
    skill = CombatSkill()
    state = active("COMBAT", {"guid": "mob-1"}, combat_state())
    skill.begin(state, combat_state(), 1.)
    remote = combat_state(ui_error="You need to be closer.")
    remote["target"]["world_position"] = {"x": 14., "y": 8., "instance_id": 2}
    remote["player_world_position"] = {"x": 1., "y": 1., "instance_id": 2}
    request = skill.verify(state, remote, 2.)
    assert request.status is SkillStatus.RUNNING
    assert request.metadata["approach_request"] == {
        "kind": "WORLD_COMBAT", "expected_guid": "mob-1", "stop_distance": 3.5,
    }
    assert state.phase == "RECOVER_RANGE"
    resumed = skill.resume_after_approach(state, remote, 3.)
    assert resumed.status is SkillStatus.RUNNING
    assert resumed.commands and resumed.commands[0].binding == "ACTIONBUTTON1"


def test_range_recovery_derives_desired_range_and_has_finite_escalation_budget():
    skill = CombatSkill()
    initial = combat_state()
    initial["actionbar"][0]["max_range"] = 40
    runtime = active("COMBAT", {"guid": "mob-1"}, initial)
    skill.begin(runtime, initial, 1.)
    remote = combat_state(ui_error="You need to be closer.")
    remote["target"]["world_position"] = {"x": 50., "y": 8., "instance_id": 2}
    remote["target"]["screen_position"] = {"x": .6, "y": .5, "sample_time": 2.}
    remote["player_world_position"] = {"x": 1., "y": 1., "instance_id": 2}
    remote["monotonic_time"] = 2.

    first = skill._local_recovery_request(
        runtime, remote, FailureReason.OUT_OF_RANGE, 2.)
    assert first.metadata["approach_request"]["stop_distance"] == 32.
    runtime.skill_context["combat"]["approach_request"] = None
    second = skill._local_recovery_request(
        runtime, remote, FailureReason.OUT_OF_RANGE, 2.2)
    assert second.metadata["approach_request"]["stop_distance"] == 32.
    runtime.skill_context["combat"]["approach_request"] = None
    local = skill._local_recovery_request(
        runtime, remote, FailureReason.OUT_OF_RANGE, 2.4)
    assert local.metadata["local_navigation_request"]["reason"] == "OUT_OF_RANGE"


def test_range_recovery_timeout_marks_target_unreachable_without_more_input():
    skill = CombatSkill()
    runtime = active("COMBAT", {"guid": "mob-1"}, combat_state())
    skill.begin(runtime, combat_state(), 1.)
    runtime.skill_context["combat"]["range_recovery_started_at"] = 1.
    remote = combat_state()
    result = skill._local_recovery_request(
        runtime, remote, FailureReason.OUT_OF_RANGE, 4.5)
    assert result.status is SkillStatus.FAILURE
    assert result.metadata["target_unreachable"] is True
    assert runtime.phase == "FAILED"


def test_combat_reports_facing_target_loss_player_death_and_timeout_as_typed_results():
    skill = CombatSkill()
    state = active("COMBAT", {"guid": "mob-1"}, combat_state())
    skill.begin(state, combat_state(), 1.)
    facing = combat_state(ui_error="You are facing the wrong way.")
    facing["target"]["screen_position"] = {"x": .72, "y": .5, "sample_time": 2.}
    facing["monotonic_time"] = 2.
    assert skill.verify(state, facing, 2.).metadata["local_navigation_request"]["reason"] == "FACING_WRONG_WAY"

    state = active("COMBAT", {"guid": "mob-1"}, {**combat_state(), "is_in_combat": True})
    skill.begin(state, combat_state(), 1.)
    # A vanished selection while still in combat first waits for the combat
    # drop (live 2026-10-01: the kill keeps combat ~3 s); after the grace it
    # is a typed TARGET_LOST (another attacker keeps us in combat).
    assert skill.verify(state, {"target": {}, "is_in_combat": True}, 2.).status         is SkillStatus.RUNNING
    lost = skill.verify(state, {"target": {}, "is_in_combat": True},
                        2. + CombatSkill.COMBAT_DROP_GRACE_SECONDS)
    assert lost.status is SkillStatus.FAILURE and lost.reason.value == "TARGET_LOST"

    state = active("COMBAT", {"guid": "mob-1"}, combat_state())
    skill.begin(state, combat_state(), 1.)
    dead = skill.verify(state, {"is_dead": True, "target": {"guid": "mob-1"}}, 2.)
    assert dead.status is SkillStatus.FAILURE and dead.reason.value == "PLAYER_DEAD"

    state = active("COMBAT", {"guid": "mob-1"}, combat_state(), deadline=2.)
    skill.begin(state, combat_state(), 1.)
    timed_out = skill.verify(state, combat_state(), 2.)
    assert timed_out.status is SkillStatus.FAILURE and timed_out.reason.value == "COMBAT_TIMEOUT"


def test_facing_recovery_sweeps_toward_an_off_screen_attacker_then_gives_up():
    """Live 2026-10-02: the murloc was behind the character (no screen
    bearing).  Live 2026-10-03 13:57: a blind 3 s turn without retrying the
    attack ended in FACING_FAILED while a goat killed the character.  Now:
    turn ~35 degrees + attack key, repeated while the client still answers
    "not in front", bounded by FACING_SWEEP_STEPS."""
    skill = CombatSkill()
    runtime = active("COMBAT", {"guid": "mob-1"}, combat_state())
    skill.begin(runtime, combat_state(), 1.)
    wrong = combat_state(ui_error="You are facing the wrong way.")
    result = skill.verify(runtime, {**wrong, "ui_error_sequence": 1}, 2.)
    assert result.status is SkillStatus.RUNNING and runtime.phase == "RECOVER_FACING"
    assert [(c.binding, c.duration) for c in result.commands][0] == (
        "TURNLEFT", CombatSkill.FACING_SWEEP_TURN_SECONDS)
    now, steps = 2., 1
    for sequence in range(2, 40):
        now += .5
        result = skill.verify(runtime, {**wrong, "ui_error_sequence": sequence}, now)
        if result.status is SkillStatus.FAILURE:
            break
        steps += bool(result.commands)
    assert result.reason.value == "FACING_FAILED" and steps == CombatSkill.FACING_SWEEP_STEPS


def test_facing_sweep_ends_when_the_client_stops_complaining():
    skill = CombatSkill()
    runtime = active("COMBAT", {"guid": "mob-1"}, combat_state())
    skill.begin(runtime, combat_state(), 1.)
    wrong = {**combat_state(ui_error="You are facing the wrong way."), "ui_error_sequence": 1}
    skill.verify(runtime, wrong, 2.)
    assert skill.verify(runtime, wrong, 2.5).commands == ()          # same error: wait
    skill.verify(runtime, wrong, 3.2)                                  # quiet > 1.1 s
    assert "facing_sweep" not in runtime.skill_context["combat"]


def test_facing_recovery_turns_toward_the_last_seen_side():
    skill = CombatSkill()
    runtime = active("COMBAT", {"guid": "mob-1"}, combat_state())
    skill.begin(runtime, combat_state(), 1.)
    runtime.skill_context["combat"]["visual_follow"] = {"last_seen_x": .93}
    result = skill.verify(runtime, combat_state(ui_error="You are facing the wrong way."), 2.)
    assert result.commands[0].binding == "TURNRIGHT"


def test_loot_accepts_confirmed_corpse_anchor_and_requires_evidence():
    before = {"target": {}, "inventory": {"items": []}, "events": []}
    skill = LootSkill()
    state = active("LOOT", {"guid": "corpse-1", "corpse_anchor": True, "x": .4, "y": .5}, before)
    started = skill.begin(state, before)
    # Hover the corpse first (live 2026-10-03), right-click once the addon names it.
    assert started.status is SkillStatus.RUNNING and started.commands[0].kind == "HOVER"
    hovered = {**before, "mouseover": {"guid": "corpse-1", "is_dead": True}, "mouseover_sample_time": 1.}
    click = skill.verify(state, hovered, 1.)
    assert click.commands[0].kind == "CLICK_CURRENT_CURSOR" and click.commands[0].button == "RIGHT"
    assert skill.verify(state, before, 2).status is SkillStatus.RUNNING
    after = {**before, "events": [{"event_type": "LOOT_RECEIVED", "payload": {"source_guid": "corpse-1"}}]}
    assert skill.verify(state, after, 2).status is SkillStatus.SUCCESS


def test_loot_rejects_living_or_unmatched_target():
    skill = LootSkill()
    before = {"target": {"guid": "corpse-1", "dead": False}}
    state = active("LOOT", {"guid": "corpse-1"}, before)
    result = skill.begin(state, before)
    assert result.status is SkillStatus.FAILURE
    assert result.reason.value == "NOT_LOOTABLE"


def test_loot_window_is_not_completion_and_declared_item_must_be_received():
    before = {"target": {"guid": "corpse-1", "dead": True}, "inventory": {"items": []}}
    skill = LootSkill()
    state = active("LOOT", {"guid": "corpse-1", "expected_item_id": 99}, before)
    skill.begin(state, before)
    assert skill.verify(state, {**before, "loot_ui": {"open": True}}, 2.).status is SkillStatus.RUNNING
    wrong = {**before, "inventory": {"items": [{"item_id": 4, "count": 1}]},
             "events": [{"event_type": "LOOT_RECEIVED", "payload": {"source_guid": "corpse-1", "item_id": 4}}]}
    assert skill.verify(state, wrong, 3.).status is SkillStatus.RUNNING
    right = {**before, "inventory": {"items": [{"item_id": 99, "count": 1}]},
             "events": [{"event_type": "LOOT_RECEIVED", "payload": {"source_guid": "corpse-1", "item_id": 99}}]}
    assert skill.verify(state, right, 4.).status is SkillStatus.SUCCESS


def test_loot_fuses_corpse_state_evidence_but_never_treats_click_as_success():
    before = {"target": {"guid": "corpse-1", "dead": True, "lootable": True,
                         "interaction_state": "READY"},
              "inventory": {"items": []}}
    skill = LootSkill()
    state = active("LOOT", {"guid": "corpse-1"}, before)
    started = skill.begin(state, before)
    assert started.commands and skill.verify(state, before, 1.1).status is SkillStatus.RUNNING

    looted = {**before, "target": {**before["target"], "lootable": False}}
    result = skill.verify(state, looted, 2.)
    assert result.status is SkillStatus.SUCCESS
    assert "corpse_lootable_changed" in result.evidence


def test_loot_ui_plus_corpse_interaction_state_can_confirm_without_inventory_delta():
    before = {"target": {"guid": "corpse-1", "dead": True,
                         "interaction_state": "READY"},
              "loot_ui": {"open": False}, "inventory": {"items": []}}
    skill = LootSkill()
    state = active("LOOT", {"guid": "corpse-1"}, before)
    skill.begin(state, before)
    after = {**before,
             "target": {**before["target"], "interaction_state": "LOOTED"},
             "loot_ui": {"open": True}}
    result = skill.verify(state, after, 2.)
    assert result.status is SkillStatus.SUCCESS
    assert set(result.evidence) == {"loot_ui_open", "corpse_interaction_changed"}


def test_loot_reports_expected_item_not_received_at_attempt_deadline():
    before = {"target": {"guid": "corpse-1", "dead": True}, "inventory": {"items": []}}
    skill = LootSkill()
    state = active("LOOT", {"guid": "corpse-1", "expected_item_id": 99}, before, deadline=2.)
    skill.begin(state, before)
    result = skill.verify(state, before, 2.)
    assert result.status is SkillStatus.FAILURE
    assert result.reason.value == "EXPECTED_ITEM_NOT_RECEIVED"


def test_loot_accepts_quest_objective_delta_when_no_explicit_item_id_is_required():
    before = {"target": {"guid": "corpse-1", "dead": True}, "inventory": {"items": []},
              "active_quests": [{"quest_id": 7, "objectives": [{"objective_id": 1, "current": 2,
                                                                      "required": 3, "is_complete": False}]}]}
    skill = LootSkill()
    state = active("LOOT", {"guid": "corpse-1"}, before)
    skill.begin(state, before)
    after = {**before, "active_quests": [{"quest_id": 7, "objectives": [{"objective_id": 1, "current": 3,
                                                                              "required": 3, "is_complete": True}]}]}
    result = skill.verify(state, after, 2.)
    assert result.status is SkillStatus.SUCCESS
    assert result.evidence == ("quest_objective_delta",)


def test_loot_requests_one_same_attempt_world_corpse_approach_after_range_error():
    before = {"target": {"guid": "corpse-1", "dead": True}, "inventory": {"items": []}}
    skill = LootSkill()
    state = active("LOOT", {"guid": "corpse-1"}, before)
    skill.begin(state, before)
    remote = {
        "target": {"guid": "corpse-1", "dead": True,
                   "world_position": {"x": 14., "y": 8., "instance_id": 2}},
        "player_world_position": {"x": 1., "y": 1., "instance_id": 2},
        "ui_error": "Need to be closer to loot that.",
    }
    approaching = skill.verify(state, remote, 2.)
    assert approaching.status is SkillStatus.RUNNING
    assert approaching.metadata["approach_request"] == {
        "kind": "WORLD_CORPSE", "corpse_guid": "corpse-1", "stop_distance": 3.5,
    }
    resumed = skill.resume_after_approach(state, remote)
    assert resumed.status is SkillStatus.RUNNING
    assert resumed.commands[0].binding == "INTERACTTARGET"


def test_combat_follow_turns_toward_a_target_that_left_the_screen_edge():
    """User 2026-10-01: never fight with the back to the selected target."""
    from wowbot.skills.combat_visual_follow import CombatVisualFollowPolicy

    policy = CombatVisualFollowPolicy()
    target = {"guid": "mob-1", "attackable": True, "dead": False,
              "screen_position": {"x": .93, "y": .5, "sample_time": 1.}}
    context = {"expected_guid": "mob-1"}
    decision = policy.decide(context, {"target": target}, 2.)       # 1 s old, right edge
    assert decision is not None and decision.kind == "COMBAT_TRACK_REACQUIRE"
    assert context["visual_follow"]["reacquire_direction"] == "TURNRIGHT"
    centred = {**target, "screen_position": {"x": .52, "y": .5, "sample_time": 1.}}
    assert CombatVisualFollowPolicy().decide({"expected_guid": "mob-1"},
                                             {"target": centred}, 2.) is None


def test_combat_follow_turns_left_toward_a_target_that_left_the_left_edge():
    from wowbot.skills.combat_visual_follow import CombatVisualFollowPolicy

    target = {"guid": "mob-1", "attackable": True, "dead": False,
              "screen_position": {"x": .06, "y": .5, "sample_time": 1.}}
    context = {"expected_guid": "mob-1"}
    decision = CombatVisualFollowPolicy().decide(context, {"target": target}, 2.)
    assert decision is not None and context["visual_follow"]["reacquire_direction"] == "TURNLEFT"


def test_corpse_view_clicks_the_live_box_bottom_and_decides_approach():
    """User 2026-10-01 ("csináld meg a lootot"): LOOT used the stale last
    mouseover point.  Now the corpse's live box is used, the click goes to its
    lower part (the unit lies at its feet), and a corpse not beside the avatar
    is approached first."""
    from wowbot.agent.combat_planning import CombatPlanningPolicy

    def box(track_id, left, top, right, bottom, **extra):
        return {"source": "WORLD3D", "track_id": track_id, "confidence": .7,
                "bbox": {"left": left, "top": top, "right": right, "bottom": bottom},
                "bbox_width_fraction": (right-left)/843, "bbox_height_fraction": (bottom-top)/475,
                "x": (left+right)/2/843, "y": 1-(top+bottom)/2/475, **extra}

    avatar = box("WORLD3D:5", 395, 225, 448, 370, appearance={"screen_anchored": True})
    corpse = {"guid": "Creature-1", "track_id": "WORLD3D:9", "x": .1, "y": .9}
    near_state = {"visual_candidates": [avatar, box("WORLD3D:9", 450, 330, 520, 368)]}
    live, point, near = CombatPlanningPolicy._corpse_view(near_state, corpse)
    assert live is not None and near is True
    assert abs(point[0] - (485/843)) < .01
    assert 1-point[1] > 340/475                       # lower part of the box
    far_state = {"visual_candidates": [avatar, box("WORLD3D:9", 600, 200, 625, 230)]}
    _, _, far = CombatPlanningPolicy._corpse_view(far_state, corpse)
    assert far is False


def test_leaving_combat_after_our_casts_with_the_selection_gone_ends_the_fight():
    """User 2026-10-01: the kill is over when the character is out of combat.
    Live: Retail cleared the selection and the player left combat in the same
    sample, but COMBAT ran on for 17-32 s (no target health/dead flag)."""
    skill = CombatSkill()
    spell = {"id": 1464, "name": "Slam", "kind": "spell", "action": "ACTIONBUTTON2",
             "is_harmful": True, "is_usable": True, "in_range": True, "cooldown_remaining": 0}
    initial = combat_state()
    initial.update(actionbar=[spell], fast_sequence=10, monotonic_time=1., is_in_combat=True)
    runtime = active("COMBAT", {"guid": "mob-1"}, initial)
    started = skill.begin(runtime, initial, 1.)
    assert started.commands and started.commands[0].binding == "ACTIONBUTTON2"
    fighting = {**initial, "fast_sequence": 11, "monotonic_time": 2.}
    assert skill.verify(runtime, fighting, 2.).status is not SkillStatus.SUCCESS
    over = {**initial, "fast_sequence": 12, "monotonic_time": 3., "target": None,
            "is_in_combat": False}
    result = skill.verify(runtime, over, 3.)
    assert result.status is SkillStatus.SUCCESS
    assert "player_left_combat_after_engagement" in result.evidence


def test_combat_waits_for_the_combat_drop_after_the_target_vanishes():
    """Live 2026-10-01 18:40: the player stayed in combat ~3 s after the kill;
    with no selection every action read out_of_range and COMBAT failed, so the
    kill was never marked and the corpse was never looted."""
    skill = CombatSkill()
    spell = {"id": 1464, "name": "Slam", "kind": "spell", "action": "ACTIONBUTTON2",
             "is_harmful": True, "is_usable": True, "in_range": True, "cooldown_remaining": 0}
    initial = combat_state()
    initial.update(actionbar=[spell], fast_sequence=10, monotonic_time=1., is_in_combat=True,
                   health=300)
    runtime = active("COMBAT", {"guid": "mob-1"}, initial)
    skill.begin(runtime, initial, 1.)
    no_target_bar = [{**spell, "in_range": False}]
    lingering = {**initial, "fast_sequence": 11, "monotonic_time": 2., "target": None,
                 "actionbar": no_target_bar}
    waiting = skill.verify(runtime, lingering, 2.)
    assert waiting.status is SkillStatus.RUNNING and not waiting.commands
    still = {**lingering, "fast_sequence": 12, "monotonic_time": 4.}
    assert skill.verify(runtime, still, 4.).status is SkillStatus.RUNNING
    dropped = {**lingering, "fast_sequence": 13, "monotonic_time": 4.5, "is_in_combat": False}
    assert skill.verify(runtime, dropped, 4.5).status is SkillStatus.SUCCESS


def test_combat_leaves_at_once_when_another_attacker_hits_after_the_kill():
    skill = CombatSkill()
    spell = {"id": 1464, "name": "Slam", "kind": "spell", "action": "ACTIONBUTTON2",
             "is_harmful": True, "is_usable": True, "in_range": True, "cooldown_remaining": 0}
    initial = combat_state()
    initial.update(actionbar=[spell], fast_sequence=10, monotonic_time=1., is_in_combat=True,
                   health=300)
    runtime = active("COMBAT", {"guid": "mob-1"}, initial)
    skill.begin(runtime, initial, 1.)
    gone = {**initial, "fast_sequence": 11, "monotonic_time": 2., "target": None,
            "actionbar": [{**spell, "in_range": False}]}
    assert skill.verify(runtime, gone, 2.).status is SkillStatus.RUNNING
    hit = {**gone, "fast_sequence": 12, "monotonic_time": 2.5, "health": 280}
    assert skill.verify(runtime, hit, 2.5).status is SkillStatus.FAILURE


def test_an_already_answered_facing_error_does_not_fail_combat():
    skill = CombatSkill()
    runtime = active("COMBAT", {"guid": "mob-1"}, combat_state(), deadline=100)
    skill.begin(runtime, combat_state(), 1.)
    wrong = {**combat_state(ui_error="You are facing the wrong way."), "ui_error_sequence": 1}
    skill.verify(runtime, wrong, 2.)
    for now in (2.5, 3.2, 3.6, 4.):
        assert skill.verify(runtime, wrong, now).status is SkillStatus.RUNNING


def test_kill_credit_during_loot_is_not_loot_evidence():
    """Issue #100: a KILL count 0/5 -> 1/5 (late paged snapshot) verified a
    LOOT with no loot event, inventory, UI or corpse change."""
    from wowbot.verification.loot import LootVerifier
    def quests(kill, collect=0):
        return [{"quest_id": 7, "objectives": [
            {"objective_id": "k", "type": "KILL", "current": kill, "required": 5},
            {"objective_id": "c", "raw_type": "item", "current": collect, "required": 3}]},
            {"quest_id": 8, "objectives": [{"objective_id": "x", "current": collect, "required": 3}]}]
    verifier = LootVerifier()
    before = {"inventory": {"items": []}, "active_quests": quests(0)}
    kill_only = {**before, "active_quests": quests(1)}
    assert not verifier.evaluate(before, kill_only, corpse_guid="corpse-1").success
    collected = {**before, "active_quests": quests(0, collect=1)}
    assert verifier.evaluate(before, collected, corpse_guid="corpse-1").success
    # Bound to the LOOT proposal's quests when it names them.
    only_other = {**before, "active_quests": [quests(0)[0], {"quest_id": 8, "objectives": [
        {"objective_id": "x", "current": 1, "required": 3}]}]}
    assert not verifier.evaluate(before, only_other, corpse_guid="corpse-1", quest_ids=(7,)).success
