"""Conservative local exploration of a DB spawn, never a live target fact."""
import math
from .models import number


def reference_destination(state):
    target = state.get("target") or {}
    player = state.get("player_world_position") or {}
    if not target.get("guid") or target.get("npc_id") is None:
        return None
    px, py, pz = (number(player.get(k)) for k in ("x", "y", "z"))
    if None in (px, py, pz) or player.get("instance_id") is None:
        return None
    matches = []
    for row in state.get("spawn_reference_candidates", []):
        if (row.get("source") != "TDB_REFERENCE" or not row.get("source_sha256")
                or row.get("npc_id") != target["npc_id"]
                or row.get("world_map_id") != player["instance_id"]):
            continue
        x, y, z = (number(row.get(k)) for k in ("x", "y", "z"))
        if None in (x, y, z) or not all(math.isfinite(v) for v in (x,y,z)):
            continue
        phase = (row.get("context") or {}).get("PhaseId")
        if state.get("phase") is not None and str(phase) not in {"0", str(state["phase"])}:
            continue
        if math.hypot(x-px,y-py) <= 60 and abs(z-pz) <= 8:
            matches.append(row)
    # No nearest-spawn guess when several phase/location candidates fit.
    return matches[0] if len(matches) == 1 else None
