from wowbot.agent.combat_controller import CombatController, CombatPhase


def test_combat_lifecycle_range_health_trend_and_death():
    controller = CombatController()
    state = {"target": {"guid": "mob", "attackable": True, "health": 100,
                        "max_health": 100},
             "actionbar": [{"kind": "spell", "is_harmful": True, "in_range": False}]}
    assert controller.observe(state, 1) == CombatPhase.APPROACH
    state["target"]["health"] = 70
    state["actionbar"][0]["in_range"] = True
    assert controller.observe(state, 2) == CombatPhase.ENGAGE
    assert controller.snapshot()["target_health_trend"] == -30
    state["target"]["dead"] = True
    assert controller.observe(state, 3) == CombatPhase.TARGET_DEAD


def test_combat_recovery_reason_keeps_range_los_facing_and_target_distinct():
    assert CombatController.recovery_reason({"ui_error": "Target is out of range"}) == "OUT_OF_RANGE"
    assert CombatController.recovery_reason({"ui_error": "Line of sight"}) == "LINE_OF_SIGHT"
    assert CombatController.recovery_reason({"ui_error": "Invalid target"}) == "INVALID_TARGET"


def test_combat_policy_uses_priority_resource_and_defensive_interrupt():
    controller = CombatController()
    state = {"health": 20, "max_health": 100, "power": 10,
             "defensive_spell_ids": [2], "target": {"guid": "m", "attackable": True},
             "actionbar": [
                 {"kind": "spell", "id": 1, "action": "A", "is_harmful": True,
                  "is_usable": True, "in_range": True, "cooldown_remaining": 0,
                  "combat_priority": 100, "resource_cost": 20},
                 {"kind": "spell", "id": 2, "action": "B", "is_harmful": False,
                  "is_usable": True, "in_range": True, "cooldown_remaining": 0}]}
    controller.observe(state, 1)
    assert controller.choose_action(state, record=True)["id"] == 2
    assert controller.snapshot()["survival_interrupts"] == 1
