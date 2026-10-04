"""Slam was never used in combat (user 2026-10-03).

Live 2026-10-02: ACTIONBUTTON3 (Shield Slam) was pressed ~100 times and
ACTIONBUTTON2 (Slam) once.  In combat Retail 12 exports the spell cooldown as
a secret value -- the addon's FAST action bar then reads 0 ("ready") -- and
IsUsableAction ignores cooldowns, so Shield Slam (priority 40) always beat
Slam (20).  Own successful casts are tracked locally.
"""
from wowbot.skills.ability_rules import AbilityRuleEngine

BAR = [
    {"action": "ACTIONBUTTON2", "kind": "spell", "id": 1464, "name": "Slam",
     "is_harmful": True, "is_usable": True, "in_range": True, "cooldown_remaining": 0},
    {"action": "ACTIONBUTTON3", "kind": "spell", "id": 23922, "name": "Shield Slam",
     "is_harmful": True, "is_usable": True, "in_range": True, "cooldown_remaining": 0},
]


def _state(**extra):
    return {"actionbar": [dict(row) for row in BAR],
            "target": {"guid": "Creature-0-1-2-3-4-5", "attackable": True}, **extra}


def test_shield_slam_cooling_down_after_its_cast_lets_slam_through():
    engine = AbilityRuleEngine()
    assert engine.choose(_state(), now=10.)["name"] == "Shield Slam"
    # The addon's fast lane reports our own successful Shield Slam cast.
    cast = _state(combat_last_spell_id=23922, combat_last_cast_at=5000.25)
    engine.observe_casts(cast, 10.5)
    assert engine.choose(cast, now=11.)["name"] == "Slam"
    assert engine.choose(cast, now=18.)["name"] == "Slam"
    # The same hint seen again is not a new cast.
    engine.observe_casts(cast, 18.)
    assert engine.choose(cast, now=19.6)["name"] == "Shield Slam"   # 9 s later


def test_slow_lane_cast_event_is_dated_back_by_its_lateness():
    engine = AbilityRuleEngine()
    old = {"sequence": 10, "event_type": "SPELLCAST_SUCCEEDED", "timestamp": 1000,
           "payload": {"spell_id": 23922}}
    engine.observe_casts(_state(events=[old], timestamp=1001), 50.)   # baseline only
    assert engine.choose(_state(), now=50.)["name"] == "Shield Slam"
    new = {"sequence": 11, "event_type": "SPELLCAST_SUCCEEDED", "timestamp": 1004,
           "payload": {"spell_id": 23922}}
    engine.observe_casts(_state(events=[old, new], timestamp=1007), 60.)   # 3 s late
    assert engine.choose(_state(), now=62.)["name"] == "Slam"
    assert engine.choose(_state(), now=66.2)["name"] == "Shield Slam"   # cast at 57 + 9 s


def test_not_ready_answer_blocks_the_ability_briefly():
    engine = AbilityRuleEngine()
    engine.note_not_ready(23922, 30.)
    assert engine.choose(_state(), now=30.5)["name"] == "Slam"
    assert engine.choose(_state(), now=32.5)["name"] == "Shield Slam"


def test_without_now_the_choice_is_unchanged():
    engine = AbilityRuleEngine()
    engine.note_not_ready(23922, 30.)
    assert engine.choose(_state())["name"] == "Shield Slam"


def test_combat_follow_turns_are_valid_movement_leases():
    """Live 2026-10-02: 11 COMBAT/DEFEND attempts ended in executor_failure
    ("Érvénytelen movement lease"): a small follow turn was .035 s while the
    executor accepts .04-.35 s only."""
    from wowbot.navigation.service import NavigationService
    service = NavigationService()
    for x in (.58, .62, .70, .30, .95):
        request = {"expected_guid": "mob-1", "reason": "COMBAT_TRACK_FOLLOW",
                   "target_screen_x": x, "target_screen_y": .5}
        for command in service.local_combat_reposition({"target": {"guid": "mob-1"}}, request):
            assert .04 <= command.duration <= .35, (x, command)


def test_a_target_lost_straight_ahead_is_not_searched_by_turning_away():
    """Live 2026-10-03: a Coastal Goat last seen at x=.49 lost its box and the
    character turned left away from it for seconds (COMBAT then out_of_range)."""
    from wowbot.skills.combat_visual_follow import CombatVisualFollowPolicy
    policy = CombatVisualFollowPolicy()
    context = {"expected_guid": "goat"}
    seen = {"guid": "goat", "attackable": True, "dead": False,
            "screen_position": {"x": .49, "y": .5, "sample_time": 1.}}
    policy.decide(context, {"target": seen}, 1.)
    lost = {"guid": "goat", "attackable": True, "dead": False}
    assert policy.decide(context, {"target": lost}, 1.5) is None


def test_target_hovers_the_live_box_and_clicks_only_when_the_guid_is_confirmed():
    """Live 2026-10-03: 7 TARGET clicks landed while the character still turned
    after a SEEK step; the goat had slid away (target_not_found)."""
    from types import SimpleNamespace
    from wowbot.runtime import ActiveSkillState, Intent, SkillStatus
    from wowbot.skills.target import TargetSkill
    goat = "Creature-0-3102-2175-11354-161130-0000408640"
    intent = SimpleNamespace(skill="TARGET", target_ref=goat, parameters={
        "guid": goat, "click_current_cursor": True, "hover_x": .55, "hover_y": .6,
        "track_id": "WORLD3D:9"})
    state = SimpleNamespace(intent=intent, skill_context={}, phase=None, started_at=10.,
                            attempt=SimpleNamespace(deadline=13.))
    skill = TargetSkill()
    first = skill.begin(state)
    assert first.commands[0].kind == "HOVER" and (first.commands[0].x, first.commands[0].y) == (.55, .6)
    state.phase = "VERIFY"   # the live runtime rewrites the phase every tick
    # The goat moved: its box is now further right; re-hover there after .45 s.
    moved = {"mouseover": {}, "visual_candidates": [
        {"source": "WORLD3D", "track_id": "WORLD3D:9", "x": .62, "y": .58}]}
    assert skill.verify(state, moved, 10.2).commands == ()
    again = skill.verify(state, moved, 10.6)
    assert again.commands[0].kind == "HOVER" and again.commands[0].x == .62
    confirmed = {**moved, "mouseover": {"guid": goat}}
    click = skill.verify(state, confirmed, 10.8)
    assert click.commands[0].kind == "CLICK_CURRENT_CURSOR"
    assert skill.verify(state, {"target": {"guid": goat}}, 11.).status is SkillStatus.SUCCESS


def test_loot_hover_shows_an_empty_corpse_and_does_not_click():
    from types import SimpleNamespace
    from wowbot.runtime import FailureReason, SkillStatus
    from wowbot.skills.loot import LootSkill
    goat = "Creature-0-3102-2175-11354-161130-0000408640"
    intent = SimpleNamespace(target_ref=goat, parameters={
        "guid": goat, "corpse_anchor": True, "x": .54, "y": .49})
    state = SimpleNamespace(intent=intent, skill_context={}, phase=None, started_at=5.,
                            attempt=SimpleNamespace(deadline=11.), before_snapshot={},
                            local_retry_count=0, failure_history=[])
    skill = LootSkill()
    assert skill.begin(state, {}).commands[0].kind == "HOVER"
    state.phase = "VERIFY"   # the live runtime rewrites the phase every tick
    empty = skill.verify(state, {"mouseover": {"guid": goat, "is_dead": True, "lootable": False}}, 5.3)
    assert empty.status is SkillStatus.FAILURE and empty.reason is FailureReason.NOT_LOOTABLE


def test_interact_approach_pointer_moves_use_the_discrete_lane():
    """Live 2026-10-03 06:30: INTERACT failed with "Érvénytelen movement lease":
    the approach's POINTER command was sent on the movement lane."""
    from types import SimpleNamespace
    from wowbot.agent.models import Command
    from wowbot.runtime import SkillResult, SkillStatus
    from wowbot.skills.interaction_runtime import InteractionRuntimeRunner
    approach = SimpleNamespace(
        observe=lambda *a: SkillResult(SkillStatus.RUNNING, commands=(Command("POINTER", x=.5, y=.5, duration=.02),)),
        snapshot=lambda *a: {})
    runner = InteractionRuntimeRunner.__new__(InteractionRuntimeRunner)
    runner.visual_approach_skill = approach
    step = runner.step_visual(SimpleNamespace(), {}, "obs", 1.)
    assert step.movement_lane is False
