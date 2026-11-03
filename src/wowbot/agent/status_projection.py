"""Read-only AutonomousAgent status projection.

Keeping this construction outside the control loop makes the engine a smaller
composition root.  This module must never select work, mutate the world or
dispatch input; it merely turns existing authoritative state into diagnostics.
"""
from __future__ import annotations

from .engine_runtime_projection import active_skill_snapshot, combat_runtime_snapshot
from .map_poi_planning import MapPoiPlanningPolicy
from .models import Mode

from dataclasses import asdict
import time


# Diagnostics must not run at the 20--40 Hz physical control cadence.  The
# canonical WorldModel is still updated every observation; only its large,
# read-only JSON projection is sampled at this bounded rate. The standalone
# live viewer receives its current overlay directly, so diagnostic WORLD3D
# frames must not invalidate this expensive projection on every tracker tick.
WORLD_STATUS_REFRESH_SECONDS = 1.0


class AgentStatusProjection:
    @staticmethod
    def _skill_contracts(agent) -> list[dict]:
        # The registry's contracts are static for the life of the process, yet
        # this was re-serializing all of them with asdict() on every tick as
        # part of the ~100 asdict calls that made status() 62% of tick time.
        # Cache keyed on the contracts mapping identity and size so a registry
        # swap or late registration still invalidates it.
        contracts = agent.registry.contracts
        key = (id(contracts), len(contracts))
        cached = getattr(agent, "_skill_contract_status_cache", None)
        if cached is None or cached[0] != key:
            cached = (key, [asdict(contract) for contract in contracts.values()])
            agent._skill_contract_status_cache = cached
        return cached[1]

    @staticmethod
    def build(agent, now: float) -> dict:
        projection_started = time.perf_counter()
        agent._flush_autonomy_events()
        if agent.memory and now-agent._sensor_health_cache[0] >= 2.:
            agent._sensor_health_cache = (now, agent.memory.sensor_health(agent.world.state))
        # Diagnostics only.  Live 2026-10-25 17:28:54-17:29:00 this refresh
        # held the engine lock ~6 s in SQLite and the Skyriding loop flew
        # unsteered; like consolidation it waits until FULL_AI is disarmed.
        if (agent.memory and agent.mode != Mode.FULL_AI
                and now-agent._memory_metrics_cache[0] >= 120.):
            agent._memory_metrics_cache = (now, agent.memory.metrics())
        # The skill fields must be repeated here: this per-tick refresh
        # replaced them with None, so between planning passes the world (and
        # quest-progress learning, which runs on ingest) never knew which
        # skill was running or had just finished -- every quest_progress row
        # had skill=NULL (found 2026-10-12).
        from .engine_runtime_projection import active_skill_snapshot
        agent.world.set_runtime_context(
            goal=agent.goal, subgoal=agent.current_plan,
            commitment=agent.autonomy.commitment,
            active_skill=active_skill_snapshot(agent.active_skill),
            last_result=agent.last_result,
            sensor_health=agent._sensor_health_cache[1] if agent.memory else [],
            primary_quest=agent.quest_runtime.snapshot(now),
            quest_failure_memory=agent.quest_runtime.failure_memory.snapshot(now),
        )
        input_safety = (agent.executor.diagnostics()
                        if hasattr(agent.executor, "diagnostics") else {})
        cached_world = getattr(agent, "_world_status_projection_cache", None)
        cached_sources = ((cached_world[2].get("observation_sources") or {})
                          if cached_world is not None else {})
        # A fresh World3D observation that *changed control* must be visible in
        # the handoff snapshot once. Ordinary tracker frames are already sent
        # directly to the viewer and must not invalidate this large projection.
        initial_control_world3d = (
            ((agent.last_decision or {}).get("reason")
             == "live_visual_inspection_candidate_observed"
             or (agent.last_result or {}).get("reason")
             == "live_visual_inspection_candidate_observed")
            and "WORLD3D" not in cached_sources)
        if (cached_world is None or now < cached_world[0]
                or now-cached_world[0] >= WORLD_STATUS_REFRESH_SECONDS
                or cached_world[1] != agent.world.session_id
                or initial_control_world3d):
            world_projection_started = time.perf_counter()
            world_status = agent.world.snapshot(now)
            agent._world_status_projection_cache = (
                now, agent.world.session_id, world_status, None)
            agent.performance_monitor.observe_latency(
                "status_world_projection",
                (time.perf_counter()-world_projection_started)*1000.)
        else:
            world_status = cached_world[2]
        result = {
            "mode": agent.mode.value, "goal": asdict(agent.goal) if agent.goal else None,
            "decision": agent.last_decision, "result": agent.last_result,
            "pending": agent.pending.to_dict() if agent.pending else None,
            "plan": asdict(agent.current_plan) if agent.current_plan else None,
            "world": world_status,
            "reasoner": agent.reasoner.snapshot() if agent.reasoner else {"status": "deterministic"},
            "semantic_advisor": (agent.semantic_advisor.snapshot()
                                 if getattr(agent, "semantic_advisor", None) else {"status": "absent"}),
            "supervisor": agent.supervisor.snapshot(), "event_bus": agent.events.diagnostics(),
            "structured_log": agent.structured_logger.snapshot(),
            "command_acknowledgements": agent.command_dispatcher.diagnostics(),
            "parallel_control": agent.parallel_control.snapshot(now),
            "quest_agenda": agent.planner.agenda.snapshot(),
            "objective_probes": (agent.planner.objective_probes.snapshot()
                                 if hasattr(agent.planner, "objective_probes") else None),
            "needs_user": (agent.planner.needs_user.snapshot()
                           if hasattr(agent.planner, "needs_user") else []),
            "quest_playbook_trials": agent.quest_attempt_memory.playbook_snapshot(limit=20),
            "runtime_health": asdict(agent.health_monitor.observe(
                now=now, last_received=(agent.world.last_received if agent.world.latest else None),
                event_bus=agent.events.diagnostics(),
                active_skill=(agent.active_skill.state.skill_type if agent.active_skill.state else None),
                last_supervisor_tick=agent._last_supervisor_tick,
                input_safety=input_safety,
            )),
            "route": agent.navigation.last_route, "navigation": agent.navigation.snapshot(now),
            "movement_controller": agent.navigation.movement_snapshot(),
            "visual_approach": agent.visual_approach.snapshot() if agent.visual_approach is not None else {'status': 'disabled'},
            "vision_seek": agent.search_skill.snapshot(agent.active_skill.state) if agent.search_skill is not None else {'status': 'disabled'},
            "camera_controller": agent.camera.snapshot(),
            "combat_runtime": combat_runtime_snapshot(agent.active_skill),
            "skill_lifecycle": active_skill_snapshot(agent.active_skill),
            "failure_manager": agent.failure_manager.snapshot(),
            "loop_guard": agent.loop_guard.snapshot(),
            "autonomous_loop": agent.autonomy.snapshot(), "episode_id": agent.episode_id,
            "goal_manager": agent.goals.snapshot(now),
            "task_pattern_analysis": agent.planner.pattern_analysis,
            "travel_mode": agent.planner.travel_mode.snapshot(),
            "server_mode": agent.world.state.get("server_mode"),
            "map_inspection": agent.planner.map_inspection_status(),
            "map_pois": MapPoiPlanningPolicy.status(agent.world.state),
            "sensor_health": agent._sensor_health_cache[1] if agent.memory else [],
            "runtime_scheduler": agent.brain_scheduler.snapshot(now),
            "passive_wait": agent.passive_wait.snapshot(now),
            "performance": agent.performance_monitor.snapshot(now),
            "memory_metrics": agent._memory_metrics_cache[1] if agent.memory else {},
            "skills": AgentStatusProjection._skill_contracts(agent),
        }
        agent.performance_monitor.observe_latency(
            "status_projection", (time.perf_counter()-projection_started)*1000.)
        return result
