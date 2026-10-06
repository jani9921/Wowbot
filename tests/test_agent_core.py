from copy import deepcopy
import json
import math
from pathlib import Path
import threading
import time
from types import SimpleNamespace

import pytest

from wowbot.agent.bindings import BindingsCache, BindingError
from wowbot.agent.engine import AutonomousAgent
from wowbot.agent.executor import InputExecutor, RecordingExecutor, ExecutionError
from wowbot.agent.models import Observation, Goal, Mode, Command, Proposal, Outcome
from wowbot.agent.memory import AgentMemory
from wowbot.agent.world import WorldModel
from wowbot.agent.navigation import AgentNavigator
from wowbot.agent.skills import SkillRegistry
from wowbot.agent.autonomy_loop import AutonomousLoop, RuntimePhase
from wowbot.navigation.graph import NavGraph, NavGraphEdge, NavGraphNode
from wowbot.vision.models import WorldPosition


def state(t=1., **overrides):
    result = {"session_id": "test:player-1", "timestamp": t, "monotonic_time": t,
              "frame_id": f"test:{t}", "map_id": 1609, "position": {"x": .5, "y": .5},
              "orientation": 0., "player_present": True, "is_dead": False, "is_in_combat": False,
              "target": None, "mouseover": None, "active_quests": [], "actionbar": [], "events": [],
              "event_sequence": 0, "inventory": {"items": [], "free_slots": 10}, "quest_ui": {"open": False, "entries": []}}
    result.update(overrides)
    return result


def agent(goal="Questelj", params=None, memory=None):
    executor = RecordingExecutor()
    value = AutonomousAgent(executor, memory=memory)
    value.set_goal(goal, 1., params)
    value.set_mode(Mode.FULL_AI)
    return value, executor


def binding_file(tmp_path, extra=""):
    path = tmp_path / "bindings-cache.wtf"
    path.write_text('bind "W" "MOVEFORWARD"\nbind "A" "TURNLEFT"\nbind "D" "TURNRIGHT"\nbind "Q" "STRAFELEFT"\nbind "E" "STRAFERIGHT"\nbind "SPACE" "JUMP"\nbind "F" "INTERACTTARGET"\nbind "1" "ACTIONBUTTON1"\n' + extra, encoding="utf-8")
    return path


def test_goal_replacement_rebinds_terminal_processor_to_new_quest_runtime():
    value, _ = agent()
    old_runtime = value.quest_runtime
    value.set_goal("Questelj tovább", 2.)
    assert value.quest_runtime is not old_runtime
    assert value.quest_terminal.quest_runtime is value.quest_runtime
    assert value.quest_terminal.quest_domain is value.planner.quest


class Backend:
    def __init__(self):
        self.foreground, self.emergency, self.calls = True, False, []
    def is_selected_foreground(self): return self.foreground
    def emergency_pressed(self): return self.emergency
    def key(self, key, down): self.calls.append((key, down))
    def move(self, x, y): self.calls.append((x, y))
    def wheel_up(self): self.calls.append(("WHEEL_UP", 120))


def test_bindings_exact_file_later_assignment_and_no_fallback(tmp_path):
    path = binding_file(tmp_path, 'bind "W" "MOVEBACKWARD"\nbind "Z" "MOVEFORWARD"\n')
    cache = BindingsCache(path)
    assert cache.resolve("MOVEFORWARD") == "Z"
    assert cache.resolve("MOVEBACKWARD") == "W"
    with pytest.raises(BindingError): cache.resolve("TARGETNEARESTENEMY")
    assert not cache.contains(None)
    path.write_text('bind "X" "MOVEFORWARD"', encoding="utf-8")
    assert not cache.unchanged()
    assert cache.resolve("MOVEFORWARD") == "Z"  # Never silently reload while controlling.


def test_partial_cache_preflight_and_none_unbind(tmp_path):
    path = tmp_path / "bindings-cache.wtf"
    path.write_text('bind Q STRAFELEFT\nbind W NONE\nbind F7 INTERACTTARGET\n')
    cache = BindingsCache(path)
    check = cache.preflight("QUEST", [{"action": "ACTIONBUTTON1", "is_harmful": True}])
    assert not cache.contains("NONE") and not check["ready"]
    assert "MOVEFORWARD" in check["missing"] and "ACTIONBUTTON1" in check["missing"]


def test_session_change_clears_all_session_local_planner_state():
    value, exe = agent()
    value.tick(state(1), 1)
    value.planner.blocked_until["old"] = 50
    value.planner.recent["old"] = 50
    value.planner.map_scan_started = 1
    value.planner.map_probes = 4
    value.planner.map_zoom_count = 3
    value.planner.map_zoom_requested = True
    value.planner.map_search_exhausted = True
    value.planner.map_search_context = ("test:player-1", 1609, 1)
    value.planner.last_map_scan_started = 1
    value.planner.used_location_fallbacks.add(("old",))
    value.planner.camera_search_step = 5
    value.planner.camera_search_next_at = 50
    value.planner.camera_search_position = (.4, .5)
    value.planner.world3d_probe_count = 6
    value.planner.quest.interaction_range_blocks["old-guid"] = {"at": 1}
    value.planner.quest.failed_map_locations.add("old-location")
    value.planner.quest.used_spawn_fallbacks.add(("old-spawn",))
    value.planner.quest.reference_arrivals.add("old-guid")
    value.planner.quest.allow_db_fallback = True
    value.planner.quest.confirmed_mouseover_anchors["old-guid"] = {"x": .5}
    value.planner.quest.reached_quest_locations[("old",)] = "signature"
    value.planner.quest.interacted_guids["old-guid"] = "signature"
    value.planner.pattern_analysis = {"mode": "MATCHED"}
    value.planner.last_scores["old"] = {"score": 1}
    value.failures["old"] = 2
    value.approach_counts["old"] = 2
    exe.commands.clear()

    value.tick(state(2, session_id="test:player-2"), 2)

    assert value.mode == Mode.MANUAL
    assert value.last_result["reason"] == "character_or_session_changed"
    assert not value.planner.blocked_until and not value.planner.recent
    assert value.planner.map_scan_started is None and value.planner.map_probes == 0
    assert value.planner.map_zoom_count == 0 and value.planner.map_zoom_requested is False
    assert value.planner.map_search_context is None and value.planner.map_search_exhausted is False
    assert not value.planner.used_location_fallbacks
    assert value.planner.camera_search_step == 0 and value.planner.camera_search_position is None
    assert value.planner.world3d_probe_count == 0
    assert not value.planner.quest.interaction_range_blocks
    assert not value.planner.quest.failed_map_locations
    assert not value.planner.quest.used_spawn_fallbacks
    assert not value.planner.quest.reference_arrivals
    assert value.planner.quest.allow_db_fallback is False
    assert not value.planner.quest.confirmed_mouseover_anchors
    assert not value.planner.quest.reached_quest_locations
    assert not value.planner.quest.interacted_guids
    assert value.planner.pattern_analysis["mode"] == "NO_REFERENCE"
    assert not value.planner.last_scores and not value.failures and not value.approach_counts
    assert not exe.commands


@pytest.mark.parametrize("reason", ["focus", "f12", "stop", "cache"])
def test_executor_refuses_invalid_state_without_input(tmp_path, reason):
    path = binding_file(tmp_path)
    backend = Backend()
    exe = InputExecutor(42, BindingsCache(path), backend)
    if reason == "focus": backend.foreground = False
    if reason == "f12": backend.emergency = True
    if reason == "stop": exe.stop()
    if reason == "cache": path.write_text('bind "Z" "MOVEFORWARD"', encoding="utf-8")
    with pytest.raises(ExecutionError): exe.execute((Command("BIND", "MOVEFORWARD"),))
    assert backend.calls == []


def test_executor_pulses_selected_binding_and_releases(tmp_path):
    backend = Backend()
    exe = InputExecutor(42, BindingsCache(binding_file(tmp_path)), backend)
    exe.execute((Command("BIND", "MOVEFORWARD", .001, simultaneous=("TURNLEFT",)),))
    assert backend.calls[:2] == [("W", True), ("A", True)]
    assert set(backend.calls[2:]) == {("W", False), ("A", False)}


def test_world_map_zoom_moves_then_sends_one_wheel_not_a_binding(tmp_path):
    backend = Backend()
    exe = InputExecutor(42, BindingsCache(binding_file(tmp_path)), backend)
    exe.execute((Command("MAP_ZOOM_IN", x=.4, y=.6),))
    assert backend.calls == [(.4, .6), ("WHEEL_UP", 120)]


def test_world_map_parent_step_is_one_bounded_right_click(tmp_path):
    backend = Backend()
    exe = InputExecutor(42, BindingsCache(binding_file(tmp_path)), backend)
    exe.execute((Command("MAP_STEP_OUT", x=.5, y=.5),))
    assert backend.calls == [(.5, .5), ("BUTTON2", True), ("BUTTON2", False)]


def test_camera_search_uses_bounded_left_drag_inside_client(tmp_path):
    backend = Backend()
    exe = InputExecutor(42, BindingsCache(binding_file(tmp_path)), backend)
    exe.execute((Command("CAMERA_PAN", duration=.001, x=.36, y=.45, button="LEFT"),))
    assert backend.calls == [(.5, .45), ("BUTTON1", True), (.36, .45), ("BUTTON1", False)]


def test_movement_lease_keeps_forward_held_across_steering_updates(tmp_path):
    backend = Backend()
    exe = InputExecutor(42, BindingsCache(binding_file(tmp_path)), backend)
    exe.execute_movement((Command("BIND", "MOVEFORWARD", .08, simultaneous=("TURNLEFT",)),))
    exe.execute_movement((Command("BIND", "MOVEFORWARD", .08),))
    assert backend.calls.count(("W", True)) == 1
    assert ("A", False) in backend.calls
    assert ("W", False) not in backend.calls
    time.sleep(.12)
    assert ("W", False) not in backend.calls
    exe.stop_movement()
    assert backend.calls[-1] == ("W", False)
    assert backend.calls.count(("W", False)) == 2
    assert exe.diagnostics()["movement_stops"] == 1


def test_movement_watchdog_releases_persistent_forward(tmp_path):
    backend = Backend()
    exe = InputExecutor(42, BindingsCache(binding_file(tmp_path)), backend)
    exe.movement_watchdog_seconds = .08
    exe.execute_movement((Command("BIND", "MOVEFORWARD", .05),))
    assert backend.calls == [("W", True)]
    time.sleep(.12)
    assert backend.calls[-1] == ("W", False)


def test_default_movement_watchdog_is_a_short_feedback_fail_safe(tmp_path):
    exe = InputExecutor(42, BindingsCache(binding_file(tmp_path)), Backend())
    assert exe.movement_watchdog_seconds <= .5


def test_stop_interrupts_held_keys(tmp_path):
    backend = Backend()
    exe = InputExecutor(42, BindingsCache(binding_file(tmp_path)), backend)
    failures = []
    def run():
        try: exe.execute((Command("BIND", "MOVEFORWARD", .3),))
        except ExecutionError as e: failures.append(str(e))
    worker = threading.Thread(target=run)
    worker.start()
    deadline = time.monotonic()+1
    while not backend.calls and time.monotonic() < deadline: time.sleep(.001)
    exe.stop()
    worker.join(1)
    assert not worker.is_alive()
    assert backend.calls == [("W", True), ("W", False)]
    assert failures


def test_invalid_batch_resolved_before_any_input(tmp_path):
    backend = Backend()
    exe = InputExecutor(42, BindingsCache(binding_file(tmp_path)), backend)
    with pytest.raises(BindingError):
        exe.execute((Command("BIND", "MOVEFORWARD"), Command("BIND", "MISSING")))
    assert backend.calls == []


def test_observations_immutable_deduplicated_and_stale():
    world = WorldModel()
    payload = state()
    obs = Observation.create(payload, 1.)
    payload["position"]["x"] = 0
    assert obs.payload["position"]["x"] == .5
    assert world.ingest(obs)
    assert not world.ingest(Observation.create(obs.payload, 3.))
    # A duplicate-content observation still proves the capture/decode
    # pipeline is alive (a genuinely new poll happened, values just didn't
    # change) -- last_received advances to the duplicate's own receipt time,
    # it just isn't reprocessed/rebuilt. Live-confirmed 2026-09-12: the old
    # "duplicates never refresh last_received" behavior forced spurious
    # MANUAL drops during ordinary stretches of unchanging game state (a
    # stable target held for a few seconds), not actual connection loss.
    assert world.fresh(5.9)
    assert world.fresh(7.1)
    assert not world.fresh(9.1)
    assert len(world.history) == 1


def test_unchanged_fresh_telemetry_is_not_reported_as_stalled_at_verify_deadline():
    world = WorldModel()
    payload = state(1, mouseover=None, cursor_position={"nx": .4, "ny": .5})
    first = Observation.create(payload, 1.)
    assert world.ingest(first)
    attempt = SimpleNamespace(
        observation_id=first.observation_id, deadline=2.5, started_at=1.,
        baseline=payload,
        proposal=Proposal.make("INSPECT", "test", {"x": .4, "y": .5}),
        commands=())

    # Same content/ID, but captured and decoded after the action.
    assert not world.ingest(Observation.create(payload, 2.))
    assert world.last_received == 2.
    assert SkillRegistry().verify(attempt, world, 2.5) == (
        Outcome.FAILURE, "expected_observation_missing")


def test_verify_still_reports_real_telemetry_stall_when_no_post_action_sample_arrives():
    world = WorldModel()
    payload = state(1)
    first = Observation.create(payload, 1.)
    assert world.ingest(first)
    attempt = SimpleNamespace(
        observation_id=first.observation_id, deadline=2.5, started_at=1.,
        baseline=payload,
        proposal=Proposal.make("INSPECT", "test", {"x": .4, "y": .5}),
        commands=())

    assert SkillRegistry().verify(attempt, world, 2.5) == (
        Outcome.FAILURE, "telemetry_stalled")


def test_fresh_fast_telemetry_remains_live_when_slow_detail_snapshot_ages():
    world = WorldModel()
    payload = state()
    payload["state_age"] = 16.5
    assert world.ingest(Observation.create(payload, 1.))
    # ``state_age`` is a slow paged-detail diagnostic, not proof that the
    # independent fast control lane has disconnected.
    assert world.fresh(4.4)
    assert world.fresh(4.6)
    assert world.detail_snapshot_stale(4.6)


def test_fast_state_updates_control_fields_without_refreshing_slow_facts():
    world = WorldModel()
    full = state(10, active_quests=[{"quest_id": 1, "objectives": []}],
                 movement={"speed": 0, "moving": False}, transport_kind="STATE",
                 telemetry_lane="FULL_STATE", state_age=0)
    assert world.ingest(Observation.create(full, 10))
    fast = state(11, active_quests=[{"quest_id": 999, "objectives": []}],
                 movement={"speed": 7, "moving": True}, orientation=1.2,
                 transport_kind="FAST", telemetry_lane="FAST_STATE",
                 fast_sequence=4, state_age=1)
    assert world.ingest(Observation.create(fast, 11))
    assert world.state["movement"] == {"speed": 7, "moving": True}
    assert world.state["orientation"] == 1.2
    assert [q["quest_id"] for q in world.state["active_quests"]] == [1]
    # A complete paged snapshot sampled slightly before the latest FAST frame
    # remains valid and can refresh the slow lane.
    newer_full = state(10.5, active_quests=[{"quest_id": 2, "objectives": []}],
                       transport_kind="STATE", telemetry_lane="FULL_STATE", state_age=.5)
    assert world.ingest(Observation.create(newer_full, 11.2))
    assert [q["quest_id"] for q in world.state["active_quests"]] == [2]


def test_compact_fast_same_guid_preserves_full_target_identity_fields():
    world = WorldModel()
    full = state(10, target={"guid": "Creature-0-1", "npc_id": 156626,
                             "name": "Lady Jaina Proudmoore", "unit_type": "NPC",
                             "attackable": False},
                 transport_kind="STATE", telemetry_lane="FULL_STATE")
    assert world.ingest(Observation.create(full, 10))

    compact = state(11, target={"guid": "Creature-0-1", "npc_id": 156626,
                                "attackable": False, "world_position": False},
                    transport_kind="FAST", telemetry_lane="FAST_STATE")
    assert world.ingest(Observation.create(compact, 11))

    assert world.state["target"]["name"] == "Lady Jaina Proudmoore"
    assert world.state["target"]["unit_type"] == "NPC"
    assert world.state["target"]["world_position"] is False


def test_compact_fast_different_guid_never_inherits_previous_identity():
    world = WorldModel()
    full = state(10, target={"guid": "Creature-old", "npc_id": 1,
                             "name": "Old NPC", "unit_type": "NPC"},
                 transport_kind="STATE", telemetry_lane="FULL_STATE")
    assert world.ingest(Observation.create(full, 10))

    compact = state(11, target={"guid": "Creature-new", "npc_id": 2,
                                "attackable": False},
                    transport_kind="FAST", telemetry_lane="FAST_STATE")
    assert world.ingest(Observation.create(compact, 11))

    assert world.state["target"]["guid"] == "Creature-new"
    assert world.state["target"].get("name") is None


def test_belief_source_hierarchy_and_correlation():
    world = WorldModel()
    world.ingest(Observation.create(state(), 1))
    visual = Observation.create({"session_id": world.session_id, "frame_id": "image-1"}, 1.1, "WORLD3D")
    world.add_evidence("position", {"x": 0, "y": 0}, visual)
    world.add_evidence("position", {"x": 1, "y": 1}, visual)
    belief = world.belief("position", 1.2)
    assert belief["source"] == "ADDON_TELEMETRY" and belief["value"]["x"] == .5
    assert len(belief["contradictions"]) == 1
    assert belief["supporting_evidence"] == [belief["evidence"][0]]
    assert belief["source_reliability"]["ADDON_TELEMETRY"] == 1
    assert world.belief("unseen", 2)["status"] == "UNKNOWN"


def test_diagnostic_beliefs_are_bounded_by_recency_not_insertion_order():
    world = WorldModel()
    world.ingest(Observation.create(state(), 1))
    # "position" is one of the earliest-inserted evidence keys. Flood the dict
    # with far more than the 200-key bound of newer visual-track keys.
    for index in range(300):
        visual = Observation.create({"session_id": world.session_id,
                                     "frame_id": f"image-{index}"},
                                    1.0 + index * .001, "WORLD3D")
        world.add_evidence(f"visual_track:{index}", {"x": index}, visual)
    # Then refresh the early-inserted key so it is the most recently updated.
    refresh = Observation.create({"session_id": world.session_id, "frame_id": "image-refresh"},
                                 2.0, "WORLD3D")
    world.add_evidence("position", {"x": 9, "y": 9}, refresh)
    beliefs = world.snapshot(2.5)["beliefs"]
    assert len(beliefs) <= 200
    # A naive islice(reversed(model.evidence)) would drop "position" because
    # setdefault keeps its original early insertion slot; recency must win.
    assert "position" in beliefs
    assert "visual_track:0" not in beliefs
    assert "visual_track:299" in beliefs


def test_foreign_visual_source_does_not_reset_session():
    world = WorldModel()
    world.ingest(Observation.create(state(), 1))
    assert not world.ingest(Observation.create({"session_id": "different"}, 2, "AI"))
    assert world.session_id == "test:player-1"


def test_supplemental_sensor_has_own_observation_and_does_not_mutate_addon_payload():
    world = WorldModel()
    addon = Observation.create(state(), 1)
    assert world.ingest(addon)
    vision = Observation.create({"session_id": world.session_id, "timestamp": 1,
                                 "frame_id": addon.correlation_id,
                                 "visual_candidates": [{"kind": "UNKNOWN"}]}, 1.1, "VISION")
    assert world.ingest(vision)
    assert "visual_candidates" not in world.addon_state
    assert world.state["visual_candidates"] == [{"kind": "UNKNOWN"}]
    belief = world.belief("visual_candidates", 1.1)
    assert belief["source"] == "VISION"
    assert world.history[-1].observation_id == vision.observation_id


def test_typed_world_query_returns_copies_and_filters_hypotheses():
    world = WorldModel()
    world.ingest(Observation.create(state(target={"guid": "g1"}, resource_observations=[
        {"id": "h1", "kind": "HERB", "confirmed": True},
        {"id": "h2", "kind": "HERB", "confirmed": False}]), 1))
    visual = Observation.create({"session_id": world.session_id, "frame_id": "v1",
        "visual_candidates": [{"track_id": "t1", "source": "WORLD3D", "kind": "UNKNOWN",
                               "confidence": .7}]}, 1.1, "WORLD3D")
    world.ingest(visual)
    target = world.query.target()
    target["guid"] = "changed"
    assert world.query.target()["guid"] == "g1"
    assert [item["id"] for item in world.query.resources("HERB")] == ["h1"]
    assert world.query.visual_tracks("WORLD3D", minimum_confidence=.65)[0]["track_id"] == "t1"


def test_world_graph_links_entities_quests_tracks_and_observations():
    world = WorldModel()
    payload = state(target={"guid": "Creature-0-1", "npc_id": 42, "name": "NPC",
                            "quest_role": "QUEST_GIVER", "quest_role_source": "API",
                            "quest_id": 7, "world_position": {"x": .3, "y": .4}},
                    active_quests=[{"quest_id": 7, "objectives": []}])
    addon = Observation.create(payload, 1)
    world.ingest(addon)
    visual = Observation.create({"session_id": world.session_id, "frame_id": addon.correlation_id,
        "visual_candidates": [{"track_id": "u1", "kind": "UNKNOWN", "confidence": .7}]},
        1.1, "WORLD3D")
    world.ingest(visual)
    assert world.query.relation(subject="entity:npc:42", predicate="related_to", object="quest:7")
    assert world.query.relation(subject="entity:npc:42", predicate="located_at")
    assert world.query.relation(subject="track:u1", predicate="observed_by")[0].status == "HYPOTHESIS"
    assert world.query.relation(subject="quest:7", predicate="observed_by")


def test_world_graph_observation_edges_collapse_per_subject_and_stay_bounded():
    # Live 2026-09-21: one observed_by edge per track per frame -> 2.47 M rows
    # for 10.9 k tracks. The edge is now per subject; the newest observation
    # is the object and `evidence` keeps the recent ones.
    world = WorldModel()
    world.ingest(Observation.create(state(), 1))
    for frame in range(30):
        visual = Observation.create({"session_id": world.session_id, "frame_id": f"v{frame}",
            "timestamp": 1+frame*.05,
            "visual_candidates": [{"track_id": "u1", "kind": "UNKNOWN", "confidence": .7}]},
            1.1+frame*.05, "WORLD3D")
        world.ingest(visual)
    edges = world.query.relation(subject="track:u1", predicate="observed_by")
    assert len(edges) == 1
    assert edges[0].object == f"observation:{visual.observation_id}"
    assert len(edges[0].evidence) == 20

    from wowbot.agent import world as world_module
    for index in range(world_module.MAX_RELATIONS+50):
        world.link(f"track:{index}", "occludes", f"track:{index+1}", world.latest)
    assert len(world.relations) == world_module.MAX_RELATIONS
    assert not world.query.relation(subject="track:0", predicate="occludes")  # least recently touched went first
    assert world.query.relation(subject=f"track:{world_module.MAX_RELATIONS+49}", predicate="occludes")


def test_world_graph_relations_are_persisted_with_session(tmp_path):
    memory = AgentMemory(tmp_path / "memory.sqlite3")
    world = WorldModel(memory.sensor_weight, memory.save_world_relation)
    world.ingest(Observation.create(state(target={"guid": "g", "npc_id": 42}), 1))
    rows = memory.world_relations(world.session_id)
    assert any(row["subject"] == "entity:npc:42" and row["predicate"] == "observed_by" for row in rows)
    assert memory.world_relations("other-session") == []


def test_independent_visual_sources_are_aggregated_without_losing_provenance():
    world = WorldModel()
    world.ingest(Observation.create(state(), 1))
    common = {"session_id": world.session_id, "timestamp": 1, "frame_id": "capture-1"}
    mini = Observation.create({**common, "visual_candidates": [{"source": "MINIMAP_CV"}]}, 1.1, "MINIMAP_CV")
    scene = Observation.create({**common, "visual_candidates": [{"source": "WORLD3D"}]}, 1.1, "WORLD3D")
    world.ingest(mini); world.ingest(scene)
    assert {item["source"] for item in world.state["visual_candidates"]} == {"MINIMAP_CV", "WORLD3D"}
    assert mini.correlation_id == scene.correlation_id
    assert {item.source for item in list(world.history)[-2:]} == {"MINIMAP_CV", "WORLD3D"}


def test_same_frame_visual_votes_are_one_correlated_evidence_group():
    world = WorldModel()
    world.ingest(Observation.create(state(), 1))
    common = {"session_id": world.session_id, "timestamp": 1, "frame_id": "same-capture"}
    world.ingest(Observation.create({**common, "marker": "A"}, 1.1, "MINIMAP_CV"))
    world.ingest(Observation.create({**common, "marker": "B"}, 1.1, "AI"))
    belief = world.belief("marker", 1.2)
    assert len(belief["evidence"]) == 1
    assert belief["correlation_groups"] == ["same-capture"]


def test_derived_addon_subsensor_does_not_double_count_parent_snapshot():
    world = WorldModel()
    addon = Observation.create(state(mouseover={"guid": "npc"}), 1)
    world.ingest(addon)
    derived = Observation.create({"session_id": world.session_id, "timestamp": 1,
        "frame_id": addon.correlation_id, "mouseover": {"guid": "npc"},
        "provenance": {"parent_observation_id": addon.observation_id,
                       "independence_group": addon.observation_id}}, 1.1, "MOUSEOVER")
    world.ingest(derived)
    belief = world.belief("mouseover", 1.2)
    assert len(belief["evidence"]) == 1
    assert belief["independence_groups"] == [addon.observation_id]


def test_session_change_cancels_and_unknown_data_stops():
    value, exe = agent("Menj oda", {"destination": {"map_id": 1609, "x": .5, "y": .4}})
    value.tick(state(), 1)
    assert value.pending
    result = value.tick(state(2, session_id="other"), 2)
    assert result["mode"] == "MANUAL" and value.pending is None
    value.set_mode(Mode.FULL_AI)
    suspended = value.tick(None, 9)
    assert suspended["mode"] == "FULL_AI"
    assert suspended["decision"]["reason"] == \
        "telemetry_suspended_waiting_for_stable_recovery"
    assert value.tick(None, 100)["mode"] == "MANUAL"


def test_old_detail_snapshot_does_not_disable_fast_control_liveness():
    world = WorldModel()
    world.ingest(Observation.create(state(50, state_age=21), 50))
    assert world.fresh(50)


def test_full_ai_reentry_does_not_inherit_manual_stationary_watchdog_time():
    value, _ = agent()
    value.tick(state(1), 1)
    value.set_mode(Mode.MANUAL)
    # Simulate a long human-controlled pause at the exact same location.
    value._stationary_position = (.5, .5)
    value._stationary_since = 1.
    value.set_mode(Mode.FULL_AI)
    value.tick(state(130), 130)
    assert value.last_decision["skill"] != "RECOVER"


def test_assist_plans_but_never_emits_input():
    value, exe = agent("Menj oda", {"destination": {"map_id": 1609, "x": .5, "y": .4}})
    value.set_mode(Mode.ASSIST)
    assert value.tick(state(), 1)["decision"]["skill"] == "MOVE"
    assert not exe.commands and value.pending is None


def test_move_turns_in_place_before_forward_when_heading_error_is_large():
    value, exe = agent("Menj oda", {"destination": {"map_id": 1609, "x": .7, "y": .5}})
    value.tick(state(), 1)
    assert exe.commands[0].binding in {"TURNLEFT", "TURNRIGHT"}
    assert exe.commands[0].simultaneous == ()
    assert exe.commands[0].duration <= .12
    assert value.goal.completed_steps == 0


def test_single_no_progress_observation_does_not_trigger_recovery():
    value, exe = agent("Menj oda", {"destination": {"map_id": 1609, "x": .5, "y": .4}})
    value.tick(state(), 1)
    value.tick(state(4), 4)
    assert value.pending is not None
    assert value.pending.proposal.skill == "MOVE"
    assert value.movement.phase.value == "NO_PROGRESS_YET"
    assert value.last_decision["skill"] == "MOVE"


def test_visual_obstacle_needs_three_independent_failed_moves_before_supported():
    navigator = AgentNavigator()
    destination = {"map_id": 1609, "x": .5, "y": .4}
    obstacle = {"source": "WORLD3D", "kind": "obstacle_candidate", "track_id": "rock",
                "confidence": .7, "stable_frames": 3, "x": .5}
    before = state(visual_candidates=[obstacle])
    assert navigator.observe_failed_move(before, before, destination, "o1", 1)["status"] == "HYPOTHESIS"
    assert navigator.observe_failed_move(before, before, destination, "o2", 2)["status"] == "HYPOTHESIS"
    claim = navigator.observe_failed_move(before, before, destination, "o3", 3)
    assert claim["status"] == "SUPPORTED" and len(claim["evidence"]) == 3
    world = WorldModel(); world.ingest(Observation.create(before, 3))
    assert not navigator.permits(world, destination, 3)
    navigator.observe_verified_move(before, state(4, position={"x": .5, "y": .499}), destination)
    assert navigator.snapshot(4)["supported_obstacles"] == []


def test_temporal_traversability_is_consumed_only_after_repeated_failed_moves():
    navigator = AgentNavigator()
    destination = {"map_id": 1609, "x": .5, "y": .4}
    local = {"schema": "WORLD3D_TRAVERSABILITY_V5", "sectors": [{
        "sector": "CENTER", "state": "BLOCKED", "obstacle_lifecycle": "CONFIRMED",
        "obstacle_confidence": .82, "evidence": ["motion_conditioned_collision_evidence"],
    }]}
    before = state(local_traversability=local)
    # A confirmed perception belief alone still does not block a destination.
    world = WorldModel(); world.ingest(Observation.create(before, 1))
    assert navigator.permits(world, destination, 1)
    for index in range(3):
        claim = navigator.observe_failed_move(before, before, destination, f"traversability-{index}", index)
    assert claim["status"] == "SUPPORTED"
    assert "traversability:CENTER" in claim["track_ids"]
    assert not navigator.permits(world, destination, 3)


def test_recovery_move_does_not_erase_blocked_forward_corridor_evidence():
    navigator = AgentNavigator()
    destination = {"map_id": 1609, "x": .5, "y": .4}
    obstacle = {"source": "WORLD3D", "kind": "obstacle_candidate", "track_id": "rock",
                "confidence": .7, "stable_frames": 3, "x": .5}
    before = state(visual_candidates=[obstacle])
    for index in range(3):
        navigator.observe_failed_move(before, before, destination, f"blocked-{index}", index)
    assert navigator.snapshot(3)["supported_obstacles"]

    recovered = state(4, position={"x": .501, "y": .5})
    navigator.observe_verified_move(before, recovered)  # RECOVER has no destination contract.
    assert navigator.snapshot(4)["supported_obstacles"]


def test_success_on_one_corridor_does_not_clear_another_corridor_claim():
    navigator = AgentNavigator()
    north = {"map_id": 1609, "x": .5, "y": .4}
    east = {"map_id": 1609, "x": .6, "y": .5}
    obstacle = {"source": "WORLD3D", "kind": "obstacle_candidate", "track_id": "rock",
                "confidence": .7, "stable_frames": 3, "x": .5}
    before = state(visual_candidates=[obstacle])
    for destination in (north, east):
        for index in range(3):
            navigator.observe_failed_move(before, before, destination,
                                           f"{destination['x']}:{destination['y']}:{index}", index)
    assert len(navigator.snapshot(3)["supported_obstacles"]) == 2

    moved_north = state(4, position={"x": .5, "y": .499})
    navigator.observe_verified_move(before, moved_north, north)
    claims = navigator.snapshot(4)["supported_obstacles"]
    assert len(claims) == 1
    assert claims[0]["path_key"] == navigator._path_key(before, east)


def test_untrusted_visual_topology_remains_a_hypothesis():
    navigator = AgentNavigator()
    observed = state(topology_observations=[{
        "type": "ENTRANCE", "geometry": {"x": .2, "y": .3},
        "source": "VISION", "confidence": .9,
    }])
    for index in range(5):
        navigator.observe_topology(observed, f"vision-{index}", index)
    feature = navigator.snapshot(6)["topology"][0]
    assert feature["status"] == "HYPOTHESIS"
    assert len(feature["evidence"]) == 5


def test_trusted_topology_requires_repeated_evidence_or_confirmation():
    navigator = AgentNavigator()
    observed = state(topology_observations=[{
        "type": "QUEST_HUB", "geometry": {"x": .4, "y": .6},
        "source": "ADDON_TELEMETRY", "confidence": .8,
    }])
    navigator.observe_topology(observed, "addon-1", 1)
    navigator.observe_topology(observed, "addon-2", 2)
    assert navigator.snapshot(2)["topology"][0]["status"] == "HYPOTHESIS"
    changed = navigator.observe_topology(observed, "addon-3", 3)
    assert changed[0]["status"] == "SUPPORTED"

    confirmed = state(topology_observations=[{
        "type": "PORTAL", "geometry": {"x": .7, "y": .1},
        "source": "USER_CONFIG", "confirmed": True,
    }])
    navigator.observe_topology(confirmed, "user-1", 4)
    assert any(item["type"] == "PORTAL" and item["status"] == "CONFIRMED"
               for item in navigator.snapshot(4)["topology"])


def test_verified_movement_creates_supported_traversed_segment():
    navigator = AgentNavigator()
    before = state(position={"x": .5, "y": .5}, frame_id="before", monotonic_time=1)
    after = state(position={"x": .5, "y": .499}, frame_id="after", monotonic_time=2)
    navigator.observe_verified_move(before, after)
    topology = navigator.snapshot(2)["topology"]
    assert topology[0]["type"] == "TRAVERSED_SEGMENT"
    assert topology[0]["status"] == "SUPPORTED"
    assert topology[0]["evidence"] == ("before", "after")


def test_blocked_primary_move_uses_an_available_alternative():
    value, _ = agent()
    first = {"quest_id": 1, "is_complete": True, "map_id": 1609, "x": .4, "y": .4}
    second = {"quest_id": 2, "is_complete": False, "map_id": 1609, "x": .6, "y": .6}
    value.navigator.blocked[(1609, .4, .4)] = 100
    value.tick(state(quest_locations=[first, second]), 1)
    assert value.pending and value.pending.proposal.skill == "MOVE"
    assert value.pending.proposal.parameters["quest_id"] == 2


def test_move_sideways_or_farther_is_not_verified_as_progress():
    value, _ = agent("Menj oda", {"destination": {"map_id": 1609, "x": .5, "y": .4}})
    value.tick(state(), 1)
    value.tick(state(2, position={"x": .501, "y": .501}, orientation=.2), 2)
    assert value.pending is not None and value.goal.completed_steps == 0
    value.tick(state(4, position={"x": .501, "y": .501}, orientation=.2), 4)
    assert value.pending is not None
    assert value.movement.phase.value in {"STEERING", "NO_PROGRESS_YET", "CANDIDATE_STUCK"}
    assert not value.world.verifications  # The high-level REACH attempt is still active.


def test_arrival_is_not_quest_completion():
    value, exe = agent()
    quest = {"quest_id": 1, "is_complete": False, "waypoint": {"map_id": 1609, "x": .5, "y": .5}, "objectives": [{"type": "TALK", "current": 0}]}
    value.tick(state(active_quests=[quest]), 1)
    assert value.goal.status == "ACTIVE" and value.goal.completed_steps == 0
    assert exe.commands and exe.commands[0].kind == "CAMERA_PAN"


def test_live_action_budget_does_not_split_one_persistent_reach_into_inputs():
    value, exe = agent("Menj oda", {"destination": {"map_id": 1609, "x": .5, "y": .4}})
    value.action_budget = 1
    value.tick(state(), 1)
    action_id = value.pending.action_id
    value.tick(state(2, position={"x": .5, "y": .499}), 2)
    assert value.mode == Mode.FULL_AI and len(exe.commands) == 2
    assert value.pending.action_id == action_id


def test_agent_episode_links_action_verification_and_goal_result(tmp_path):
    memory = AgentMemory(tmp_path / "memory.sqlite3")
    value, _ = agent("Menj oda", {"destination": {"map_id": 1609, "x": .5, "y": .4}}, memory=memory)
    value.tick(state(), 1)
    episode_id = value.episode_id
    value.tick(state(2, position={"x": .5, "y": .4}), 2)
    episode = memory.episode(episode_id)
    assert value.goal.status == "COMPLETED" and value.episode_id is None
    assert episode["status"] == "SUCCESS"
    assert [step["kind"] for step in episode["steps"]] == ["ACTION_INTENT", "VERIFICATION"]
    assert episode["steps"][1]["payload"]["skill"] == "MOVE"


def test_loot_from_defeated_enemy_text_does_not_start_blind_tab_acquisition():
    value, exe = agent()
    objective = {"description": "0/6 First Aid Kits recovered from defeated Murlocs", "raw_type": "item", "type": "COLLECT"}
    value.tick(state(active_quests=[{"quest_id": 9000, "objectives": [objective]}]), 1)
    assert value.last_decision["skill"] != "ACQUIRE_TARGET"
    assert not any(command.binding == "TARGETNEARESTENEMY" for command in exe.commands)


def test_late_attackable_target_promotes_acquire_commitment_after_verify_timeout():
    world = WorldModel()
    world.ingest(Observation.create(state(), 1.))
    goal = Goal.parse("Questelj", 1.)
    loop = AutonomousLoop()
    acquire = Proposal.make("ACQUIRE_TARGET", "nearby hostile")
    loop._commit(acquire, goal, world, 1.)

    loop.outcome(acquire, False, "expected_observation_missing", world, 3.01)
    assert loop.commitment and loop.commitment.kind == "ACQUIRE"
    assert loop.phase == RuntimePhase.ACQUIRING

    world.ingest(Observation.create(state(
        3.1, target={"guid": "Creature-Murloc", "name": "Murloc Watershaper",
                     "attackable": True, "dead": False},
        actionbar=[{"id": 1, "kind": "spell", "is_harmful": True,
                    "is_usable": True, "in_range": True}]), 3.1))
    combat = Proposal.make("COMBAT", "quest target", {"guid": "Creature-Murloc"})
    chosen = loop.choose([combat], combat, goal, world, 3.1)

    assert chosen.skill == "COMBAT"
    assert loop.commitment.kind == "TARGET"
    assert loop.commitment.target_guid == "Creature-Murloc"
    assert loop.phase == RuntimePhase.COMBAT


def test_combat_subject_parser_is_generic_and_word_bounded():
    from wowbot.agent.quest_semantics import target_matches_objective
    assert target_matches_objective({"name": "Murloc Watershaper"}, {"description": "Supplies from defeated Murlocs"})
    assert target_matches_objective({"name": "Cave Spider"}, {"description": "0/3 Spider slain"})
    assert not target_matches_objective({"name": "Pirate"}, {"description": "0/3 Rats slain"})
    assert not target_matches_objective({"name": "Rabbit"}, {"description": "Supplies from defeated Murlocs"})


def test_quest_accept_requires_that_quest_not_just_ui_change():
    value, exe = agent()
    ui = {"open": True, "action": "ACCEPT", "quest_id": 42, "x": .3, "y": .3}
    value.tick(state(quest_ui=ui), 1)
    value.tick(state(2, quest_ui={**ui, "x": .4}), 2)
    assert value.pending and value.goal.completed_steps == 0
    value.tick(state(3, active_quests=[{"quest_id": 42, "objectives": []}]), 3)
    assert value.goal.completed_steps == 1


def test_open_accept_preempts_a_committed_visual_approach():
    """An exact dialog action ends approach ownership immediately.

    This is the Jaina regression: VISUAL_APPROACH used to outrank ACCEPT by
    raw priority and could be selected forever after it had already opened
    the quest frame.
    """
    value, executor = agent()
    guid = "Creature-Jaina"
    value.autonomy._commit(Proposal.make("VISUAL_APPROACH", "test", {"guid": guid}),
                            value.goal, value.world, 0.)
    ui = {"open": True, "action": "ACCEPT", "quest_id": 55122, "x": .035, "y": .43}
    value.tick(state(target={"guid": guid, "attackable": False, "name": "Lady Jaina Proudmoore"},
                     quest_ui=ui), 1.)
    assert value.last_decision["skill"] == "QUEST_DIALOG"
    assert value.pending and value.pending.proposal.skill == "QUEST_DIALOG"
    assert any(command.kind == "CLICK" and command.x == .035 and command.y == .43
               for command in executor.commands)


def test_unaddressable_open_quest_list_preempts_visual_approach_without_clicking():
    """A modal quest list with no verified row point must fail closed."""
    value, executor = agent()
    guid = "Creature-Austin"
    value.autonomy._commit(Proposal.make("VISUAL_APPROACH", "test", {"guid": guid}),
                            value.goal, value.world, 0.)
    ui = {"open": True, "action": "", "entries": [
        {"kind": "AVAILABLE", "quest_id": 55186, "title": "Down with the Quilboar",
         "x": 0, "y": 0, "acceptable": True},
        {"kind": "AVAILABLE", "quest_id": 55184, "title": "Quilboar Shadow Magic",
         "x": 0, "y": 0, "acceptable": True},
    ]}
    value.tick(state(target={"guid": guid, "attackable": False, "name": "Austin Huxworth"},
                     quest_ui=ui), 1.)
    assert value.last_decision["skill"] == "WAIT"
    assert value.last_decision["reason"] == "A nyitott questlista soraihoz nincs hiteles kattintási koordináta"
    assert executor.commands == []


def test_quest_accept_waits_for_delayed_paged_quest_log_ground_truth():
    value, exe = agent()
    ui = {"open": True, "action": "ACCEPT", "quest_id": 42, "x": .3, "y": .3}
    value.tick(state(quest_ui=ui), 1)
    value.tick(state(7, quest_ui={"open": False}), 7)
    assert value.pending and value.goal.failures == 0
    value.tick(state(8, active_quests=[{"quest_id": 42, "objectives": []}]), 8)
    assert value.pending is None
    assert value.goal.completed_steps == 1
    assert value.last_result["outcome"] == "SUCCESS"


def test_attempt_to_dict_references_baseline_instead_of_copying_world_state():
    from wowbot.agent.models import Attempt, Prediction
    baseline = state(1., world3d_batch={"tracks": [{"id": i} for i in range(500)]})
    attempt = Attempt("action-1", Proposal.make("INTERACT", "test", {"guid": "g"}), baseline,
                      "obs-1", 1., 8., (), Prediction("p-1", "action-1", "dialog", 1., 8., "obs-1"))
    serialized = attempt.to_dict()
    # The ~300 KB world-state copy was 80% of the live 4.4 MB status JSON and
    # was also written per action into the structured log and SQLite episode
    # steps; only the durable observation reference belongs in diagnostics.
    assert "baseline" not in serialized
    assert serialized["baseline_observation_id"] == "obs-1"
    assert attempt.baseline is baseline  # verifiers still read the live object


def test_status_throttles_large_world_projection_but_keeps_control_fields_live():
    value, _ = agent()
    calls = []
    original = value.world.snapshot

    def measured(now):
        calls.append(now)
        return original(now)

    value.world.snapshot = measured
    value.last_decision = {"skill": "WAIT", "reason": "first"}
    first = value.status(1.)
    value.last_decision = {"skill": "COMBAT", "reason": "second"}
    second = value.status(1.05)
    third = value.status(2.01)

    assert len(calls) == 2
    assert first["world"] is second["world"]
    assert second["decision"] == {"skill": "COMBAT", "reason": "second"}
    assert third["world"] is not second["world"]


def test_closed_partial_quest_ui_does_not_falsely_verify_interaction():
    registry = SkillRegistry()
    baseline = state(1., target={"guid": "Creature-Jaina", "attackable": False})
    current = world = WorldModel()
    current.ingest(Observation.create(state(2., target={"guid": "Creature-Jaina", "attackable": False},
        quest_ui={"open": False, "entries": []}), 2.))
    attempt = SimpleNamespace(
        observation_id="baseline", deadline=8., started_at=1., baseline=baseline,
        proposal=Proposal.make("INTERACT", "test", {"guid": "Creature-Jaina"}), commands=())
    outcome, reason = registry.verify(attempt, world, 2.)
    assert outcome == Outcome.PENDING
    assert reason == "awaiting_expected_change"


def test_open_quest_ui_verifies_interaction():
    registry = SkillRegistry()
    baseline = state(1., target={"guid": "Creature-Jaina", "attackable": False},
                     quest_ui={"open": False})
    current = WorldModel()
    current.ingest(Observation.create(state(2., target={"guid": "Creature-Jaina", "attackable": False},
        quest_ui={"open": True, "action": "ACCEPT", "quest_id": 55122,
                  "x": .0346, "y": .4475}), 2.))
    attempt = SimpleNamespace(
        observation_id="baseline", deadline=8., started_at=1., baseline=baseline,
        proposal=Proposal.make("INTERACT", "test", {"guid": "Creature-Jaina"}), commands=())
    assert registry.verify(attempt, current, 2.) == (Outcome.SUCCESS, "expected_observation_verified")


def test_quest_removal_is_not_turnin():
    value, exe = agent()
    q = {"quest_id": 42, "is_complete": True, "objectives": []}
    ui = {"open": True, "action": "COMPLETE", "quest_id": 42, "x": .3, "y": .3}
    value.tick(state(active_quests=[q], quest_ui=ui), 1)
    value.tick(state(2), 2)
    assert value.goal.completed_steps == 0
    value.tick(state(3, event_sequence=1, events=[{"sequence": 1, "event_type": "QUEST_TURNED_IN", "payload": {"quest_id": 42}}]), 3)
    assert value.goal.completed_steps == 1


def test_loot_needs_item_or_objective_evidence():
    value, exe = agent()
    target = {"guid": "creature1", "dead": True, "attackable": True}
    value.tick(state(target=target, loot_pending=True), 1)
    assert value.last_decision["skill"] == "LOOT"
    value.tick(state(2, target=target, loot_pending=True, events=[{"sequence": 1, "event_type": "LOOT_WINDOW_OPENED"}]), 2)
    assert value.pending and value.goal.completed_steps == 0
    value.tick(state(3, target=target, loot_pending=True, inventory={"items": [{"item_id": 3, "count": 1}], "free_slots": 9}), 3)
    assert value.goal.completed_steps == 1 and value.last_decision["skill"] != "LOOT"
    value.tick(state(65, target=target, loot_pending=True,
                     inventory={"items": [{"item_id": 3, "count": 1}], "free_slots": 9}), 65)
    assert value.last_decision["skill"] != "LOOT"


def test_loot_range_recovery_keeps_the_same_canonical_attempt_until_corpse_arrival():
    value, exe = agent()
    corpse = {"guid": "corpse-range", "dead": True, "attackable": True,
              "world_position": {"x": 110., "y": 100., "z": 3., "instance_id": 2175}}
    player = {"x": 100., "y": 100., "z": 3., "instance_id": 2175}
    value.tick(state(1, target=corpse, loot_pending=True, player_world_position=player), 1.)
    assert value.pending and value.pending.proposal.skill == "LOOT"
    action_id = value.pending.action_id

    value.tick(state(2, target=corpse, loot_pending=True, player_world_position=player,
                     ui_error="You need to be closer to loot that target."), 2.)
    assert value.pending and value.pending.action_id == action_id
    assert value.active_skill.state.skill_context["loot"]["approach_request"]["kind"] == "WORLD_CORPSE"
    assert exe.commands[-1].binding == "MOVEFORWARD"

    value.tick(state(3, target=corpse, loot_pending=True,
                     player_world_position={**player, "x": 107.}), 3.)
    assert value.pending and value.pending.action_id == action_id
    assert exe.commands[-1].binding == "INTERACTTARGET"


def test_compact_fast_loot_baseline_preserves_existing_inventory():
    value, _ = agent()
    corpse = {"guid": "creature-fast", "dead": True, "attackable": True}
    full = state(1, target=corpse, loot_pending=True,
                 inventory={"items": [{"item_id": 3, "count": 1}], "free_slots": 9},
                 transport_kind="STATE", telemetry_lane="FULL_STATE")
    value.world.ingest(Observation.create(full, 1))
    compact = {
        "session_id": full["session_id"], "timestamp": 2., "monotonic_time": 2.,
        "frame_id": "fast:1", "transport_kind": "FAST", "telemetry_lane": "FAST_STATE",
        "fast_sequence": 1, "state_age": 0., "player_present": True,
        "target": corpse, "is_dead": False, "is_in_combat": False,
    }
    value.tick(compact, 2.)
    assert value.pending and value.pending.proposal.skill == "LOOT"
    assert value.pending.baseline["inventory"]["items"] == [{"item_id": 3, "count": 1}]

    unchanged = {**compact, "timestamp": 2.2, "monotonic_time": 2.2,
                 "frame_id": "fast:2", "fast_sequence": 2}
    value.tick(unchanged, 2.2)
    assert value.pending and value.pending.proposal.skill == "LOOT"
    assert value.last_result.get("skill") != "LOOT"


def test_loot_rejects_explicit_event_from_another_source():
    value, _ = agent()
    target = {"guid": "creature1", "dead": True, "attackable": True}
    value.tick(state(target=target, loot_pending=True), 1)
    wrong = {"sequence": 1, "event_type": "LOOT_RECEIVED", "payload": {"source_guid": "other"}}
    value.tick(state(2, target=target, loot_pending=True, event_sequence=1, events=[wrong]), 2)
    assert value.pending and value.goal.completed_steps == 0
    # LOOT waits up to 6 s for the paged loot events (live 2026-10-02).
    value.tick(state(4, target=target, loot_pending=True, event_sequence=1, events=[wrong]), 4)
    assert value.pending and value.goal.completed_steps == 0
    value.tick(state(8, target=target, loot_pending=True, event_sequence=1, events=[wrong]), 8)
    assert value.last_result["outcome"] == "FAILURE"


def test_corpse_tooltip_event_preserves_anchor_and_loots_before_new_target():
    value, exe = agent()
    guid = "Creature-0-1-2-3-150228-00000001"
    quest = {"quest_id": 55122, "objectives": [{
        "raw_type": "item", "type": "COLLECT",
        "description": "0/6 First Aid Kits recovered from defeated Murlocs",
        "current": 0, "required": 6,
    }]}
    target = {"guid": guid, "npc_id": 150228, "name": "Murloc Spearhunter",
              "health": 10, "attackable": True, "dead": False}
    spell = {"kind": "spell", "id": 1464, "action": "ACTIONBUTTON1",
             "is_usable": True, "is_harmful": True, "in_range": True,
             "cooldown_remaining": 0}
    value.tick(state(active_quests=[quest], target=target, is_in_combat=True,
                     actionbar=[spell]), 1)
    assert value.pending and value.pending.proposal.skill == "COMBAT"

    corpse_event = {"sequence": 1, "timestamp": 2, "event_type": "MOUSEOVER_CHANGED", "payload": {
        "tooltip": "Murloc Spearhunter ~ Level 2 ~ Corpse ~ Murloc Mania",
        "tooltip_data": {"guid": guid, "unit_guid": guid}}}
    value.tick(state(2, active_quests=[quest], target=None, is_in_combat=False,
                     actionbar=[spell], event_sequence=1, events=[corpse_event],
                     cursor_position={"nx": .61, "ny": .42}, cursor_sample_time=2), 2)

    assert value.last_result["skill"] == "COMBAT"
    assert value.last_result["outcome"] == "SUCCESS"
    assert value.pending and value.pending.proposal.skill == "LOOT"
    assert value.pending.proposal.parameters["corpse_anchor"] is True
    assert value.world.state["confirmed_corpse_anchors"][0]["guid"] == guid
    assert exe.commands[-1].kind == "HOVER"   # hover-confirm before the right-click

    loot_event = {"sequence": 2, "timestamp": 3, "event_type": "LOOT_RECEIVED",
                  "payload": {"source_guid": guid}}
    value.tick(state(3, active_quests=[quest], target=None, event_sequence=2,
                     events=[corpse_event, loot_event],
                     cursor_position={"nx": .61, "ny": .42}, cursor_sample_time=3,
                     inventory={"items": [{"item_id": 168410, "count": 1}],
                                "free_slots": 9}), 3)
    assert value.last_result["skill"] == "LOOT"
    assert value.last_result["outcome"] == "SUCCESS"
    assert value.world.state["confirmed_corpse_anchors"] == []


def test_looted_corpse_is_not_readded_by_later_mouseover():
    world = WorldModel()
    guid = "Creature-0-1-2-3-150228-00000010"
    corpse = {"sequence": 1, "timestamp": 1, "event_type": "MOUSEOVER_CHANGED",
              "payload": {"tooltip": "Murloc ~ Corpse",
                          "tooltip_data": {"guid": guid, "lootable": True}}}
    world.ingest(Observation.create(state(1, event_sequence=1, events=[corpse],
        mouseover={"guid": guid, "is_dead": True},
        cursor_position={"nx": .5, "ny": .4}, cursor_sample_time=1), 1))
    assert world.state["confirmed_corpse_anchors"][0]["guid"] == guid

    loot = {"sequence": 2, "timestamp": 2, "event_type": "LOOT_RECEIVED",
            "payload": {"message": "You receive loot: First Aid Kit"}}
    world.ingest(Observation.create(state(2, event_sequence=2, events=[corpse, loot],
        mouseover={"guid": guid, "is_dead": True},
        cursor_position={"nx": .5, "ny": .4}, cursor_sample_time=2), 2))
    assert world.state["confirmed_corpse_anchors"] == []

    later = {"sequence": 3, "timestamp": 3, "event_type": "MOUSEOVER_CHANGED",
             "payload": {"tooltip": "Murloc ~ Corpse",
                         "tooltip_data": {"guid": guid, "lootable": True}}}
    world.ingest(Observation.create(state(3, event_sequence=3, events=[later],
        mouseover={"guid": guid, "is_dead": True},
        cursor_position={"nx": .5, "ny": .4}, cursor_sample_time=3), 3))
    assert world.state["confirmed_corpse_anchors"] == []


def test_multiple_sourceless_loot_items_do_not_retire_multiple_corpses():
    world = WorldModel()
    first = "Creature-0-1-2-3-150228-00000011"
    second = "Creature-0-1-2-3-150228-00000012"
    world.session_id = "test:player-1"
    world.last_received = 1
    world.corpse_anchors = {
        first: {"guid": first, "observed_at": 1},
        second: {"guid": second, "observed_at": 2},
    }
    observation = Observation.create(state(3), 3)
    world._project_corpse_event(
        {"event_type": "LOOT_RECEIVED", "payload": {"message": "item one"}},
        observation.payload, observation)
    world._project_corpse_event(
        {"event_type": "LOOT_RECEIVED", "payload": {"message": "item two"}},
        observation.payload, observation)
    assert second in world.looted_corpse_guids
    assert first in world.corpse_anchors


def test_targeted_loot_does_not_toggle_to_last_target_first():
    value, exe = agent()
    target = {"guid": "Creature-current", "dead": True, "attackable": True}
    value.tick(state(target=target, loot_pending=True), 1)
    assert value.pending and value.pending.proposal.skill == "LOOT"
    assert [command.binding for command in exe.commands] == ["INTERACTTARGET"]


def test_unrelated_corpse_event_does_not_confirm_current_combat_target():
    value, _ = agent()
    target = {"guid": "Creature-current", "health": 10, "attackable": True}
    spell = {"kind": "spell", "id": 1, "action": "ACTIONBUTTON1",
             "is_usable": True, "is_harmful": True, "in_range": True,
             "cooldown_remaining": 0}
    value.tick(state(target=target, is_in_combat=True, actionbar=[spell]), 1)
    action_id = value.pending.action_id
    unrelated = {"sequence": 1, "timestamp": 2, "event_type": "MOUSEOVER_CHANGED", "payload": {
        "tooltip": "Other Murloc ~ Corpse",
        "tooltip_data": {"guid": "Creature-other"}}}
    # Still fighting (leaving combat would itself end the fight, user rule
    # 2026-10-01).  With the selection gone while in combat another attacker
    # is assumed (user: acquire it, loot only after combat), so the agent may
    # move on to ACQUIRE_TARGET; the unrelated corpse must never confirm a
    # kill or create a loot anchor.
    value.tick(state(2, target=None, actionbar=[spell], event_sequence=1,
                     events=[unrelated], cursor_position={"nx": .6, "ny": .4},
                     cursor_sample_time=2, is_in_combat=True), 2)
    assert value.last_result.get("outcome") != "SUCCESS"
    assert not value.world.state.get("confirmed_corpse_anchors")


def test_unowned_live_dead_mouseover_does_not_create_loot_anchor():
    world = WorldModel()
    guid = "Creature-0-1-2-3-150228-00000009"
    payload = state(5, mouseover={"guid": guid, "name": "Murloc Spearhunter",
                                 "is_player": False, "is_dead": True},
                    cursor_position={"nx": .44, "ny": .37}, cursor_sample_time=5)
    assert world.ingest(Observation.create(payload, 5))
    assert world.state["confirmed_corpse_anchors"] == []


def test_own_combat_dead_mouseover_creates_corpse_anchor_without_event_page():
    world = WorldModel()
    guid = "Creature-0-1-2-3-150228-00000009"
    world.ingest(Observation.create(state(
        4, target={"guid": guid, "attackable": True, "dead": False},
        is_in_combat=True), 4))
    world.mark_combat_kill(guid, 4.5)
    payload = state(5, mouseover={"guid": guid, "name": "Murloc Spearhunter",
                                 "is_player": False, "is_dead": True},
                    cursor_position={"nx": .44, "ny": .37}, cursor_sample_time=5)
    assert world.ingest(Observation.create(payload, 5))
    corpse = world.state["confirmed_corpse_anchors"][0]
    assert corpse["guid"] == guid
    assert (corpse["x"], corpse["y"]) == (.44, .37)
    assert corpse["source"] == "ADDON_DEAD_MOUSEOVER"
    assert corpse["ownership_confirmed"] is True


def test_object_use_requires_quest_credit_not_only_object_used_event():
    value, _ = agent()
    quest = {"quest_id": 10, "objectives": [{"type": "USE_ITEM", "object_id": 77,
                                               "current": 0, "required": 1}]}
    value.tick(state(active_quests=[quest], mouseover={"object_id": 77},
                     cursor_position={"nx": .4, "ny": .6}), 1)
    assert value.pending and value.pending.proposal.skill == "OBJECT_USE"
    event = {"sequence": 1, "event_type": "OBJECT_USED", "payload": {"object_id": 77}}
    value.tick(state(2, active_quests=[quest], mouseover={"object_id": 77},
                     cursor_position={"nx": .4, "ny": .6}, event_sequence=1, events=[event]), 2)
    assert value.pending and value.last_result.get("outcome") != "SUCCESS"
    progressed = {"quest_id": 10, "objectives": [{**quest["objectives"][0], "current": 1}]}
    value.tick(state(3, active_quests=[progressed], mouseover={"object_id": 77},
                     cursor_position={"nx": .4, "ny": .6}, event_sequence=1, events=[event]), 3)
    assert value.last_result["outcome"] == "SUCCESS" and value.goal.completed_steps == 1


def test_combat_can_verify_linked_objective_progress_after_target_disappears():
    value, _ = agent()
    quest = {"quest_id": 20, "objectives": [{"raw_type": "monster", "target_npc_id": 5,
                                               "current": 0, "required": 1}]}
    target = {"guid": "mob", "npc_id": 5, "health": 10, "attackable": True}
    spell = {"kind": "spell", "id": 1, "action": "ACTIONBUTTON1", "is_usable": True,
             "is_harmful": True, "in_range": True, "cooldown_remaining": 0}
    value.tick(state(active_quests=[quest], target=target, is_in_combat=True, actionbar=[spell]), 1)
    progressed = {"quest_id": 20, "objectives": [{**quest["objectives"][0], "current": 1}]}
    value.tick(state(2, active_quests=[progressed], target=None, actionbar=[spell]), 2)
    assert value.last_result["skill"] == "COMBAT"
    assert value.last_result["outcome"] == "SUCCESS"


def test_secret_cooldown_is_not_assumed_ready():
    value, exe = agent()
    target = {"guid": "creature1", "health": 10, "attackable": True}
    spell = {"kind": "spell", "id": 1, "action": "ACTIONBUTTON1", "is_usable": True, "is_harmful": True}
    value.tick(state(target=target, is_in_combat=True, actionbar=[spell]), 1)
    assert not exe.commands
    value.tick(state(2, target=target, is_in_combat=True, actionbar=[{**spell, "cooldown_remaining": 0}]), 2)
    assert value.last_decision["skill"] == "DEFEND" and exe.commands


def test_combat_facing_error_half_turns_then_retries_ability_without_stale_repeat(tmp_path):
    bindings = BindingsCache(binding_file(tmp_path))
    registry = SkillRegistry(bindings)
    world = WorldModel()
    target = {"guid": "mob", "health": 10, "attackable": True, "dead": False}
    spell = {"kind": "spell", "id": 1, "action": "ACTIONBUTTON1",
             "is_usable": True, "is_harmful": True, "in_range": True,
             "cooldown_remaining": 0}
    world.ingest(Observation.create(state(1, target=target, is_in_combat=True,
        actionbar=[spell], ui_error="You are facing the wrong way!"), 1))
    proposal = Proposal.make("DEFEND", "test", {"guid": "mob"})

    first = registry.commands(proposal, world)
    assert [command.binding for command in first] == [
        "TURNLEFT", "TURNLEFT", "TURNLEFT", "ACTIONBUTTON1"]
    assert all(command.duration <= .35 for command in first)

    # The addon retains an error string for three seconds. The immediately
    # following combat decision must try the ability, not turn another pi.
    world.ingest(Observation.create(state(1.5, target=target, is_in_combat=True,
        actionbar=[spell], ui_error="You are facing the wrong way!"), 1.5))
    second = registry.commands(proposal, world)
    assert [command.binding for command in second] == ["ACTIONBUTTON1"]


def test_unrelated_hostile_not_proactively_attacked():
    value, exe = agent()
    target = {"guid": "creature1", "name": "Rabbit", "attackable": True}
    spell = {"kind": "spell", "id": 1, "action": "ACTIONBUTTON1", "is_usable": True, "is_harmful": True, "cooldown_remaining": 0}
    value.tick(state(target=target, actionbar=[spell]), 1)
    assert not exe.commands


def test_learning_requires_repeated_verified_success(tmp_path):
    memory = AgentMemory(tmp_path / "memory.sqlite3")
    memory.learn("map:quest", "MOVE", True)
    assert memory.reliability("map:quest", "MOVE")[1] == "EPISODIC"
    for _ in range(5): memory.learn("map:quest", "MOVE", True)
    assert memory.reliability("map:quest", "MOVE")[1] == "LEARNED"
    assert memory.reliability("other-map:quest", "MOVE")[1] == "EPISODIC"


def test_verified_inspection_updates_sensor_calibration(tmp_path):
    memory = AgentMemory(tmp_path / "memory.sqlite3")
    value, _ = agent(memory=memory)
    marker = {"kind": "quest_giver", "detector_kind": "quest_giver", "source": "MINIMAP_CV",
              "track_id": "m:1", "confidence": .9, "x": .4, "y": .5}
    value.tick(state(visual_candidates=[marker]), 1)
    assert value.pending and value.pending.proposal.skill == "INSPECT"
    value.tick(state(2, visual_candidates=[marker], cursor_position={"nx": .4, "ny": .5},
                     mouseover={"guid": "npc"}), 2)
    profiles = memory.sensor_health(value.world.state)
    assert any(item["source"] == "MINIMAP_CV" and item["detector"] == "*"
               and item["samples"] == 1 for item in profiles)


def test_verified_inspection_calibrates_detector_only_against_semantic_label(tmp_path):
    memory = AgentMemory(tmp_path / "memory.sqlite3")
    value, _ = agent(memory=memory)
    marker = {"kind": "quest_giver", "detector_kind": "quest_giver", "source": "MINIMAP_CV",
              "track_id": "m:1", "confidence": .9, "x": .4, "y": .5}
    value.tick(state(visual_candidates=[marker]), 1)
    value.tick(state(2, visual_candidates=[marker], cursor_position={"nx": .4, "ny": .5},
                     mouseover={"guid": "npc", "quest_role": "QUEST_GIVER"}), 2)
    profile = memory.sensor_profile("MINIMAP_CV", "quest_giver",
                                    memory.learning_context(value.world.state, "SENSOR"))
    assert profile["samples"] == 1 and profile["historical_precision"] > .5


def test_npc_identity_does_not_get_player_coordinates():
    world = WorldModel()
    world.ingest(Observation.create(state(target={"guid": "npc", "name": "Henry"}), 1))
    assert "locations" not in world.entities["npc"]
    assert world.entity_locations.get("npc", []) == []


def quest_npc_boxes(x, y, track="WORLD3D:jaina"):
    """The hovered NPC's box with a "!" box over its head (live geometry).

    With no active quest only such a quest NPC is selected (user 2026-10-02).
    """
    body = {"source": "WORLD3D", "track_id": track, "detector_kind": "unknown_subject_candidate",
            "kind": "unknown_subject_candidate", "x": x, "y": y, "confidence": .8,
            "bbox": {"left": 500, "top": 200, "right": 560, "bottom": 360,
                     "coordinate_space": "CLIENT_PIXELS"}}
    bang = {"source": "WORLD3D", "track_id": track + ":bang", "detector_kind": "unknown_symbol_candidate",
            "kind": "unknown_symbol_candidate", "candidate_labels": ["learned_symbol_like"],
            "x": x, "y": y + .1, "confidence": .7,
            "bbox": {"left": 520, "top": 160, "right": 540, "bottom": 195,
                     "coordinate_space": "CLIENT_PIXELS"}}
    return [body, bang]


def test_confirmed_friendly_mouseover_is_targeted_before_opening_map():
    value, _ = agent()
    mouse = {"guid": "jaina", "npc_id": 156626, "name": "Lady Jaina Proudmoore",
             "unit_type": "NPC", "is_attackable": False}
    value.tick(state(mouseover=mouse, cursor_position={"nx": .5, "ny": .72},
                     world_map_open=False, active_quests=[],
                     visual_candidates=quest_npc_boxes(.5, .72)), 1)
    assert value.last_decision["skill"] == "TARGET"
    assert value.pending and value.pending.proposal.parameters["guid"] == "jaina"


def test_ground_truth_mouseover_target_beats_new_unknown_world3d_inspection():
    value, _ = agent()
    mouse = {"guid": "Creature-0-1-2-3-156626-4", "npc_id": 156626,
             "name": "Lady Jaina Proudmoore", "unit_type": "NPC",
             "is_attackable": False, "identity_source": "WOW_API_MOUSEOVER"}
    unknown = {
        "source": "WORLD3D", "track_id": "WORLD3D:new-unknown",
        "kind": "unknown_subject_probe", "detector_kind": "unknown_subject_probe",
        "stable_frames": 8, "confidence": .99, "x": .22, "y": .48,
        "visual_relations": [{"type": "ABOVE", "belief": "SUPPORTED"}],
        "appearance": {"residual_motion": .9, "body_geometry": .9,
                       "foreground_contrast": .9, "screen_center_relevance": .8,
                       "static_scene_score": 0.0},
    }
    payload = state(1, mouseover=mouse, cursor_position={"nx": .53, "ny": .66},
                    cursor_sample_time=1, mouseover_sample_time=1,
                    world_map_open=False, active_quests=[],
                    visual_candidates=[unknown, *quest_npc_boxes(.53, .66)])

    # Reproduce the live failure shape: a high-value UNKNOWN inspection exists
    # in the same planning cycle as fresh addon ground-truth mouseover identity.
    value.tick(payload, 1)

    assert value.last_decision["skill"] == "TARGET"
    assert value.pending and value.pending.proposal.parameters["guid"] == mouse["guid"]
    assert value.pending.proposal.parameters["ground_truth_handoff"] is True
    assert value.pending.proposal.priority == 72


def test_quest_tooltip_mouseover_handoff_targets_collect_source_then_fights():
    value, _ = agent()
    quest = [{"quest_id": 55174, "title": "Cooking Meat", "is_accepted": True,
              "is_complete": False, "objectives": [{"type": "COLLECT",
              "raw_type": "item", "description": "0/5 Raw Meat collected from wildlife",
              "current": 0, "required": 5, "is_complete": False}]}]
    guid = "Creature-0-3102-2175-40024-161133-000029A31D"
    mouse = {"guid": guid, "npc_id": 161133, "name": "Coastal Albatross",
             "unit_type": "NPC", "is_attackable": True, "is_dead": False,
             "quest_related": True, "quest_id": 55174}
    value.tick(state(1, active_quests=quest, mouseover=mouse,
                     cursor_position={"nx": .77, "ny": .61},
                     cursor_sample_time=1, mouseover_sample_time=1), 1)
    assert value.pending and value.pending.proposal.skill == "TARGET"
    assert value.pending.proposal.parameters["guid"] == guid

    target = {"guid": guid, "npc_id": 161133, "name": "Coastal Albatross",
              "unit_type": "NPC", "attackable": True, "dead": False}
    actions = [{"kind": "spell", "action": "ACTIONBUTTON1", "id": 100, "is_harmful": True,
                "is_usable": True, "in_range": True, "cooldown_remaining": 0}]
    value.tick(state(2, active_quests=quest, target=target, mouseover=False,
                     cursor_position={"nx": .77, "ny": .61}, actionbar=actions), 2)
    assert value.last_result["outcome"] == "SUCCESS"
    value.tick(state(3, active_quests=quest, target=target, mouseover=False,
                     actionbar=actions), 3)
    assert value.pending and value.pending.proposal.skill == "COMBAT"
    assert value.pending.proposal.parameters["quest_ids"] == [55174]


def test_structured_unit_tooltip_without_guid_can_be_selected_then_name_verified():
    value, _ = agent()
    mouse = {
        "exists": True, "name": "Lady Jaina Proudmoore", "unit_type": "UNIT",
        "structured_unit": True, "identity_source": "TOOLTIP_PRIMARY_DATA",
        "tooltip_text": "Lady Jaina Proudmoore ~ Level 10",
        "tooltip_data": {"raw_type": 2, "is_unit": True,
                         "unit_name": "Lady Jaina Proudmoore"},
    }
    value.tick(state(1, mouseover=mouse,
                     cursor_position={"nx": .58, "ny": .60},
                     cursor_sample_time=1, mouseover_sample_time=1,
                     character_name="Test Player", world_map_open=False,
                     visual_candidates=quest_npc_boxes(.58, .60)), 1)
    assert value.last_decision["skill"] == "TARGET"
    assert value.pending.proposal.parameters["partial_identity"] is True
    assert value.pending.proposal.parameters["expected_name"] == "Lady Jaina Proudmoore"

    selected = {"guid": "Creature-0-1-2-3-156626-4", "npc_id": 156626,
                "name": "Lady Jaina Proudmoore", "unit_type": "NPC",
                "attackable": False, "dead": False}
    value.tick(state(2, target=selected, mouseover=False,
                     cursor_position={"nx": .58, "ny": .60}), 2)
    assert value.last_result["outcome"] == "SUCCESS"
    assert value.autonomy.commitment.target_guid == selected["guid"]


def test_confirmed_friendly_target_is_interacted_with_before_opening_map():
    value, _ = agent()
    target = {"guid": "jaina", "npc_id": 156626, "name": "Lady Jaina Proudmoore",
              "unit_type": "NPC", "attackable": False, "dead": False}
    value.tick(state(target=target, world_map_open=False, active_quests=[]), 1)
    assert value.last_decision["skill"] == "INTERACT"
    assert value.pending and value.pending.proposal.parameters["guid"] == "jaina"


def test_compact_creature_target_identity_is_interacted_with_before_opening_map():
    """Reproduces the live 0.9.7 bounded FAST target after Jaina selection."""
    value, _ = agent()
    target = {"guid": "Creature-0-4234-2175-9499-156626-000021EEC5",
              "npc_id": 156626, "attackable": False, "dead": False}

    value.tick(state(target=target, world_map_open=False, active_quests=[]), 1)

    assert value.last_decision["skill"] == "INTERACT"
    assert value.pending
    assert value.pending.proposal.parameters["guid"] == target["guid"]
    assert all(command.binding != "TOGGLEWORLDMAP" for command in value.executor.commands)


def test_entity_identity_location_role_and_state_are_separate():
    world = WorldModel()
    target = {"guid": "Creature-1", "npc_id": 42, "name": "Guide", "unit_type": "NPC",
              "world_position": {"x": .2, "y": .3, "z": 4},
              "quest_role": "QUEST_GIVER", "quest_role_source": "TOOLTIP",
              "quest_id": 7, "health": 100, "attackable": False}
    world.ingest(Observation.create(state(target=target, phase="p1", instance_id=9), 1))
    assert world.entities["npc:42"]["guids"] == ["Creature-1"]
    assert "locations" not in world.entities["npc:42"] and "roles" not in world.entities["npc:42"]
    assert world.query.entity("npc:42").name == "Guide"
    assert world.query.entity_locations("npc:42")[0].z == 4
    assert world.query.entity_roles("npc:42")[0].role == "QUEST_GIVER"
    assert world.query.entity_roles("npc:42")[0].quest_id == 7
    assert world.entity_states["npc:42"][0]["values"]["health"] == 100


def test_navigation_circling_guard():
    world = WorldModel()
    world.ingest(Observation.create(state(position={"x": .6, "y": .8}), 1))
    nav = AgentNavigator()
    destination = {"map_id": 1609, "x": .8, "y": .8}
    assert nav.permits(world, destination, 1)
    # Circling at a constant distance: walked, never closer.  (Standing
    # still -- INSPECT, loot -- is not circling, live 2026-10-06.)
    world.ingest(Observation.create(state(14., position={"x": .8, "y": .6}), 14))
    assert not nav.permits(world, destination, 14)
    assert not nav.permits(world, destination, 15)
    # The route quarantine is deliberately short: the old 30-second value
    # produced long passive WAIT runs even when fresh evidence was available.
    assert nav.permits(world, destination, 19)


def test_measured_route_uses_smoothed_lookahead_instead_of_tiny_waypoint_steps():
    world = WorldModel()
    world.ingest(Observation.create(state(position={"x": .5, "y": .5}), 1))
    nav = AgentNavigator()
    graph = NavGraph()
    points = [("start", .5, .5), ("tiny", .5, .499),
              ("middle", .50005, .496), ("end", .5, .494)]
    for key, x, y in points:
        graph.add_node(NavGraphNode(key, WorldPosition(x, y)))
    for index, ((a, ax, ay), (b, bx, by)) in enumerate(zip(points, points[1:])):
        distance = math.hypot(bx-ax, by-ay)
        graph.add_edge(NavGraphEdge(f"edge-{index}", a, b, distance, distance),
                       bidirectional=False)
    nav.graphs[1609] = graph
    waypoint = nav.waypoint(world, {"map_id": 1609, "x": .5, "y": .494})
    assert waypoint["source"] == "MEASURED_ROUTE_LOOKAHEAD"
    assert math.hypot(waypoint["x"]-.5, waypoint["y"]-.5) >= .0039
    assert waypoint["y"] > .494


@pytest.mark.parametrize("text,domain", [("Fedezd fel a területet", "EXPLORE"), ("Farmolj ore-t", "MINE"),
    ("Questelj egész nap", "QUEST"), ("Fishingelj amíg tele a bag", "FISH"), ("Menj NPC 42-hez", "MOVE"), ("Menj BG-zni", "PVP")])
def test_high_level_goals(text, domain):
    assert Goal.parse(text, 1).domain == domain


def test_area_loot_retires_recent_kills_and_failed_corpses_are_released():
    """Live 2026-10-01 18:45-18:49: after one successful loot, Retail area loot
    had emptied the other corpses, which then failed loot_ui_not_opened; one
    stale point was clicked three times."""
    world = WorldModel()
    a, b, old = ("Creature-0-1-2-3-150228-0000000A", "Creature-0-1-2-3-150228-0000000B",
                 "Creature-0-1-2-3-150228-0000000C")
    world.ingest(Observation.create(state(1, target={"guid": a, "attackable": True},
                                          is_in_combat=True), 1))
    world.mark_combat_kill(old, 1.)
    world.mark_combat_kill(a, 40.)
    world.mark_combat_kill(b, 50.)
    world.mark_area_looted(55., window=30.)
    assert a not in world.owned_corpse_guids and b not in world.owned_corpse_guids
    assert old in world.owned_corpse_guids              # outside the area-loot window
    world.note_loot_failure(old, 60.)
    assert old in world.owned_corpse_guids
    world.note_loot_failure(old, 61.)
    assert old not in world.owned_corpse_guids
