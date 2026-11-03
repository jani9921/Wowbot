"""REV4 responsibility split (SRC_MELY_AUDIT 4.3/4.4).

NavigationService components: HazardAwareRouteValidator (hazard_route),
FallHazardMemory (fall_hazards), DestinationLayerResolver (layer_resolver),
CombatLocalPositioningAdapter (navigation_combat), TravelCostQueryPort
(travel_cost), ZoneSweepGeometry (zone_sweep), TravelTransitionPolicy
(travel_transitions).  CombatSkill components: CombatLocalRecovery
(combat_recovery), CombatFacingController (combat_facing), CombatArbitrator
(combat_arbitrator).  The service keeps request/route/waypoint ownership and
the single movement controller; the skill keeps the FSM and attempt state.
The old entry points delegate; behaviour is covered by the existing pit,
spiral, cave-layer, flight, LOS/range/facing and combat suites."""
import ast
from pathlib import Path

from wowbot.navigation.contracts import GlobalRoute
from wowbot.navigation.hazard_route import HazardAwareRouteValidator
from wowbot.navigation.service import NavigationService
from wowbot.skills.combat import CombatSkill

SRC = Path(__file__).resolve().parents[1] / "src" / "wowbot"


def _functions(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return {node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)}


def test_the_hazard_geometry_left_the_service():
    service = _functions(SRC / "navigation/service.py")
    moved = {"_drop_side", "_walkable_near", "_densified", "_edge_distance", "_near_offset_stuck",
             "_walkable_offsets", "_simplified"}
    assert not moved & service
    assert moved <= _functions(SRC / "navigation/hazard_route.py")
    assert not [name for name in vars(NavigationService) if name.startswith(("DROP_", "CENTER_"))]


def test_the_service_delegates_to_one_persistent_validator():
    nav = NavigationService()
    validator = nav.hazard_route
    assert isinstance(validator, HazardAwareRouteValidator)
    route = GlobalRoute("r", ({"x": 0., "y": 0., "z": 0.}, {"x": 1., "y": 0., "z": 0.}), (), 1., 1., 0., 1.)
    assert nav._away_from_drops(route) is route                  # two anchors: nothing to centre
    validator.note_offset_stuck(1., 2., 3.)
    nav.reset()
    assert nav.hazard_route is validator and validator.offset_stuck == [(1., 2., 3.)]
    assert validator._layers() is nav._z                         # reads the owner's current resolver


def test_the_combat_recovery_left_the_skill():
    skill = _functions(SRC / "skills/combat.py")
    source = (SRC / "skills/combat.py").read_text(encoding="utf-8")
    assert "_local_recovery_request" in skill and "CombatLocalRecovery(self).request" in source
    assert "request" in _functions(SRC / "skills/combat_recovery.py")
    # budgets stay overridable on the skill
    assert CombatSkill.RANGE_DIRECT_APPROACH_BUDGET == 2 and CombatSkill.LOS_RECOVERY_ATTEMPTS == 3


NAV_FORBIDDEN = ("wowbot.skills", "wowbot.vision", "navigation.service")
COMBAT_FORBIDDEN = ("wowbot.navigation", "wowbot.vision")


def test_the_new_components_import_no_owner_or_vision():
    for path, forbidden in ((SRC / "navigation/hazard_route.py", ("wowbot.agent", *NAV_FORBIDDEN)),
                            (SRC / "navigation/layer_resolver.py", ("wowbot.agent", *NAV_FORBIDDEN)),
                            (SRC / "navigation/zone_sweep.py", ("wowbot.agent", *NAV_FORBIDDEN)),
                            (SRC / "navigation/fall_hazards.py", ("wowbot.agent", *NAV_FORBIDDEN)),
                            (SRC / "navigation/travel_cost.py", NAV_FORBIDDEN),
                            (SRC / "navigation/travel_transitions.py", NAV_FORBIDDEN),
                            (SRC / "navigation/navigation_combat.py", NAV_FORBIDDEN),
                            (SRC / "skills/combat_recovery.py", COMBAT_FORBIDDEN),
                            (SRC / "skills/combat_facing.py", COMBAT_FORBIDDEN),
                            (SRC / "skills/combat_arbitrator.py", COMBAT_FORBIDDEN)):
        imported = set()
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ImportFrom):
                imported.add(node.module or "")
            elif isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
        assert not [name for name in imported if any(name.startswith(f) or f in name for f in forbidden)], imported


def test_fall_hazards_are_their_own_memory_that_a_reset_clears():
    from wowbot.navigation.fall_hazards import FallHazardMemory
    nav = NavigationService()
    memory = nav.fall_hazards
    assert isinstance(memory, FallHazardMemory) and nav._fall_hazards is memory.items
    memory.remember(10., 20., 30., 2175, 1.)
    memory.remember(10.5, 20., 31., 2175, 2.)                      # same ledge, same floor: once
    assert len(nav._fall_hazards) == 1
    route = GlobalRoute("r", ({"x": 0., "y": 20., "z": 30.}, {"x": 20., "y": 20., "z": 30.}), (), 1., 1., 0., 1.)
    assert memory.blocks(route, 2175, 0., 0., None, 3.)
    assert not memory.blocks(route, 2175, 10., 20., 30., 3.)      # still on the ledge's floor: no drop
    assert not memory.blocks(route, 2175, 0., 0., None, 1. + memory.FALL_HAZARD_TTL_SECONDS)   # expired
    memory.remember(10., 20., 30., 2175, 700.)
    nav.reset()
    assert nav.fall_hazards is memory and not memory.items
    assert not [name for name in vars(NavigationService) if name.startswith("FALL_HAZARD_")]


def _layered_nav(z=10.):
    nav = NavigationService()
    nav._z.seed_player(2175, 0., 0., z, 1.)
    return nav


def test_layer_resolution_is_its_own_component_reading_the_current_resolver():
    from wowbot.navigation.layer_resolver import DestinationLayerResolver
    nav = _layered_nav()
    resolver = nav.layer_resolver
    assert isinstance(resolver, DestinationLayerResolver) and resolver._layers() is nav._z
    nav.reset()
    assert nav.layer_resolver is resolver and resolver._layers() is nav._z      # the reset's new resolver
    assert not [name for name in vars(NavigationService)
                if name.startswith(("OBSERVED_LAYER", "OBSERVED_Z", "SEARCH_CELL_", "ROUTE_HINT_"))]
    route = GlobalRoute("r", ({"x": 0., "y": 0., "z": 5.}, {"x": 10., "y": 0., "z": 15.}), (), 1., 1., 0., 1.)
    nav._active_route = route
    state = {"player_world_position": {"x": 5., "y": 1., "instance_id": 2175}}
    assert nav._route_hint_z(state) == resolver.route_hint_z(route, state) == 10.


def test_the_observed_floor_watch_confirms_waits_then_contradicts():
    from wowbot.navigation.layer_resolver import DestinationLayerResolver
    watch = DestinationLayerResolver(lambda: None)
    observed = {"player_world_position": {"x": 0., "y": 0., "z": 30., "z_observed": True}}
    assert watch.observed_layer(observed, {"x": 1., "y": 0., "z": 28.}, False, False, 1.) == "CONFIRMED"
    other = {"x": 1., "y": 0., "z": 10.}
    assert watch.observed_layer(observed, other, False, False, 2.) is None            # persistence wait
    assert watch.observed_layer(observed, other, False, False, 3.5) is None
    assert watch.observed_layer(observed, other, False, False, 4.) == "CONTRADICTED"  # 2 s on another floor
    assert watch.observed_layer(observed, other, False, True, 4.1) == "CONTRADICTED"  # a probe: at once
    assert watch.observed_layer(observed, other, True, True, 4.2) is None             # skipped MOVE
    assert watch.observed_layer({}, other, False, True, 6.5) is None                  # the observed z aged out


def test_combat_positioning_is_an_adapter_not_a_mixin():
    from wowbot.navigation.navigation_combat import CombatLocalPositioningAdapter
    nav = NavigationService()
    adapter = nav.combat_positioning
    assert isinstance(adapter, CombatLocalPositioningAdapter)
    assert not any(base.__name__ == "NavigationCombatMixin" for base in NavigationService.__mro__)
    assert adapter._face is nav._face and adapter._danger is nav._danger and adapter._los_recovery is nav._los_recovery
    nav._latest_los_recovery = {"phase": "X"}
    assert adapter.latest_los_recovery == {"phase": "X"}
    nav.reset()
    assert adapter.latest_los_recovery is None
    assert nav.record_los_exhaustion("Creature-0-1-2-3-4-5", {"player_world_position": {"x": 1., "y": 2.}}, 1.)


def test_combat_facing_and_action_choice_left_the_skill():
    path = SRC / "skills/combat.py"
    source = path.read_text(encoding="utf-8")
    skill = next(node for node in ast.parse(source).body if isinstance(node, ast.ClassDef) and node.name == "CombatSkill")
    methods = {node.name: node for node in skill.body if isinstance(node, ast.FunctionDef)}
    for owner, names in (("CombatFacingController", ("_exact_facing_turn", "_facing_sweep_step",
                                                     "_continue_facing_sweep", "_sweep_attack_binding",
                                                     "_interact_attacks_expected")),
                         ("CombatArbitrator", ("_next_action", "_auto_attack_fallback"))):
        for name in names:
            node = methods[name]
            assert owner in ast.get_source_segment(source, node) and len(node.body) == 1, name
    assert {"exact_turn", "sweep_step", "continue_sweep"} <= _functions(SRC / "skills/combat_facing.py")
    assert {"next_action", "auto_attack_fallback"} <= _functions(SRC / "skills/combat_arbitrator.py")
    assert "_target_bearing_error" in methods                # the selected-GUID check stays the skill's boundary


def test_cost_queries_and_sweep_geometry_own_only_their_caches():
    from wowbot.navigation.travel_cost import TravelCostQueryPort
    from wowbot.navigation.zone_sweep import ZoneSweepGeometry
    nav = _layered_nav(z=42.)
    assert isinstance(nav.travel_cost, TravelCostQueryPort) and isinstance(nav.zone_geometry, ZoneSweepGeometry)
    assert not [name for name in vars(NavigationService)
                if name.startswith(("RECOVERY_PROBE", "RECOVERY_FLOOR", "WALK_COST_", "LOWER_LAYER_"))]
    state = {"player_world_position": {"x": 0., "y": 0., "instance_id": 2175}, "monotonic_time": 1.}
    assert nav.player_layer_z(state) == nav.travel_cost.player_layer_z(state) == 42.
    assert nav.zone_geometry._player_layer()[:4] == (2175, 0., 0., 42.)
    nav.zone_geometry.lower_layer_cache[(1, 2, 3)] = None
    nav.reset()
    assert not nav.zone_geometry.lower_layer_cache
    assert nav.zone_geometry._hop_yards() == nav.ZONE_SWEEP_HOP_YARDS


def test_the_server_position_wait_is_its_own_component_behind_the_old_views():
    from wowbot.navigation.position_acquisition import ServerPositionWait
    nav = NavigationService()
    wait = nav.position_wait
    assert isinstance(wait, ServerPositionWait) and nav._position_wait is None
    state = {"session_id": "s", "character_guid": "Player-1",
             "player_world_position": {"x": 0., "y": 0., "instance_id": 0}}
    wait.begin("r", state, 10., 3.)
    assert nav._position_wait == {"started_at": 10., "scope": ("s", "Player-1", 0, None)}
    assert wait.status(state, 11., 3., 10., 20.) == "WAITING"
    assert wait.status(state, 13., 3., 10., 20.) == "server_position_probe_timeout"
    assert wait.status({**state, "session_id": "t"}, 11., 3., 10., 20.) == "server_position_probe_context_changed"
    nav.cancel_movement()
    assert nav._position_wait is None and nav._position_acquisition_snapshot()["phase"] == "CANCELLED"
    nav.reset()
    assert nav.position_wait is wait and wait.trace is None


def test_flight_departure_transitions_are_decisions_only():
    from wowbot.navigation.travel_transitions import TravelTransitionPolicy
    goal = {"x": 1., "y": 2., "flight_departure": {"flight_style": "STEADY"}, "flight": False}
    assert TravelTransitionPolicy.flight_destination(goal, "STEADY") == {
        "x": 1., "y": 2., "flight": True, "flight_style": "STEADY"}
    assert TravelTransitionPolicy.after_departure_walk(
        goal, {"is_mounted": False, "movement": {"indoors": True}}) is None              # still inside: wait
    nav = NavigationService()
    nav.travel_transitions.departures["k"] = None
    nav.cancel_movement()
    assert not nav.travel_transitions.departures and not nav._departure_active()
