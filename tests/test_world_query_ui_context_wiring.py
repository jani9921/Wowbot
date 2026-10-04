"""V4-011 wiring: WorldQuery.ui_context()."""
from wowbot.agent.ui_context import BlockingState, PrimaryPanel
from wowbot.agent.world import WorldModel


def test_world_query_exposes_ui_context():
    world = WorldModel()
    context = world.query.ui_context()
    assert context.primary_panel is PrimaryPanel.WORLD
    assert context.blocking_state is BlockingState.NONE


def test_world_query_ui_context_reflects_stored_state():
    world = WorldModel()
    world.state["loading"] = True
    context = world.query.ui_context()
    assert context.blocking_state is BlockingState.LOADING
