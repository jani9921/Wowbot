"""Read-only active-bar context and canonical Skyriding action projection.

The selected cache still owns physical bindings. A bar context owns only
which spell ACTIONBUTTONn currently executes, never its physical key.
"""
from __future__ import annotations

from .models import json_copy


def current_actionbar_context(state: dict) -> dict | None:
    context = state.get("actionbar_context")
    if (not isinstance(context, dict) or type(context.get("page")) is not int
            or not 1 <= context["page"] <= 32
            or type(context.get("revision")) is not int or context["revision"] < 0
            or context.get("kind") not in {
                "NORMAL", "PAGED", "SKYRIDING", "VEHICLE", "OVERRIDE", "TEMP_SHAPESHIFT"}):
        return None
    return context


def binding_context(state: dict) -> str:
    context = current_actionbar_context(state)
    if (context is not None and context["kind"] == "SKYRIDING"
            and state.get("is_mounted") is not False
            and state.get("in_vehicle") is not True and state.get("on_taxi") is not True
            and not state.get("is_dead") and not state.get("is_ghost")):
        return "SKYRIDING"
    return "NORMAL"


def project_skyriding_actionbar(state: dict) -> bool:
    """True when the Skyriding branch owns this projection (including unknown rows).

    A fast page/revision transition invalidates old spell rows. The matching
    full snapshot must arrive before a former spell can be selected again.
    Old addon/vehicle snapshots without a context keep their existing path.
    """
    context = current_actionbar_context(state)
    state["skyriding_controls"] = False
    if context is None:
        if "actionbar_context" in state:
            # An explicitly unknown/malformed new context cannot resurrect
            # retained abilities. Legacy snapshots omit the field entirely.
            state["actionbar"] = []
            state["vehicle_controls"] = False
            return True
        return False
    if "player_actionbar" not in state:
        state["player_actionbar"] = json_copy(state.get("actionbar") or [])
    base = state["player_actionbar"]
    coherent = state.get("actionbar_snapshot_context") == context
    if context["kind"] != "SKYRIDING":
        state["actionbar"] = json_copy(base) if coherent else []
        return False
    state["vehicle_controls"] = False
    state["actionbar"] = []
    if binding_context(state) != "SKYRIDING":
        return True
    state["skyriding_controls"] = True
    bar = state.get("skyriding_bar")
    if (not isinstance(bar, dict) or bar.get("kind") != "SKYRIDING"
            or bar.get("page") != context["page"]
            or bar.get("revision") != context["revision"]):
        return True
    actions = []
    for row in bar.get("actions") or ():
        if not isinstance(row, dict):
            continue
        index = row.get("index")
        if (type(index) is not int or not 1 <= index <= 12
                or row.get("slot") != (context["page"] - 1) * 12 + index
                or row.get("action") != f"ACTIONBUTTON{index}"):
            continue
        actions.append({**json_copy(row), "source": "SKYRIDING_BAR"})
    # Independently bound sidebars remain usable; hidden primary-bar combat
    # rows never become flight abilities. Do not carry rows across revisions.
    if coherent:
        actions.extend(json_copy(row) for row in base
                       if isinstance(row, dict)
                       and str(row.get("action") or "").startswith("MULTIACTIONBAR"))
    state["actionbar"] = actions
    return True
