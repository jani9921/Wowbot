"""Offline candidate integrity only. No process/capture/game execution."""
import hashlib
from pathlib import Path
import struct
from types import SimpleNamespace

import pytest

from tools.ymir_compat import build_70575_candidate as port
from tools.ymir_compat import test_candidate as runner


@pytest.fixture
def synthetic_source(monkeypatch):
    source = bytearray(0x120000)
    for offset, opcode in port.SITES:
        source[offset-1] = opcode
        struct.pack_into("<I", source, offset, port.OLD_BUILD)
    for offset, old, _ in port.GLOBAL_SITES:
        struct.pack_into("<I", source, offset, old)
    source = bytes(source)
    monkeypatch.setattr(port, "SOURCE_SHA256", port.sha256(source))
    return source


def addresses():
    return {"capture_root": 0x4A50710, "locale_index": 0x49F4198,
            "locale_table": 0x3AF06E0}


def test_changes_are_only_the_eight_reviewed_operands(synthetic_source):
    output, changes = port.transform(synthetic_source, addresses())
    assert len(output) == len(synthetic_source)
    allowed = {c["offset"]+i for c in changes for i in range(4)}
    actual = {i for i, (a,b) in enumerate(zip(synthetic_source, output)) if a != b}
    assert actual <= allowed and len(changes) == 8
    for offset, opcode in port.SITES:
        assert output[offset-1] == opcode
        assert struct.unpack_from("<I", output, offset)[0] == 70575
    for offset, _, role in port.GLOBAL_SITES:
        assert struct.unpack_from("<I", output, offset)[0] == addresses()[role]


def test_unpinned_source_is_rejected():
    with pytest.raises(ValueError, match="hash mismatch"):
        port.transform(b"not the reviewed binary", addresses())


def test_missing_address_is_not_guessed(synthetic_source):
    with pytest.raises(ValueError, match="three reviewed"):
        port.transform(synthetic_source, {"capture_root": 0x4A50710})


def test_reference_hashes_are_mandatory():
    with pytest.raises(ValueError, match="reference hash"):
        port.derive_addresses(b"old", b"new")


def test_create_once_preserves_existing_artifacts(tmp_path):
    destination = tmp_path/"candidate.exe"
    port.create_once(destination, b"first")
    port.create_once(destination, b"first")
    with pytest.raises(ValueError, match="refusing to overwrite"):
        port.create_once(destination, b"second")
    assert destination.read_bytes() == b"first"


@pytest.mark.parametrize("line", ["Session key: PRIVATE", "Chat: PRIVATE",
                                 "account: PRIVATE", "arbitrary console text"])
def test_unrecognized_console_text_is_not_retained(line):
    assert runner.safe_console_event(line) is None


@pytest.mark.parametrize("line", ["Memory::ReadBytes: PRIVATE",
                                 "System.ArgumentNullException: PRIVATE",
                                 "Dont have a key to use for decrypt"])
def test_errors_are_classified_without_copying_contents(line):
    assert runner.safe_console_event(line) == ("capture_error", "CLIENT_INTEGRATION_FAILED")


def test_test_runner_checks_metadata_before_any_capture(monkeypatch, tmp_path):
    candidate = tmp_path/"candidate.exe"
    candidate.write_bytes(b"candidate")
    monkeypatch.setattr(runner, "CANDIDATE", candidate)
    monkeypatch.setattr(runner, "CANDIDATE_SHA256", hashlib.sha256(b"candidate").hexdigest())
    monkeypatch.setattr(runner, "process_list", lambda: [("Wow.exe", 77)])
    monkeypatch.setattr(runner, "check_client", lambda pid: (_ for _ in ()).throw(ValueError("build mismatch")))
    monkeypatch.setattr(runner.subprocess, "Popen", lambda *a, **kw: pytest.fail("must not launch"))
    with pytest.raises(ValueError, match="build mismatch"):
        runner.run(77, 120)


@pytest.mark.parametrize("processes", [[("Wow.exe", 77), ("Wow.exe", 88)],
                                      [("Wow.exe", 88)],
                                      [("Wow.exe", 77), ("ymir_old.exe", 12)]])
def test_test_runner_rejects_ambiguous_or_competing_processes(monkeypatch, tmp_path, processes):
    candidate = tmp_path/"candidate.exe"
    candidate.write_bytes(b"candidate")
    monkeypatch.setattr(runner, "CANDIDATE", candidate)
    monkeypatch.setattr(runner, "CANDIDATE_SHA256", hashlib.sha256(b"candidate").hexdigest())
    monkeypatch.setattr(runner, "process_list", lambda: processes)
    monkeypatch.setattr(runner, "check_client", lambda pid: pytest.fail("no metadata lookup needed"))
    monkeypatch.setattr(runner.subprocess, "Popen", lambda *a, **kw: pytest.fail("must not launch"))
    with pytest.raises(ValueError):
        runner.run(77, 120)


def test_real_candidate_matches_manifest_without_execution():
    candidate = runner.CANDIDATE
    if not candidate.exists():
        pytest.skip("private generated binary is not a repository fixture")
    source = port.ROOT/"runtime/ymir/ymir_retail_12.1.5.70448_PORT_CANDIDATE_V2.exe"
    expected, _ = port.transform(source.read_bytes(), addresses())
    assert candidate.read_bytes() == expected
    assert port.sha256(expected) == runner.CANDIDATE_SHA256
    assert port.sha256(source.read_bytes()) == port.SOURCE_SHA256


def test_real_client_reference_maps_only_reviewed_builds():
    old = port.ROOT/"output/compat/ymir-70575/reference/Wow-70448.exe"
    new = Path(r"C:\Program Files (x86)\World of Warcraft\_retail_\Wow.exe")
    if not old.exists() or not new.exists():
        pytest.skip("private reference images unavailable")
    raw = new.read_bytes()
    if port.sha256(raw) != port.NEW_CLIENT_SHA256:
        pytest.skip("installed client has since updated")
    mapped, evidence = port.derive_addresses(old.read_bytes(), raw)
    assert mapped == addresses()
    assert evidence["bss_live_validated"] is False
    assert evidence["locale_labels_equal"] is True
