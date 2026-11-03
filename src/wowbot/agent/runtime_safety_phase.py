"""Selected-PID foreground/emergency safety gate for AgentRuntime."""
from __future__ import annotations

from .models import Mode


FOREGROUND_DEMOTE_SECONDS = 15.0


def enforce_runtime_safety(runtime, backend, now: float) -> None:
    """Suspend immediately on focus loss, demote only if it persists."""
    if backend and backend.emergency_pressed():
        runtime.mode("MANUAL")
    if not backend or runtime.agent.mode != Mode.FULL_AI:
        return
    if backend.is_selected_foreground():
        runtime._not_foreground_since = None
        runtime._foreground_suspended = False
        return
    # The backend independently refuses every command while the selected PID
    # is not foreground.  Explicitly release persistent movement too, without
    # destroying the committed subgoal for a brief Alt-Tab/GUI interaction.
    if not runtime._foreground_suspended:
        runtime.executor.stop_movement()
        runtime._foreground_suspended = True
        owner = getattr(backend, "foreground_owner", None)
        try:
            taken_by = owner() if callable(owner) else {}
        except Exception:
            taken_by = {}
        runtime.foreground_loss = {"at": now, "demoted": False, **taken_by}
    if runtime._not_foreground_since is None:
        runtime._not_foreground_since = now
    elif now-runtime._not_foreground_since >= FOREGROUND_DEMOTE_SECONDS:
        loss = getattr(runtime, "foreground_loss", None)
        if isinstance(loss, dict):
            loss["demoted"] = True
        runtime.mode("MANUAL")
