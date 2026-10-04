"""Offline-checkable V4-084/V4-096/V4-097 documentation contracts."""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_every_required_final_deliverable_exists_and_is_nonempty():
    required = (
        "CHANGELOG.md", "docs/ARCHITECTURE.md", "docs/M0_IMPLEMENTATION.md",
        "docs/M1_QUEST_EXECUTION.md", "docs/MIGRATION.md",
        "docs/DEAD_CODE_AUDIT.md", "docs/TEST_REPORT.md",
        "docs/KNOWN_LIMITATIONS.md",
    )
    for relative in required:
        path = ROOT / relative
        assert path.is_file(), relative
        assert len(path.read_text(encoding="utf-8").strip()) >= 40, relative


def test_validation_ledger_preserves_offline_vs_live_vocabulary():
    ledger = (ROOT / "docs/CURRENT_SOURCE_COVERAGE.md").read_text(encoding="utf-8")
    live = (ROOT / "docs/LIVE_VALIDATION.md").read_text(encoding="utf-8")
    assert "OFFLINE_VERIFIED" in ledger
    assert "OFFLINE_PARTIAL" in ledger
    assert "live-open" in ledger.lower() or "live open" in ledger.lower()
    assert "selected-PID" in live or "selected PID" in live


def test_dead_code_audit_names_isolated_legacy_and_removed_lifecycle_owner():
    audit = (ROOT / "docs/DEAD_CODE_AUDIT.md").read_text(encoding="utf-8")
    assert "SkillLifecycleController" in audit
    assert "removed" in audit.lower()
    assert (ROOT / "src/legacy_logging").is_dir()
    assert not (ROOT / "src/wowbot/agent/skill_lifecycle.py").exists()
