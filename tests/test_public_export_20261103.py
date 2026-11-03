"""Public exports must keep source fixtures and omit machine/runtime material."""
from pathlib import Path

import pytest

from tools import export_packages as exporter


def test_github_export_filters_runtime_and_secret_files(tmp_path, monkeypatch):
    keep = ["src/wowbot/example.py", "tests/fixtures/sample.jsonl",
            "tests/fixtures/sample.png", "examples/bindings-cache.example.wtf",
            "docs/result.json", "addon/AIPC_Export/AIPC_Export.lua"]
    omit = ["config/wow_password.txt", "config/wow_account.txt",
            "config/local_env.bat", "config/reference_catalog.local.json",
            "output/agent/profiles/user/agent_memory.sqlite3",
            "runtime/ymir/interface.cfg", "runtime/ymir/current.exe",
            "runtime/ymir/dumps/live.pkt", "captures/live.pcapng",
            "data/client_supplement.sqlite3", "data/client_supplement.sqlite3-wal",
            "docs/evidence/before.zip", "src.zip", ".env", "config/.env.local",
            "examples/bindings-cache-pid-123-abc.wtf", "native/WowPacketParser/private.txt",
            "native/db2_exporter/obj/project.assets.json", "native/db2_exporter/bin/app.exe"]
    for rel in keep + omit:
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("fixture", encoding="utf-8")
    monkeypatch.setattr(exporter, "ROOT", tmp_path)
    assert {rel for _, rel in exporter.iter_files("github")} == set(keep)


def test_github_export_does_not_delete_existing_checkout(tmp_path, monkeypatch):
    monkeypatch.setattr(exporter, "EXPORT", tmp_path)
    head = tmp_path / "github" / "Wowbot" / ".git" / "HEAD"
    head.parent.mkdir(parents=True)
    head.write_text("ref: refs/heads/main\n", encoding="utf-8")
    with pytest.raises(FileExistsError):
        exporter.build_github("Wowbot")
    assert head.read_text(encoding="utf-8") == "ref: refs/heads/main\n"


@pytest.mark.parametrize("name", ["../outside", "nested/tree", r"nested\tree", "..", ""])
def test_export_rejects_names_outside_staging(tmp_path, monkeypatch, name):
    monkeypatch.setattr(exporter, "EXPORT", tmp_path)
    with pytest.raises(ValueError):
        exporter.build_github(name)
    assert list(tmp_path.iterdir()) == []
