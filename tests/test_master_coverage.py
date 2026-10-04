from pathlib import Path

from tools.build_requirements_ledger import SOURCES, requirements


def test_every_current_user_source_section_is_tracked():
    entries = list(requirements())
    assert len(entries) == 372
    assert len({entry["id"] for entry in entries}) == 372
    ledger = (Path(__file__).resolve().parents[1] / "docs" / "CURRENT_SOURCE_COVERAGE.md").read_text(encoding="utf-8")
    for entry in entries:
        assert f"| {entry['id']} |" in ledger


def test_all_current_authoritative_sources_are_structurally_complete():
    for prefix, path, expected_count, _ in SOURCES:
        assert path.is_file(), f"missing current source: {path.name}"
        source_entries = [entry for entry in requirements() if entry["id"].startswith(f"{prefix}-")]
        assert len(source_entries) == expected_count
