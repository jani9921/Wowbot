from .models import (
    ArrivalCondition,
    DestinationIntent,
    DestinationKind,
    MovementIntent,
    MovementMode,
    NavigationPlan,
    NavigationStatus,
)
from .graph import NavGraph, NavGraphNode, NavGraphEdge
from .planner import RoutePlanner, NoRouteError
from .world_context import CanonicalWorldContext, CoordinateBounds, CoordinateMapper, MapIdentityResolver
from .progress import ProgressMonitor, ProgressPhase, ProgressPolicy, ProgressScore
from .stuck_resolver import RecoveryDirective, StuckResolutionState, StuckResolver
from .contracts import ArrivalEnvelope, GlobalRoute, LocalMotionPlan, NavigationRequest, PathCorridor
from .global_planner import GlobalPlanner, GlobalPlannerPolicy
from .corridor import CorridorPolicy, PathCorridorBuilder
from .local_planner import LocalPlanner, LocalPlannerPolicy
from .stuck_classifier import StuckAssessment, StuckClassifier, StuckKind
from .mmap_navmesh import MMapDataSource, NavMeshPath, TrinityMMapNavMesh
from .los_recovery import LosRecoveryDirective, LosRecoveryPhase, LosRecoveryPlanner
from .navigation_context import NavigationContext, NavigationContextAssessment, NavigationContextClassifier
from .transition_resolver import TransitionAssessment, TransitionKind, TransitionResolver
from .navigation_mode import NavigationMode, NavigationModeEvidence, resolve_navigation_mode
from .arrival import ArrivalAssessment, ArrivalStatus, ArrivalVerifier

__all__ = [
    "ArrivalCondition", "DestinationIntent", "DestinationKind", "MovementIntent", "MovementMode",
    "NavigationPlan", "NavigationStatus", "NavGraph", "NavGraphNode", "NavGraphEdge", "RoutePlanner",
    "NoRouteError", "CanonicalWorldContext", "CoordinateBounds", "CoordinateMapper", "MapIdentityResolver",
    "ProgressMonitor", "ProgressPhase", "ProgressPolicy", "ProgressScore",
    "RecoveryDirective", "StuckResolutionState", "StuckResolver",
    "ArrivalEnvelope", "GlobalRoute", "LocalMotionPlan", "NavigationRequest", "PathCorridor",
    "GlobalPlanner", "GlobalPlannerPolicy", "CorridorPolicy", "PathCorridorBuilder", "LocalPlanner", "LocalPlannerPolicy",
    "StuckAssessment", "StuckClassifier", "StuckKind",
    "MMapDataSource", "NavMeshPath", "TrinityMMapNavMesh",
    "NavigationContext", "NavigationContextAssessment", "NavigationContextClassifier",
    "TransitionAssessment", "TransitionKind", "TransitionResolver",
    "NavigationMode", "NavigationModeEvidence", "resolve_navigation_mode",
    "ArrivalAssessment", "ArrivalStatus", "ArrivalVerifier",
]
# ``service`` composes the agent-side movement controller.  Importing it here
# would make a low-level ``navigation.progress`` import pull the controller
# back in while that controller is still importing progress.  Keep the public
# service available lazily without making package import order an authority.
def __getattr__(name: str):
    if name == "NavigationService":
        from .service import NavigationService
        return NavigationService
    raise AttributeError(name)


__all__ = [
    "ArrivalCondition", "DestinationIntent", "DestinationKind", "MovementIntent", "MovementMode",
    "NavigationPlan", "NavigationStatus", "NavGraph", "NavGraphNode", "NavGraphEdge", "RoutePlanner",
    "NoRouteError", "CanonicalWorldContext", "CoordinateBounds", "CoordinateMapper", "MapIdentityResolver",
    "ProgressMonitor", "ProgressPhase", "ProgressPolicy", "ProgressScore",
    "RecoveryDirective", "StuckResolutionState", "StuckResolver", "NavigationService",
    "LosRecoveryDirective", "LosRecoveryPhase", "LosRecoveryPlanner",
    "ArrivalEnvelope", "GlobalRoute", "LocalMotionPlan", "NavigationRequest", "PathCorridor",
    "GlobalPlanner", "GlobalPlannerPolicy", "CorridorPolicy", "PathCorridorBuilder", "LocalPlanner", "LocalPlannerPolicy",
    "StuckAssessment", "StuckClassifier", "StuckKind",
    "MMapDataSource", "NavMeshPath", "TrinityMMapNavMesh",
    "NavigationContext", "NavigationContextAssessment", "NavigationContextClassifier",
    "TransitionAssessment", "TransitionKind", "TransitionResolver",
    "NavigationMode", "NavigationModeEvidence", "resolve_navigation_mode",
    "ArrivalAssessment", "ArrivalStatus", "ArrivalVerifier",
]
