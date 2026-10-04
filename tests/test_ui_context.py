from wowbot.agent.ui_context import (
    BlockingState, PrimaryPanel, UiContextResolver, resolve_ui_context,
)


def test_empty_state_resolves_to_world_with_no_blocking():
    context = resolve_ui_context({})
    assert context.primary_panel is PrimaryPanel.WORLD
    assert context.blocking_state is BlockingState.NONE
    assert context.overlays == ()


def test_loading_is_a_blocking_state_that_hides_panel_identity():
    context = resolve_ui_context({"loading": True, "quest_offer_open": True})
    assert context.blocking_state is BlockingState.LOADING
    assert context.primary_panel is PrimaryPanel.UNKNOWN


def test_cinematic_is_a_blocking_state():
    context = resolve_ui_context({"cinematic_playing": True})
    assert context.blocking_state is BlockingState.CINEMATIC


def test_player_dead_is_a_blocking_state():
    context = resolve_ui_context({"is_dead": True})
    assert context.blocking_state is BlockingState.PLAYER_DEAD


def test_disconnected_outranks_every_other_blocking_state():
    context = resolve_ui_context({"disconnected": True, "is_dead": True, "loading": True})
    assert context.blocking_state is BlockingState.DISCONNECTED


def test_vehicle_override_is_a_blocking_state():
    context = resolve_ui_context({"vehicle_ui": True})
    assert context.blocking_state is BlockingState.VEHICLE_OVERRIDE


def test_no_blocking_state_resolves_gossip_panel():
    context = resolve_ui_context({"gossip_open": True})
    assert context.blocking_state is BlockingState.NONE
    assert context.primary_panel is PrimaryPanel.GOSSIP


def test_quest_offer_panel_is_recognized():
    context = resolve_ui_context({"quest_offer_open": True})
    assert context.primary_panel is PrimaryPanel.QUEST_OFFER


def test_overlays_are_collected_independently_of_the_primary_panel():
    context = resolve_ui_context({
        "gossip_open": True,
        "quest_tool_button_visible": True,
        "extra_action_button_visible": True,
    })
    assert context.primary_panel is PrimaryPanel.GOSSIP
    assert set(context.overlays) == {"quest_tool_button", "extra_action_button"}


def test_nested_open_dict_convention_is_also_recognized():
    context = resolve_ui_context({"vendor_ui_open": {"open": True}})
    assert context.primary_panel is PrimaryPanel.VENDOR


def test_confidence_is_higher_when_a_specific_panel_or_block_is_recognized():
    unknown = resolve_ui_context({})
    specific = resolve_ui_context({"gossip_open": True})
    assert specific.confidence > unknown.confidence


def test_stateful_resolver_tracks_stability_and_capability_gates():
    resolver = UiContextResolver()
    resolver.resolve({"quest_offer_open": True}, observed_at=10.0)
    assert resolver.can_accept_quest()
    assert not resolver.can_turnin()
    assert not resolver.can_interact_world()
    assert not resolver.stable_for(200, now=10.1)
    assert resolver.stable_for(200, now=10.2)
    resolver.resolve({"quest_complete_open": True}, observed_at=10.3)
    assert resolver.can_turnin()
    assert not resolver.can_accept_quest()


def test_stateful_resolver_rejects_out_of_order_state_and_invalidation_fails_closed():
    resolver = UiContextResolver()
    resolver.resolve({"world_map_open": True}, observed_at=5.0)
    stale = resolver.resolve({"quest_offer_open": True}, observed_at=4.0)
    assert stale.primary_panel is PrimaryPanel.MAP
    resolver.invalidate()
    assert resolver.is_blocking()
    assert not resolver.can_interact_world()
    assert not resolver.stable_for(0, now=6.0)
