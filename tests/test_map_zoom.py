from test_agent_map_discovery import world
from wowbot.agent.models import Attempt, Goal, Prediction, Proposal
from wowbot.agent.planner import Planner
from wowbot.agent.skills import SkillRegistry


def test_unknown_map_retry_zoom_is_bounded_and_requires_new_revision():
    registry = SkillRegistry()
    planner = Planner(registry)
    marker = {"kind": "unknown_map_marker", "source": "WORLD_MAP_CV", "x": .4,
              "y": .6, "confidence": .9, "semantic_type": "UNKNOWN"}
    state = world(world_map_open=True, visual_candidates=[marker])
    goal = Goal.parse("Questelj", 1.)
    assert not planner.inspections(state, 1., "WORLD_MAP_CV", goal)[0].parameters.get("map_zoom_in")
    planner.map_zoom_requested = True
    proposal = planner.inspections(state, 1., "WORLD_MAP_CV", goal)[0]
    assert registry.commands(proposal, state)[0].kind == "MAP_ZOOM_IN"
    planner.map_zoom_count = 1
    assert planner.inspections(state, 2., "WORLD_MAP_CV", goal) == []
    fresh = world(world_map_open=True, visual_candidates=[{**marker, "map_zoom_revision": 5}])
    planner.map_zoom_count = 5
    assert not planner.inspections(fresh, 3., "WORLD_MAP_CV", goal)[0].parameters.get("map_zoom_in")


def test_zoom_rejected_outside_world_map_and_during_combat():
    registry = SkillRegistry()
    proposal = Proposal.make("INSPECT", "zoom", {"source": "WORLD_MAP_CV", "x": .4,
                                                "y": .6, "map_zoom_in": True})
    assert not registry.available(proposal, world(world_map_open=False))
    assert not registry.available(proposal, world(world_map_open=True, is_in_combat=True))


def test_requested_zoom_survives_rejection_and_expired_scan():
    class RejectedMemory:
        def rejection_status(self, *args, **kwargs):
            return {"belief": "REJECTED", "confidence": 1.}
        def sensor_profile(self, *args, **kwargs):
            return {"samples": 0, "weight": .5, "health": "UNKNOWN"}
        def learning_context(self, *args, **kwargs):
            return {}
    registry = SkillRegistry()
    planner = Planner(registry, RejectedMemory())
    planner.map_scan_started = 1.
    planner.map_zoom_requested = True
    marker = {"kind": "unknown_map_marker", "source": "WORLD_MAP_CV", "x": .4,
              "y": .6, "confidence": .9, "semantic_type": "UNKNOWN"}
    result = planner.candidates(Goal.parse("Questelj", 1.),
                                world(world_map_open=True, visual_candidates=[marker]), 30.)
    assert result[0].skill == "INSPECT"
    assert result[0].parameters["map_zoom_in"] is True
    assert planner.map_inspection_status()["zoom_limit"] == 5


def test_parent_map_step_verifies_only_from_addon_map_context_change():
    registry = SkillRegistry()
    proposal = Proposal.make("INSPECT", "parent", {
        "source": "WORLD_MAP_CONTEXT", "map_step_out": True,
        "x": .5, "y": .5, "expected_parent_map_id": 13})
    before = world(world_map_open=True,
                   map_context={"active_map_id": 1409, "parent_map_id": 13})
    attempt = Attempt(
        "a", proposal, before.state, "o", 1., 2., (),
        Prediction("p", "a", "parent map", 1., 2., "o"))
    pending = registry.verify(attempt, before, 1.2)
    assert pending[0].value == "PENDING"
    after = world(world_map_open=True,
                  map_context={"active_map_id": 13, "parent_map_id": 947})
    success = registry.verify(attempt, after, 1.3)
    assert success[0].value == "SUCCESS"
    assert success[1] == "parent_map_context_observed"
