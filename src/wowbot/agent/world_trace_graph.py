"""Execution-trace to WorldModel relation/event projection.

This component is intentionally authority-neutral: it can only call the
WorldModel's bounded ``link`` and derived-event surfaces.  It neither mutates
planning state nor performs input.
"""
from __future__ import annotations

from .models import number


class WorldTraceGraph:
    def record_plan(self, world, goal, plan, obs) -> None:
        goal_id = f"goal:{goal.goal_id}"
        subgoal_id = f"subgoal:{plan.subgoal_id}"
        plan_id = f"plan:{plan.plan_id}"
        world.link(goal_id, "has_subgoal", subgoal_id, obs, 1., "CONFIRMED")
        world.link(subgoal_id, "planned_by", plan_id, obs, plan.confidence, "HYPOTHESIS")
        world.link(plan_id, "based_on", f"observation:{obs.observation_id}", obs, 1., "CONFIRMED")

    def record_action(self, world, attempt, obs) -> None:
        action_id = f"action:{attempt.action_id}"
        world.link(f"plan:{attempt.plan_id}", "selected_action", action_id, obs, 1., "EXECUTED")
        world.link(action_id, "expects", f"prediction:{attempt.prediction.prediction_id}",
                   obs, attempt.prediction.confidence, "HYPOTHESIS")
        world.link(action_id, "based_on", f"observation:{attempt.observation_id}",
                   obs, 1., "CONFIRMED")

    def record_verification(self, world, verification, obs) -> None:
        verification_id = f"verification:{verification.verification_id}"
        world.link(f"action:{verification.action_id}", "verified_by", verification_id,
                   obs, 1., "CONFIRMED")
        world.link(f"prediction:{verification.prediction_id}", "resolved_by", verification_id,
                   obs, 1., "CONFIRMED")
        if verification.observed_observation_id:
            world.link(verification_id, "observed_by",
                       f"observation:{verification.observed_observation_id}",
                       obs, 1., "CONFIRMED")

    def ingest(self, world, obs) -> None:
        payload = obs.payload
        kind, value = payload.get("trace_type"), payload.get("trace") or {}
        if kind == "PLAN":
            goal_id = value.get("goal_id")
            subgoal_id = value.get("subgoal_id")
            plan_id = value.get("plan_id")
            if all((goal_id, subgoal_id, plan_id)):
                world.link(f"goal:{goal_id}", "has_subgoal", f"subgoal:{subgoal_id}",
                           obs, 1., "CONFIRMED")
                world.link(f"subgoal:{subgoal_id}", "planned_by", f"plan:{plan_id}",
                           obs, number(value.get("confidence")) or 0., "HYPOTHESIS")
                if value.get("observation_id"):
                    world.link(f"plan:{plan_id}", "based_on",
                               f"observation:{value['observation_id']}",
                               obs, 1., "CONFIRMED")
        elif kind in {"ACTION_INTENT", "ACTION_EXECUTED", "ACTION_CANCELLED"}:
            action_id, plan_id = value.get("action_id"), value.get("plan_id")
            status = {"ACTION_INTENT": "INTENDED", "ACTION_EXECUTED": "EXECUTED",
                      "ACTION_CANCELLED": "CANCELLED"}[kind]
            if action_id:
                world.link(f"action:{action_id}", "has_lifecycle",
                           f"action_status:{status}", obs, 1., "CONFIRMED")
            if action_id and plan_id:
                world.link(f"plan:{plan_id}", "selected_action", f"action:{action_id}",
                           obs, 1., status)
            prediction = value.get("prediction") or {}
            if action_id and prediction.get("prediction_id"):
                world.link(f"action:{action_id}", "expects",
                           f"prediction:{prediction['prediction_id']}", obs,
                           number(prediction.get("confidence")) or 0., "HYPOTHESIS")
            if action_id and value.get("observation_id"):
                world.link(f"action:{action_id}", "based_on",
                           f"observation:{value['observation_id']}", obs, 1., "CONFIRMED")
        elif kind == "VERIFICATION":
            action_id = value.get("action_id")
            verification_id = value.get("verification_id")
            prediction_id = value.get("prediction_id")
            if action_id and verification_id:
                world.link(f"action:{action_id}", "verified_by",
                           f"verification:{verification_id}", obs, 1., "CONFIRMED")
            if prediction_id and verification_id:
                world.link(f"prediction:{prediction_id}", "resolved_by",
                           f"verification:{verification_id}", obs, 1., "CONFIRMED")
            if verification_id and value.get("observed_observation_id"):
                world.link(f"verification:{verification_id}", "observed_by",
                           f"observation:{value['observed_observation_id']}",
                           obs, 1., "CONFIRMED")
        if kind:
            world._emit_derived_event(f"AGENT_{kind}", {
                "goal_id": value.get("goal_id"), "plan_id": value.get("plan_id"),
                "action_id": value.get("action_id"),
                "verification_id": value.get("verification_id"),
                "trace_observation_id": obs.observation_id}, obs)
