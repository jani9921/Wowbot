"""Live 2026-10-28 10:53:42-10:54:53 (Claimant to the Throne 66780, "Speak
with Left and Right", Obsidian Citadel): the only plan was a TDB-POI walk,
chosen 1.7 s before the server sent Left and Right 12 yd away.  The route had
been planned on a floor 10 yd below the observed height (387.6 vs 377.6); the
walk spun 70 s around waypoint 2 (1.8 yd flat) and was never replanned."""
from types import SimpleNamespace

from wowbot.agent.engine_runtime_projection import movement_visual_interrupt
from wowbot.agent.server_npc_planning import objective_npc_available

from test_observed_layer_route_20261027 import RUNNING, _navigation, _state

LEFT = "Creature-0-1463-2444-47-191710-0000616823"


def citadel(*, created=100., flags=1, z=387.64):
    return {
        "monotonic_time": 120., "map_id": 2022,
        "player_world_position": {"x": 2417.1, "y": 2672.5, "z": 387.56, "z_observed": True,
                                  "instance_id": 2444, "coordinate_space": "WORLD_YARDS"},
        "active_quests": [{"quest_id": 66780, "is_complete": False, "objectives": [
            {"description": "0/1 Speak with Talonstalker Kavia", "is_complete": False},
            {"description": "0/1 Speak with Left and Right", "is_complete": False}]}],
        "reference_knowledge": {"quests": {"66780": {"objectives": [
            {"description": "Speak with Left and Right", "credit_action": "TALK", "raw_type": 0,
             "credit_kind": "CREATURE_CREDIT", "credit_object_id": 190847,
             "talk_creatures": [{"entry": 191710, "name": "Left"}, {"entry": 191711, "name": "Right"}]}]}}},
        "packet_entities": {LEFT: {
            "guid": LEFT, "kind": "CREATURE", "entry_id": 191710, "map_id": 2444,
            "info": {"npc_flags": flags, "sampled_at": created},
            "position": {"x": 2436.34, "y": 2659.65, "z": z, "source": "PACKET_CREATE_MOVEMENT",
                         "sampled_at": created}}}}


def search_walk(started_at=99.):
    return SimpleNamespace(started_at=started_at, proposal=SimpleNamespace(skill="MOVE", parameters={
        "purpose": "LOCATE_QUEST_OBJECTIVE_REGION", "quest_id": 66780, "objective_id": "66780:1",
        "x": 2435., "y": 2660., "coordinate_space": "WORLD_YARDS", "instance_id": 2444,
        "knowledge_priority": "PRIMARY_STATIC", "stop_distance": 8.}))


def test_a_poi_search_walk_yields_to_the_objective_npc_the_server_just_sent():
    for identity_only in (True, False):                # fast lane and medium tick
        result = movement_visual_interrupt(search_walk(), citadel(), identity_only=identity_only)
        assert result["kind"] == "SERVER_OBJECTIVE_NPC_AVAILABLE" and result["guid"] == LEFT


def test_an_npc_known_before_the_walk_or_not_talkable_does_not_cancel_it():
    assert movement_visual_interrupt(search_walk(started_at=101.), citadel()) is None
    assert objective_npc_available(citadel(flags=0), 66780) is None
    assert objective_npc_available(citadel(), 66779) is None                 # another quest's walk
    done = citadel()
    done["active_quests"][0]["objectives"][1].update(description="1/1 Speak with Left and Right",
                                                     is_complete=True)
    assert objective_npc_available(done, 66780) is None


def test_a_route_ten_yards_below_the_observed_floor_fails():
    nav = _navigation()
    nav._movement.destination.update(z=250.3, layer_z=250.3)               # 10 yd under the wall top
    nav._route_on_observed_other_layer(_state(10.), RUNNING, 10.)
    result = nav._route_on_observed_other_layer(_state(12.2), RUNNING, 12.2)
    assert result.terminal and result.reason == "route_on_observed_other_layer"
    nav = _navigation()
    nav._movement.destination.update(z=255.3, layer_z=255.3)               # a 5 yd slope/step stays
    for t in (10., 12.2, 14.):
        assert nav._route_on_observed_other_layer(_state(t), RUNNING, t) is None


def test_a_route_planned_without_own_height_fails_on_the_first_contradicting_packet():
    nav = _navigation()
    nav._route_own_z_unobserved = True
    nav._movement.destination.update(z=250.3, layer_z=250.3)
    result = nav._route_on_observed_other_layer(_state(10.), RUNNING, 10.)
    assert result.terminal and result.reason == "route_on_observed_other_layer"
    nav = _navigation()
    nav._route_own_z_unobserved = True
    nav._movement.destination.update(z=258.3, layer_z=258.3)               # the guess was right
    assert nav._route_on_observed_other_layer(_state(10.), RUNNING, 10.) is None
    assert nav._route_own_z_unobserved is False


def test_a_late_context_also_gets_the_latest_unit_health_and_target():
    """The snapshot slot "unit" (2026-10-27) was stored but never replayed."""
    from wowbot.packetio.forwarder import EntitySnapshot
    from wowbot.packetio.models import AgentPacketEvent
    snapshot = EntitySnapshot()
    update = AgentPacketEvent.create(
        pid=7236, flow_id="flow", direction="SERVER_TO_CLIENT", event_type="ENTITY_UNIT_UPDATE",
        timestamp=1000., semantic_status="CONFIRMED", opcode=0,
        payload={"entity_guid": "0"*32, "entry_id": 191710, "health": 9}, provenance={}, confidence=1.)
    snapshot.note(update)
    (replayed,) = snapshot.replay(2000.)
    assert replayed.event_type == "ENTITY_UNIT_UPDATE" and replayed.timestamp == 2000.
