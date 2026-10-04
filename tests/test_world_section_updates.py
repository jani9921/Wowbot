from wowbot.agent.models import Observation
from wowbot.agent.world import WorldModel


def observation(source="ADDON_TELEMETRY", at=1., **payload):
    payload.setdefault("session_id", "session:1")
    payload.setdefault("timestamp", 1000.+at)
    payload.setdefault("frame_id", f"{source}:{at}")
    return Observation.create(payload, at, source)


def test_addon_mutation_is_attributed_per_major_section():
    world = WorldModel()
    obs = observation(
        session_id="session:1", map_id=2175,
        health=100, target={"guid": "Creature-1"}, is_in_combat=True,
        active_quests=[{"quest_id": 1}], quest_ui={"open": True},
        loading=False)
    assert world.ingest(obs)

    for section in ("PlayerState", "TargetState", "EntityMap", "CombatState",
                    "NavigationState", "QuestState", "InteractionState",
                    "UIState", "MapState", "RecoveryState"):
        update = world.section_updates[section]
        assert update["observation_id"] == obs.observation_id
        assert update["source"] == "ADDON_TELEMETRY"
        assert update["updated_at"] == 1.
        assert update["source_timestamp"] == 1001.
        assert update["revision"] == world.revision


def test_supplemental_sources_update_only_their_owned_major_sections():
    world = WorldModel()
    world.session_id = "session:1"
    obs = observation(
        "WORLD3D", 2., visual_candidates=[{"track_id": "t1"}])
    assert world.ingest(obs)
    assert set(world.section_updates) == {"EntityMap", "EnvironmentState"}

    nav = observation(
        "WORLD3D_LOCAL_VIEW", 3., local_traversability={"free": .8})
    assert world.ingest(nav)
    assert world.section_updates["NavigationState"]["observation_id"] == nav.observation_id
    assert world.section_updates["EntityMap"]["observation_id"] == obs.observation_id


def test_planning_and_diagnostic_snapshots_expose_isolated_attribution():
    world = WorldModel()
    obs = observation(session_id="session:1", health=100)
    world.ingest(obs)
    planning = world.planning_snapshot(2.)
    diagnostic = world.snapshot(2.)
    assert planning.section_updates["PlayerState"]["observation_id"] == obs.observation_id
    assert diagnostic["section_updates"]["PlayerState"]["source"] == "ADDON_TELEMETRY"
    diagnostic["section_updates"]["PlayerState"]["source"] = "tampered"
    assert world.section_updates["PlayerState"]["source"] == "ADDON_TELEMETRY"
