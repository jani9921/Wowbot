from wowbot.skills.ability_rules import AbilityRuleEngine, AbilityTag


def _state(*actions, **overrides):
    state = {
        "target": {"guid": "Creature-0-0-0-0-12-1", "attackable": True},
        "actionbar": list(actions),
        "combat_spell_ids": [],
        "health": 100,
        "max_health": 100,
        "power": 100,
    }
    state.update(overrides)
    return state


def test_rule_engine_explains_rejection_and_returns_a_structured_definition():
    engine = AbilityRuleEngine()
    state = _state(
        {"id": 7, "name": "Strike", "kind": "spell", "action": "ACTIONBUTTON1",
             "is_harmful": True, "is_usable": True, "in_range": False,
             "combat_priority": 8, "max_range": 5, "tags": ["OFFENSIVE"], "cooldown_remaining": 0},
    )

    candidate = engine.evaluate(state)[0]

    assert not candidate.eligible
    assert candidate.rejection_reasons == ("out_of_range",)
    assert candidate.definition.ability_id == 7
    assert candidate.definition.max_range == 5


def test_rule_engine_uses_priority_and_never_selects_without_required_target():
    engine = AbilityRuleEngine()
    low = {"id": 1, "kind": "spell", "action": "ACTIONBUTTON1", "is_harmful": True,
           "is_usable": True, "in_range": True, "combat_priority": 2, "cooldown_remaining": 0}
    high = {"id": 2, "kind": "spell", "action": "ACTIONBUTTON2", "is_harmful": True,
            "is_usable": True, "in_range": True, "combat_priority": 9, "cooldown_remaining": 0}

    assert engine.choose(_state(low, high))["id"] == 2
    missing_target = _state(low, high, target={})
    assert engine.choose(missing_target) is None
    assert all("target_missing" in item.rejection_reasons for item in engine.evaluate(missing_target))


def test_rule_engine_prioritizes_a_configured_defensive_spell_at_low_health():
    engine = AbilityRuleEngine()
    strike = {"id": 1, "kind": "spell", "action": "ACTIONBUTTON1", "is_harmful": True,
              "is_usable": True, "in_range": True, "combat_priority": 99, "cooldown_remaining": 0}
    shield = {"id": 2, "kind": "spell", "action": "ACTIONBUTTON2", "is_harmful": False,
              "is_usable": True, "in_range": True, "combat_priority": 1,
              "requires_target": False, "cooldown_remaining": 0}
    state = _state(strike, shield, health=20, max_health=100, defensive_spell_ids=[2])

    assert engine.choose(state)["id"] == 2


def test_rule_engine_fails_closed_when_cooldown_readiness_is_missing():
    engine = AbilityRuleEngine()
    state = _state({"id": 1, "kind": "spell", "action": "ACTIONBUTTON1",
                    "is_harmful": True, "is_usable": True, "in_range": True})

    candidate = engine.evaluate(state)[0]
    assert not candidate.eligible
    assert "cooldown_unknown" in candidate.rejection_reasons
    assert engine.choose(state) is None


def test_fast_actionbar_overrides_stale_range_and_cooldown_without_losing_binding_identity():
    engine = AbilityRuleEngine()
    stale = {"id": 1, "kind": "spell", "action": "ACTIONBUTTON1",
             "is_harmful": True, "is_usable": False, "in_range": True,
             "cooldown_remaining": 9}
    state = _state(stale, actionbar_fast=[[1, True, False, 0]])

    candidate = engine.evaluate(state)[0]

    assert not candidate.eligible
    assert candidate.rejection_reasons == ("out_of_range",)
    overlaid = engine.actionbar(state)[0]
    assert overlaid["action"] == "ACTIONBUTTON1"
    assert overlaid["is_usable"] is True
    assert overlaid["in_range"] is False
    assert overlaid["cooldown_remaining"] == 0


def test_ability_definition_and_runtime_state_cover_the_m2_contract():
    action = {
        "id": 42, "name": "Shield Bash", "kind": "spell",
        "action": "ACTIONBUTTON3", "is_harmful": True, "is_usable": True,
        "in_range": True, "facing": True, "has_los": True,
        "min_range": 0, "max_range": 5, "cast_time_ms": 0,
        "channel_time_ms": 0, "gcd_ms": 1500, "cooldown_ms": 12000,
        "cooldown_remaining": 0, "resource_cost": 20,
        "requires_target": True, "requires_facing": True, "requires_los": True,
        "tags": ["OFFENSIVE", "INTERRUPT"],
        "last_attempt_at": 9.5, "last_result": "CAST_SUCCEEDED",
    }
    candidate = AbilityRuleEngine().evaluate(_state(action, power=30))[0]
    definition, runtime = candidate.definition, candidate.runtime_state
    assert definition.ability_id == 42 and definition.name == "Shield Bash"
    assert definition.binding == "ACTIONBUTTON3"
    assert (definition.min_range, definition.max_range) == (0., 5.)
    assert (definition.cast_time_ms, definition.channel_time_ms,
            definition.gcd_ms, definition.cooldown_ms) == (0, 0, 1500, 12000)
    assert definition.resource_cost == 20
    assert definition.tags == (AbilityTag.OFFENSIVE.value, AbilityTag.INTERRUPT.value)
    assert runtime.ready_belief == 1.
    assert runtime.cooldown_remaining_estimate == 0.
    assert runtime.resource_available_belief == 1.
    assert runtime.in_range_belief == runtime.facing_belief == runtime.los_belief == 1.
    assert runtime.usable_confidence == 1.
    assert runtime.last_attempt_at == 9.5 and runtime.last_result == "CAST_SUCCEEDED"


def test_runtime_beliefs_fail_closed_for_unknown_ready_and_low_resource():
    action = {"id": 7, "kind": "spell", "action": "ACTIONBUTTON1",
              "is_harmful": True, "is_usable": True, "resource_cost": 50,
              "in_range": True, "facing": True, "has_los": True}
    candidate = AbilityRuleEngine().evaluate(_state(action, power=10))[0]
    assert candidate.runtime_state.ready_belief == 0.
    assert candidate.runtime_state.resource_available_belief == 0.
    assert candidate.runtime_state.usable_confidence == 0.


def test_rule_contract_explains_precondition_and_forbidden_rejections():
    action = {
        "id": 8, "kind": "spell", "action": "ACTIONBUTTON2",
        "is_harmful": True, "is_usable": True, "in_range": True,
        "cooldown_remaining": 0, "rule_id": "interrupt-caster",
        "combat_priority": 30,
        "preconditions": ["state:target_casting"],
        "forbidden_conditions": [{"field": "player_silenced", "equals": True}],
        "expected_postconditions": ["target_cast_interrupted"],
    }
    state = _state(action, target_casting=False, player_silenced=True)
    candidate = AbilityRuleEngine().evaluate(state)[0]
    assert candidate.rule_id == "interrupt-caster"
    assert candidate.rule.ability_id == 8
    assert candidate.rule.priority == 30
    assert candidate.rule.expected_postconditions == ("target_cast_interrupted",)
    assert candidate.eligible is False
    assert candidate.rejection_reasons[-2:] == (
        "precondition_failed:state:target_casting",
        "forbidden_condition:player_silenced",
    )


def test_rule_engine_debug_projection_is_bounded_to_top_five_candidates():
    from wowbot.agent.combat_controller import CombatController

    actions = [{"id": index, "kind": "spell", "action": f"ACTIONBUTTON{index}",
                "is_harmful": True, "is_usable": True, "in_range": True,
                "cooldown_remaining": 0, "combat_priority": index,
                "rule_id": f"rule-{index}"}
               for index in range(1, 8)]
    controller = CombatController()
    combat_state = _state(*actions)
    controller.observe(combat_state, 1.)
    controller.choose_action(combat_state)
    debug = controller.snapshot()["ability_candidates"]
    assert len(debug) == 5
    assert all(item["rule_id"].startswith("rule-") for item in debug)
    assert all("rejection_reasons" in item for item in debug)


def test_warrior_catalog_prefers_charge_at_range_and_melee_rotation_when_close():
    engine = AbilityRuleEngine()
    charge = {"id": 100, "name": "Charge", "kind": "spell", "action": "ACTIONBUTTON1",
              "is_harmful": True, "is_usable": True, "in_range": True,
              "cooldown_remaining": 0}
    shield_slam = {"id": 23922, "name": "Shield Slam", "kind": "spell",
                   "action": "ACTIONBUTTON2", "is_harmful": True,
                   "is_usable": True, "in_range": False, "cooldown_remaining": 0}
    slam = {"id": 1464, "name": "Slam", "kind": "spell", "action": "ACTIONBUTTON3",
            "is_harmful": True, "is_usable": True, "in_range": False,
            "cooldown_remaining": 0}

    assert engine.choose(_state(charge, shield_slam, slam))["id"] == 100
    close = _state(charge, shield_slam, slam, actionbar_fast=[
        [100, False, False, 3.0], [23922, True, True, 0], [1464, True, True, 0],
    ])
    assert engine.choose(close)["id"] == 23922
    definition = engine.definition(engine.actionbar(close)[0])
    assert (definition.min_range, definition.max_range) == (8., 25.)


def test_usage_history_breaks_equal_priority_ties_without_overriding_readiness():
    engine = AbilityRuleEngine()
    first = {"id": 1, "kind": "spell", "action": "ACTIONBUTTON1",
             "is_harmful": True, "is_usable": True, "in_range": True,
             "cooldown_remaining": 0}
    second = {"id": 2, "kind": "spell", "action": "ACTIONBUTTON2",
              "is_harmful": True, "is_usable": True, "in_range": True,
              "cooldown_remaining": 0}
    state = _state(first, second)
    assert engine.choose(state, uses={})["id"] == 1
    assert engine.choose(state, uses={1: 1})["id"] == 2


def test_charge_is_an_opener_and_melee_range_switches_to_shield_slam():
    engine = AbilityRuleEngine()
    charge = {"id": 100, "name": "Charge", "kind": "spell", "action": "ACTIONBUTTON1",
              "is_harmful": True, "is_usable": True, "in_range": True,
              "cooldown_remaining": 0}
    shield_slam = {"id": 23922, "name": "Shield Slam", "kind": "spell",
                   "action": "ACTIONBUTTON2", "is_harmful": True,
                   "is_usable": True, "in_range": True, "cooldown_remaining": 0}

    chosen = engine.choose(_state(charge, shield_slam), uses={100: 1})
    assert chosen["id"] == 23922
    rejected = next(item for item in engine.evaluate(
        _state(charge, shield_slam), uses={100: 1}) if item.ability_id == 100)
    assert "movement_opener_already_used" in rejected.rejection_reasons
    assert "melee_range_confirmed" in rejected.rejection_reasons


def test_slam_catalog_exposes_its_rage_cost_to_the_rule_engine():
    engine = AbilityRuleEngine()
    slam = {"id": 1464, "name": "Slam", "kind": "spell", "action": "ACTIONBUTTON2",
            "is_harmful": True, "is_usable": True, "in_range": True,
            "cooldown_remaining": 0}
    candidate = engine.evaluate(_state(slam, power=0))[0]
    assert candidate.definition.resource_cost == 20.
    assert "insufficient_resource" in candidate.rejection_reasons
