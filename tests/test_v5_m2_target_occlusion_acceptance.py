"""M2-E integration replay at the production CombatController boundary."""

from wowbot.agent.combat_controller import CombatController, CombatPhase
from wowbot.agent.target_manager import TargetLifecycle


def _state(target, track_state="ACTIVE"):
    return {
        "target": target,
        "is_in_combat": True,
        "nearby_attackable_entities": ([target] if target.get("guid") else []),
        "visual_candidates": [{
            "track_id": "WORLD3D:17",
            "lifecycle": track_state,
            "source": "WORLD3D",
        }],
        "actionbar": [{
            "kind": "spell", "is_harmful": True, "is_usable": True,
            "in_range": True, "action": "ACTIONBUTTON1",
        }],
    }


def test_combat_keeps_same_guid_and_track_across_occluded_then_reacquired():
    guid = "Creature-12"
    selected = {"guid": guid, "attackable": True,
                "visual_track_id": "WORLD3D:17", "health": 100}
    controller = CombatController()

    assert controller.observe(_state(selected), 1.0) is CombatPhase.ENGAGE
    assert controller.target_manager.lifecycle is TargetLifecycle.ENGAGED

    # Brief selected-unit loss retains both canonical identities.
    assert controller.observe(_state({}, "OCCLUDED"), 1.2) is CombatPhase.ACQUIRE
    assert controller.target_manager.lifecycle is TargetLifecycle.OCCLUDED
    assert controller.target_guid == guid
    assert controller.target_manager.current_track_id == "WORLD3D:17"

    # The same temporal track returns, but combat remains in acquire until the
    # addon confirms the selected GUID. No different candidate is promoted.
    assert controller.observe(_state({}, "REACQUIRED"), 1.5) is CombatPhase.ACQUIRE
    assert controller.target_manager.lifecycle is TargetLifecycle.REACQUIRING
    assert controller.target_guid == guid

    assert controller.observe(_state(selected, "REACQUIRED"), 1.6) is CombatPhase.ENGAGE
    assert controller.target_manager.lifecycle is TargetLifecycle.ENGAGED
    assert controller.target_guid == guid

