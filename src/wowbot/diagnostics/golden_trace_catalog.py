"""Canonical, deterministic M1 replay scenarios required by the design spec."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .replay import ReplayPlayer, ReplayRecord, ReplayRecordKind


@dataclass(frozen=True, slots=True)
class GoldenTraceSpec:
    name: str
    session_id: str
    skill: str
    terminal: str
    expected_command: str


GOLDEN_TRACES: tuple[GoldenTraceSpec, ...] = (
    GoldenTraceSpec("interact", "golden-interact", "INTERACT", "SUCCESS", "INTERACTTARGET"),
    GoldenTraceSpec("combat_recovery", "golden-combat-recovery", "COMBAT", "RUNNING", "STRAFELEFT"),
    GoldenTraceSpec("navigation_stuck", "golden-navigation-stuck", "MOVE", "RUNNING", "STRAFERIGHT"),
    GoldenTraceSpec("quest_speak", "golden-quest-speak", "TALK", "SUCCESS", "INTERACTTARGET"),
    GoldenTraceSpec("quest_kill", "golden-quest-kill", "COMBAT", "SUCCESS", "ACTIONBUTTON1"),
    GoldenTraceSpec("collect", "golden-collect", "LOOT", "SUCCESS", "INTERACTTARGET"),
    GoldenTraceSpec("turn_in", "golden-turn-in", "QUEST_DIALOG", "SUCCESS", "CLICK"),
)


def load_golden_trace(path: str | Path, spec: GoldenTraceSpec) -> tuple[ReplayRecord, ...]:
    """Load and semantically validate one canonical trace.

    Validation makes the fixtures evidence rather than decorative files.  The
    function is diagnostics-only and cannot execute recorded commands.
    """
    records = ReplayPlayer().load(path, session_id=spec.session_id)
    if not records:
        raise ValueError(f"missing golden trace session: {spec.session_id}")
    kinds = {record.kind for record in records}
    required = {
        ReplayRecordKind.SESSION_START,
        ReplayRecordKind.OBSERVATION,
        ReplayRecordKind.SKILL_TRANSITION,
        ReplayRecordKind.COMMAND,
        ReplayRecordKind.VERIFICATION,
        ReplayRecordKind.SESSION_END,
    }
    if not required.issubset(kinds):
        missing = sorted(item.value for item in required - kinds)
        raise ValueError(f"incomplete golden trace {spec.name}: {missing}")
    start = next(item for item in records if item.kind is ReplayRecordKind.SESSION_START)
    transition = next(item for item in records if item.kind is ReplayRecordKind.SKILL_TRANSITION)
    command = next(item for item in records if item.kind is ReplayRecordKind.COMMAND)
    verification = next(item for item in records if item.kind is ReplayRecordKind.VERIFICATION)
    if start.payload.get("scenario") != spec.name:
        raise ValueError(f"wrong scenario metadata for {spec.name}")
    if transition.payload.get("skill") != spec.skill:
        raise ValueError(f"wrong skill transition for {spec.name}")
    if transition.payload.get("current") != spec.terminal:
        raise ValueError(f"wrong terminal transition for {spec.name}")
    if (command.payload.get("command") or {}).get("binding") != spec.expected_command:
        raise ValueError(f"wrong command for {spec.name}")
    verification_payload = verification.payload.get("verification") or {}
    if verification_payload.get("success") is not True:
        raise ValueError(f"unverified golden trace: {spec.name}")
    if not verification_payload.get("evidence"):
        raise ValueError(f"golden trace lacks verification evidence: {spec.name}")
    return records


def validate_golden_catalog(path: str | Path) -> dict[str, tuple[ReplayRecord, ...]]:
    return {spec.name: load_golden_trace(path, spec) for spec in GOLDEN_TRACES}

