"""Immutable manifest model for user-reviewed real WoW regression sessions."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path


ALLOWED_CASES = frozenset({
    "quest_giver", "quest_turn_in", "moving_npc", "multi_map_npc",
    "multi_location_npc", "unknown_marker", "ambiguous_marker", "ui_variation",
    "telemetry_failure", "vision_failure", "combat_situation", "resource_gathering",
    "navigation_failure",
})


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_golden_manifest(path: Path) -> dict:
    manifest = json.loads(path.read_text(encoding="utf-8"))
    errors = []
    if manifest.get("status") != "USER_REVIEWED_GOLDEN":
        errors.append("manifest_not_user_reviewed")
    unknown_cases = sorted(set(manifest.get("cases") or ())-ALLOWED_CASES)
    if unknown_cases:
        errors.append("unknown_cases:" + ",".join(unknown_cases))
    artifacts = manifest.get("artifacts") or []
    if not artifacts:
        errors.append("no_artifacts")
    for artifact in artifacts:
        artifact_path = (path.parent / artifact.get("path", "")).resolve()
        try:
            artifact_path.relative_to(path.parent.resolve())
        except ValueError:
            errors.append(f"outside_manifest_directory:{artifact.get('path')}")
            continue
        if not artifact_path.is_file():
            errors.append(f"missing:{artifact.get('path')}")
        elif sha256_file(artifact_path) != artifact.get("sha256"):
            errors.append(f"hash_mismatch:{artifact.get('path')}")
    return {"valid": not errors, "errors": errors, "name": manifest.get("name"),
            "cases": manifest.get("cases") or [], "artifacts": len(artifacts),
            "live": manifest.get("provenance", {}).get("source") == "REAL_WOW_CLIENT"}

