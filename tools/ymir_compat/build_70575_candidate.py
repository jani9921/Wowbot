"""Offline-only, hash-pinned 70448 -> 70575 Ymir compatibility candidate.

Explicitly authorized by the user on 2026-10-25. No process APIs, execution,
injection, input or session material. The two BSS addresses are hypotheses,
not live-validated mappings. This does NOT update the production bridge pin.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import struct


ROOT = Path(__file__).resolve().parents[2]
SOURCE_SHA256 = "f685d3d90d5f73dc8f39ea980cff8e1c92ff0ab66c3c85d425ca29736201b267"
OLD_CLIENT_SHA256 = "1c51e68c00e7183c2c187606d2c443c27252a629406454de4afec336e8c5753a"
NEW_CLIENT_SHA256 = "14b70997cf6c7971a4fcd533b7f421316b6a3da0c8da3710425a8dd20e356a29"
OLD_BUILD, NEW_BUILD = 70448, 70575
SITES = ((0x11A332, 0xBA), (0x11A5BA, 0xBA), (0x11BA3B, 0x3D),
         (0x11CE46, 0xBA), (0x11D2BE, 0xBA))
GLOBAL_SITES = ((0x11E2A3, 0x4ADF710, "capture_root"),
                (0x11C209, 0x4A83198, "locale_index"),
                (0x11C226, 0x3B7E6D0, "locale_table"))
LOCALE_ANCHOR = b"Argument must be an integer of type '{}'"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sections(data: bytes) -> dict:
    pe = struct.unpack_from("<I", data, 0x3C)[0]
    if data[:2] != b"MZ" or data[pe:pe+4] != b"PE\0\0":
        raise ValueError("not a PE image")
    machine, count = struct.unpack_from("<HH", data, pe+4)
    optional_size = struct.unpack_from("<H", data, pe+20)[0]
    if machine != 0x8664 or struct.unpack_from("<H", data, pe+24)[0] != 0x20B:
        raise ValueError("not an AMD64 PE32+ image")
    result = {}
    for index in range(count):
        offset = pe+24+optional_size+index*40
        name = data[offset:offset+8].rstrip(b"\0").decode("ascii")
        size, rva, raw_size, raw_offset = struct.unpack_from("<4I", data, offset+8)
        result[name] = dict(rva=rva, size=size, raw_size=raw_size, raw_offset=raw_offset)
    return result


def locale_table(data: bytes, layout: dict) -> tuple[int, list[str | None]]:
    if data.count(LOCALE_ANCHOR) != 1:
        raise ValueError("locale anchor must be unique")
    offset = data.index(LOCALE_ANCHOR)+0x38
    section = next(s for s in layout.values()
                   if s["raw_offset"] <= offset < s["raw_offset"]+s["raw_size"])
    rva = offset-section["raw_offset"]+section["rva"]
    values = struct.unpack_from("<12Q", data, offset)
    labels = []
    for pointer in values:
        if pointer == 0:
            labels.append(None)
            continue
        target = pointer-0x140000000
        owner = next(s for s in layout.values()
                     if s["rva"] <= target < s["rva"]+s["raw_size"])
        off = target-owner["rva"]+owner["raw_offset"]
        labels.append(data[off:off+5].split(b"\0")[0].decode("ascii"))
    return rva, labels


def derive_addresses(old: bytes, new: bytes) -> tuple[dict, dict]:
    if sha256(old) != OLD_CLIENT_SHA256 or sha256(new) != NEW_CLIENT_SHA256:
        raise ValueError("client reference hash mismatch")
    a, b = sections(old), sections(new)
    ad, bd = a[".data"], b[".data"]
    if (ad["size"], ad["raw_size"]) != (bd["size"], bd["raw_size"]):
        raise ValueError("data section layout size changed; no relative-address hypothesis")
    old_table, old_labels = locale_table(old, a)
    new_table, new_labels = locale_table(new, b)
    expected = ["enUS", "koKR", "frFR", "deDE", "zhCN", "zhTW",
                "esES", "esMX", "ruRU", None, "ptBR", "itIT"]
    if old_table != 0x3B7E6D0 or old_labels != expected or new_labels != expected:
        raise ValueError("locale table structure changed")
    addresses = {"locale_table": new_table}
    for _, old_rva, role in GLOBAL_SITES[:2]:
        relative = old_rva-ad["rva"]
        if not ad["raw_size"] <= relative < ad["size"]:
            raise ValueError("expected BSS address is outside the matched section")
        addresses[role] = bd["rva"]+relative
    evidence = {
        "old_data_section": ad, "new_data_section": bd,
        "data_rva_delta": bd["rva"]-ad["rva"],
        "locale_labels_equal": True,
        "locale_table_evidence": "unique string anchor +0x38; identical 12 locale entries",
        "bss_evidence": "equal raw/virtual section sizes; preserved section-relative offsets ONLY",
        "bss_live_validated": False,
        "direct_code_xrefs_found": False,
    }
    return addresses, evidence


def transform(source: bytes, addresses: dict) -> tuple[bytes, list[dict]]:
    if sha256(source) != SOURCE_SHA256:
        raise ValueError("source Ymir hash mismatch")
    if set(addresses) != {item[2] for item in GLOBAL_SITES}:
        raise ValueError("exactly three reviewed address roles required")
    output = bytearray(source)
    changes = []
    if source.count(struct.pack("<I", OLD_BUILD)) != len(SITES):
        raise ValueError("unexpected build-immediate count")
    for offset, opcode in SITES:
        if (source[offset-1] != opcode
                or struct.unpack_from("<I", source, offset)[0] != OLD_BUILD):
            raise ValueError("build instruction precondition failed")
        struct.pack_into("<I", output, offset, NEW_BUILD)
        changes.append(dict(offset=offset, kind="build", old=OLD_BUILD, new=NEW_BUILD))
    for offset, old, role in GLOBAL_SITES:
        if (source.count(struct.pack("<I", old)) != 1
                or struct.unpack_from("<I", source, offset)[0] != old):
            raise ValueError("client RVA precondition failed")
        struct.pack_into("<I", output, offset, addresses[role])
        changes.append(dict(offset=offset, kind="client_rva", role=role,
                            old=old, new=addresses[role]))
    allowed = {item["offset"]+delta for item in changes for delta in range(4)}
    changed = {i for i, pair in enumerate(zip(source, output)) if pair[0] != pair[1]}
    if len(source) != len(output) or not changed <= allowed:
        raise ValueError("unexpected mutation outside reviewed instruction operands")
    if bytes(output).count(struct.pack("<I", OLD_BUILD)):
        raise ValueError("old build label remains")
    return bytes(output), changes


def create_once(path: Path, data: bytes) -> None:
    if path.exists():
        if path.read_bytes() != data:
            raise ValueError(f"refusing to overwrite different artifact: {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(data)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--old-client", type=Path, required=True)
    parser.add_argument("--new-client", type=Path, required=True)
    args = parser.parse_args()
    source = ROOT/"runtime/ymir/ymir_retail_12.1.5.70448_PORT_CANDIDATE_V2.exe"
    output = ROOT/"runtime/ymir/candidates/70575/ymir_retail_12.1.5.70575_PORT_CANDIDATE.exe"
    addresses, evidence = derive_addresses(args.old_client.read_bytes(), args.new_client.read_bytes())
    raw = source.read_bytes()
    candidate, changes = transform(raw, addresses)
    report = dict(status="STATIC_CANDIDATE_NOT_LIVE_VALIDATED", source_sha256=SOURCE_SHA256,
                  output_sha256=sha256(candidate), old_client_sha256=OLD_CLIENT_SHA256,
                  new_client_sha256=NEW_CLIENT_SHA256, old_build=OLD_BUILD, new_build=NEW_BUILD,
                  executed=False, production_enabled=False, evidence=evidence, changes=changes)
    create_once(output, candidate)
    create_once(output.with_suffix(".exe.manifest.json"),
                (json.dumps(report, indent=2)+"\n").encode("utf-8"))
    if sha256(source.read_bytes()) != SOURCE_SHA256:
        raise ValueError("source changed during generation")
    print(json.dumps({"output": str(output), **report}, indent=2))


if __name__ == "__main__":
    main()
