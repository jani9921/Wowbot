"""Authoritative mount-capability gates shared by planning and dispatch."""
from __future__ import annotations


def mount_capability_allows(state: dict) -> bool:
    """Return true only for explicit, current addon capability evidence.

    A configured mount binding or an action-bar icon is not proof that the
    character owns a usable mount or has learned riding. Missing/unknown
    telemetry therefore fails closed. Dismount intentionally does not use this
    gate because an observed mounted character must always be able to get off.
    """
    capability = state.get("mount_capability")
    return (
        isinstance(capability, dict)
        and capability.get("has_collected_mount") is True
        and capability.get("riding_capability_confirmed") is True
    )

