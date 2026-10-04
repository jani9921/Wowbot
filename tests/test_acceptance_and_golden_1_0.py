import hashlib
import json

from wowbot.agent.acceptance import AcceptanceAccumulator
from wowbot.agent.golden_sessions import verify_golden_manifest


def test_live_acceptance_requires_safe_handoff_and_no_thrash():
    value = AcceptanceAccumulator(0)
    for index in range(12):
        value.update({"mode": "FULL_AI", "fresh": True, "runtime_error": None,
                      "phase": "APPROACHING", "replan_revision": 1,
                      "result": {}, "session_id": "live-session"},
                     {"input_safety": {"held_key_count": 1}})
    value.update({"mode": "MANUAL", "fresh": True, "runtime_error": None,
                  "phase": "IDLE", "replan_revision": 1,
                  "result": {}, "session_id": "live-session"},
                 {"input_safety": {"held_key_count": 0}})
    report = value.report(ended_at=3600, final_summary={"mode": "MANUAL", "session_id": "live-session"},
                          final_status={"input_safety": {"held_key_count": 0}},
                          required_duration=3600)
    assert report["result"] == "PASS"
    assert all(report["gates"].values())


def test_live_acceptance_rejects_off_duration_full_ai_handoff():
    value = AcceptanceAccumulator(0)
    value.update({"mode": "FULL_AI", "fresh": False, "runtime_error": "boom",
                  "phase": "RECOVERING", "result": {}, "replan_revision": 1},
                 {"input_safety": {"held_key_count": 1}})
    report = value.report(ended_at=10, final_summary={"mode": "FULL_AI"},
                          final_status={"input_safety": {"held_key_count": 1}},
                          required_duration=3600)
    assert report["result"] == "FAIL"
    assert report["gates"]["duration_reached"] is False
    assert report["gates"]["safe_handoff_not_full_ai"] is False


def test_golden_manifest_is_hash_locked_and_requires_user_review(tmp_path):
    artifact = tmp_path / "session.jsonl"
    artifact.write_text('{"real":"capture"}\n', encoding="utf-8")
    digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
    manifest = tmp_path / "golden.json"
    manifest.write_text(json.dumps({
        "name": "jaina-live", "status": "USER_REVIEWED_GOLDEN",
        "cases": ["quest_giver", "unknown_marker"],
        "provenance": {"source": "REAL_WOW_CLIENT"},
        "artifacts": [{"path": "session.jsonl", "sha256": digest}],
    }), encoding="utf-8")
    assert verify_golden_manifest(manifest) == {
        "valid": True, "errors": [], "name": "jaina-live",
        "cases": ["quest_giver", "unknown_marker"], "artifacts": 1, "live": True}
    artifact.write_text("mutated", encoding="utf-8")
    assert verify_golden_manifest(manifest)["valid"] is False
