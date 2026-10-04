"""Canonical runtime ownership primitives.

The package contains no WoW input implementation.  It owns typed runtime
state only; sensors, world model, skills and executor remain separate.
"""

from .active_skill import (ActiveSkillRuntime, ActiveSkillState, CancellationToken,
                           SkillContext, SkillLifecycleState, SkillLifecycleTransition)
from .contracts import (FailureReason, Intent, RuntimeEvent, SkillResult, SkillStatus,
                        ObjectiveLocationStatus, VerificationResult, failure_reason_from_legacy)
from .events import EventBus
from .entity_identity import WorldEntityId, world_entity_id
from .failures import (FailureDecision, FailureEscalationStage, FailureManager,
                       FailureRecord)
from .freshness_gate import FreshnessDecision, FreshnessDecisionKind, FreshnessGate
from .health import HealthMonitor, HealthReport
from .loop_guard import (ActionSignature, LoopDecision, LoopGuard, LoopLevel,
                         LoopSignatureKind, RouteSegmentSignature, SkillSignature,
                         TargetFailureSignature, WorldStateSignature)
from .performance import LatencySummary, PerformanceMonitor, measure_input_dispatch, measure_runtime_tick
from .m0_dispatch import M0SkillDispatcher
from .policies import RetryPolicy, TimeoutPolicy
from .supervisor import (Supervisor, SupervisorDirective, SupervisorDirectiveKind,
                         SupervisorRetryPolicy, SupervisorState, SupervisorStateSpec)
from .structured_logger import LogLevel, StructuredLogEntry, StructuredLogger
from .verification_engine import VerificationDecision, VerificationEngine
from .skill_executor import SkillExecutor, SkillLaunch, SkillPreparation
from .state_invalidation import (InvalidationDecision, InvalidationEvent,
                                 StateInvalidationPolicy)
from .cinematic_policy import CinematicSkipDecision, CinematicSkipPolicy

__all__ = (
    "ActiveSkillRuntime", "ActiveSkillState", "CancellationToken", "SkillContext",
    "SkillLifecycleState", "SkillLifecycleTransition", "FailureReason", "Intent",
    "RuntimeEvent", "SkillResult", "SkillStatus", "VerificationResult",
    "ObjectiveLocationStatus",
    "failure_reason_from_legacy",
    "EventBus", "WorldEntityId", "world_entity_id",
    "Supervisor", "SupervisorDirective", "SupervisorDirectiveKind", "SupervisorState",
    "SupervisorStateSpec", "SupervisorRetryPolicy",
    "FailureRecord", "FailureDecision", "FailureEscalationStage", "FailureManager",
    "FreshnessDecision", "FreshnessDecisionKind", "FreshnessGate",
    "HealthMonitor", "HealthReport",
    "ActionSignature", "LoopDecision", "LoopGuard", "LoopLevel",
    "LoopSignatureKind", "RouteSegmentSignature", "SkillSignature",
    "TargetFailureSignature", "WorldStateSignature",
    "LatencySummary", "PerformanceMonitor", "measure_input_dispatch", "measure_runtime_tick",
    "M0SkillDispatcher", "RetryPolicy", "TimeoutPolicy",
    "LogLevel", "StructuredLogEntry", "StructuredLogger",
    "VerificationDecision", "VerificationEngine",
    "SkillExecutor", "SkillLaunch", "SkillPreparation",
    "InvalidationDecision", "InvalidationEvent", "StateInvalidationPolicy",
    "CinematicSkipDecision", "CinematicSkipPolicy",
)
