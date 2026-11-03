"""Server-selected input policy and independent server-stream health.

User 2026-10-21: "állítsd át szerver módra" -- after agent-wow cleared the orc
starting zone on server data alone, and after the earlier question "kell
nekünk így mostmár az egész vizuális rész?".  While the server stream is
fresh (a packet within FRESH_SECONDS and server entities in view):

* the planner drops screen/map searching (INSPECT, SEEK_VISUAL_CUE, OPEN_MAP,
  search-cell and minimap-dot MOVEs) whenever any server-driven proposal
  exists, not only for kill targets (``Planner.prefer_server_targets``);
* a running MOVE is no longer stopped by unidentified World3D boxes; server
  hand-offs and exact mouseover identities still stop it
  (``movement_visual_interrupt``).

Selection and health are separate: a stale or empty stream must never
silently enable visual input. ``AIPC_SERVER_MODE=0`` explicitly restores
vision-first behaviour. Offline worlds without a configured packet sensor
and without packet history keep their existing visual policy.
"""
from __future__ import annotations

import os

FRESH_SECONDS = 20.
SERVER_EVIDENCE = frozenset({"kill_objective_entry", "tab_nearest_ahead",
                             "objective_npc_became_client_actor"})
SERVER_ACTIVATIONS = frozenset({"INTERACT_KEY_PACKET", "TAB_SERVER_GUID"})
KEY_TARGET_ACTIVATIONS = frozenset({"TAB_SERVER_GUID", "TAB_DEFEND", "TAB_FRIEND_RESCUE"})


def pointer_target(proposal) -> bool:
    """Screen TARGET needs pointer commands that server mode deliberately withholds."""
    return (proposal.skill == "TARGET"
            and proposal.parameters.get("activation_source") not in KEY_TARGET_ACTIVATIONS
            and not proposal.parameters.get("restore_last_target"))


def enabled() -> bool:
    return os.environ.get("AIPC_SERVER_MODE", "1").strip().lower() not in {"0", "false", "off"}


def status(packet_age: float | None, entities: int) -> dict:
    fresh = packet_age is not None and 0. <= packet_age <= FRESH_SECONDS
    active = enabled() and fresh and entities > 0
    configured = (os.environ.get("AIPC_SERVER_MODE") is not None
                  or os.environ.get("AIPC_PACKET_TELEMETRY", "0").lower() in {"1", "true", "yes", "on"})
    selected = enabled() and (configured or packet_age is not None or entities > 0)
    return {"active": active, "enabled": enabled(), "selected": selected,
            "packet_age": None if packet_age is None else round(packet_age, 2),
            "server_entities": entities,
            "reason": ("server_stream_fresh" if active else "disabled" if not enabled()
                       else "no_server_entities" if fresh else "server_stream_stale")}


def server_mode_active(state: dict) -> bool:
    return (state.get("server_mode") or {}).get("active") is True


def server_profile(state: dict) -> bool:
    """The SERVER composition (REV4, user 2026-10-30): visual recognition is
    retired there, so no planner builds screen/map/camera search proposals.
    LEGACY_VISION states carry no ``runtime_profile`` key."""
    return state.get("runtime_profile") == "SERVER"


def server_mode_selected(state: dict) -> bool:
    """Input/planner policy, not sensor health; compatible with older snapshots."""
    mode = state.get("server_mode") or {}
    return mode.get("selected", mode.get("enabled", mode.get("active", False))) is True


def server_driven(proposal) -> bool:
    """A proposal built from server facts (Ymir entities, server GUIDs)."""
    evidence = {str(tag) for tag in proposal.evidence or ()}
    params = proposal.parameters
    return bool(SERVER_EVIDENCE & evidence or any(tag.startswith("server_") for tag in evidence)
                or params.get("knowledge_priority") == "SERVER_LIVE"
                or params.get("server_entity_guid")
                or params.get("activation_source") in SERVER_ACTIVATIONS)
