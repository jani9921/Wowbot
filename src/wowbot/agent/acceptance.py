"""Deterministic live/soak acceptance accounting.

This module never controls the client.  It turns read-only status samples into
explicit pass/fail/not-measured gates so an offline replay cannot be mistaken
for a live endurance result.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class AcceptanceAccumulator:
    started_at: float
    samples: int = 0
    full_ai_samples: int = 0
    full_ai_stale_samples: int = 0
    runtime_errors: int = 0
    replans: int = 0
    recoveries: int = 0
    failures: int = 0
    max_held_keys: int = 0
    last_replan_revision: int | None = None
    last_phase: str | None = None
    action_ids: set[str] = field(default_factory=set)

    def update(self, summary: dict, raw_status: dict) -> None:
        self.samples += 1
        full_ai = summary.get("mode") == "FULL_AI"
        self.full_ai_samples += int(full_ai)
        self.full_ai_stale_samples += int(full_ai and summary.get("fresh") is False)
        self.runtime_errors += int(bool(summary.get("runtime_error")))
        result = summary.get("result") or {}
        self.failures += int(result.get("outcome") == "FAILURE"
                             and result.get("action_id") not in self.action_ids)
        if result.get("action_id"):
            self.action_ids.add(result["action_id"])
        revision = summary.get("replan_revision")
        if (revision is not None and self.last_replan_revision is not None
                and revision != self.last_replan_revision):
            self.replans += max(1, int(revision)-int(self.last_replan_revision))
        self.last_replan_revision = revision
        phase = summary.get("phase")
        if phase == "RECOVERING" and self.last_phase != "RECOVERING":
            self.recoveries += 1
        self.last_phase = phase
        safety = raw_status.get("input_safety") or {}
        self.max_held_keys = max(self.max_held_keys, int(safety.get("held_key_count") or 0))

    def report(self, *, ended_at: float, final_summary: dict,
               final_status: dict, required_duration: float) -> dict:
        duration = max(0., ended_at-self.started_at)
        safety = final_status.get("input_safety") or {}
        final_held = int(safety.get("held_key_count") or len(safety.get("held_keys") or []))
        stale_ratio = self.full_ai_stale_samples/max(1, self.full_ai_samples)
        minutes = max(duration/60., 1/60.)
        replan_rate = self.replans/minutes
        gates = {
            "duration_reached": duration >= required_duration,
            "live_full_ai_observed": self.full_ai_samples > 0,
            "no_runtime_errors": self.runtime_errors == 0,
            "telemetry_stale_ratio_below_20_percent": stale_ratio <= .20,
            "no_planner_thrash_over_30_replans_per_min": replan_rate <= 30.,
            "safe_handoff_not_full_ai": final_summary.get("mode") != "FULL_AI",
            "no_keys_held_at_handoff": final_held == 0,
        }
        return {
            "result": "PASS" if all(gates.values()) else "FAIL",
            "live": True,
            "required_duration_seconds": required_duration,
            "duration_seconds": round(duration, 3),
            "gates": gates,
            "metrics": {"samples": self.samples, "full_ai_samples": self.full_ai_samples,
                        "runtime_errors": self.runtime_errors, "action_failures": self.failures,
                        "stale_ratio_during_full_ai": round(stale_ratio, 5),
                        "replans": self.replans, "replans_per_minute": round(replan_rate, 4),
                        "recoveries": self.recoveries, "max_held_keys": self.max_held_keys,
                        "final_held_keys": final_held},
            "ended_mode": final_summary.get("mode"),
            "session_id": final_summary.get("session_id"),
        }

