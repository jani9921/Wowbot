from wowbot.verification import MovementVerifier, UiPanelVerifier, Verifier
from wowbot.verification.base import Verifier as BaseVerifier


def test_all_seven_verifier_modules_are_present_per_v4_040():
    # base, movement, interaction, combat, loot, quest, ui
    import wowbot.verification.base
    import wowbot.verification.movement
    import wowbot.verification.interaction
    import wowbot.verification.combat
    import wowbot.verification.loot
    import wowbot.verification.quest
    import wowbot.verification.ui  # noqa: F401 -- import-only presence check


def test_existing_verifiers_satisfy_the_shared_structural_protocol():
    from wowbot.verification import CombatVerifier, InteractionVerifier, LootVerifier, QuestProgressVerifier
    assert isinstance(CombatVerifier(), BaseVerifier)
    assert isinstance(InteractionVerifier(), BaseVerifier)
    assert isinstance(LootVerifier(), BaseVerifier)
    assert isinstance(QuestProgressVerifier(), BaseVerifier)
    assert Verifier is BaseVerifier


def test_movement_verifier_confirms_arrival_within_radius():
    verifier = MovementVerifier()
    before = {"player_world_position": {"x": 0.0, "y": 0.0}}
    after = {"player_world_position": {"x": 1.0, "y": 1.0}}
    result = verifier.evaluate(before, after, destination=(0.0, 0.0), arrival_radius=3.0)
    assert result.success
    assert "within_arrival_radius" in result.evidence


def test_movement_verifier_reports_progress_without_arrival():
    verifier = MovementVerifier()
    before = {"player_world_position": {"x": 100.0, "y": 0.0}}
    after = {"player_world_position": {"x": 50.0, "y": 0.0}}
    result = verifier.evaluate(before, after, destination=(0.0, 0.0), arrival_radius=3.0)
    assert not result.success
    assert "distance_decreasing" in result.evidence


def test_movement_verifier_flags_no_progress_when_distance_does_not_shrink():
    verifier = MovementVerifier()
    before = {"player_world_position": {"x": 50.0, "y": 0.0}}
    after = {"player_world_position": {"x": 50.0, "y": 0.0}}
    result = verifier.evaluate(before, after, destination=(0.0, 0.0), arrival_radius=3.0)
    assert not result.success


def test_movement_verifier_requires_a_destination():
    verifier = MovementVerifier()
    result = verifier.evaluate({}, {"player_world_position": {"x": 0.0, "y": 0.0}}, destination=None)
    assert not result.success


def test_ui_panel_verifier_confirms_open_transition():
    verifier = UiPanelVerifier()
    before = {"world_map": {"open": False}}
    after = {"world_map": {"open": True}}
    result = verifier.evaluate(before, after, panel_key="world_map", expect_open=True)
    assert result.success
    assert "panel_transitioned" in result.evidence


def test_ui_panel_verifier_rejects_still_closed_when_open_expected():
    verifier = UiPanelVerifier()
    before = {"quest_ui": {"open": False}}
    after = {"quest_ui": {"open": False}}
    result = verifier.evaluate(before, after, panel_key="quest_ui", expect_open=True)
    assert not result.success


def test_ui_panel_verifier_supports_the_flat_open_suffix_convention():
    verifier = UiPanelVerifier()
    before = {"gossip_open": False}
    after = {"gossip_open": True}
    result = verifier.evaluate(before, after, panel_key="gossip", expect_open=True)
    assert result.success
