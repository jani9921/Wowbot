"""Explicit WPP build families; never infer compatibility by proximity.

Verified against TrinityCore/WowPacketParser commit
1a72288ca3fab3363b99965d5e9782b99cd6803b, Enums/Version/Opcodes.cs.
Opcode-table sharing does NOT prove every payload layout is identical.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class OpcodeFamily:
    defining_build: int
    namespace: str
    sha256: str
    builds: frozenset[int]


WPP_REVISION = "1a72288ca3fab3363b99965d5e9782b99cd6803b"
# Retain the original default for callers analysing 12.1.0 captures.
OPCODE_DEFINING_BUILD = 69214
# UTF-8, BOM removed, CRLF normalized to LF. External tables must match.
OPCODE_TABLE_SHA256 = "5e4387ac682620c7ca45013fa554ad14ca8e619d8a9fe45ce5ceb8f33519ef2c"
OPCODE_FAMILIES = (
    OpcodeFamily(69214, "V12_1_0_69214", OPCODE_TABLE_SHA256, frozenset({
        69214, 69273, 69283, 69299, 69323, 69382, 69404,
        69465, 69497, 69587, 69814, 69875, 69933,
    })),
    OpcodeFamily(70340, "V12_1_5_70340",
        "dcb59d20e7def7014a20b8708b5ca6c6089aa97cab497e9dac6d25ec0a47bcc0",
        # WPP explicitly aliases 70448 to the 70340 opcode table. Payload
        # prefixes remain independently golden-tested before promotion.
        # 70575: aliased too at WPP 44df9d5b (same table SHA-256); a user-run
        # 70575 capture decoded byte-exact on 2026-10-25.  70529 is aliased
        # by WPP but never captured here, so it stays out.
        frozenset({70340, 70391, 70448, 70575})),
)
VERIFIED_OPCODE_BUILDS = frozenset(build for family in OPCODE_FAMILIES for build in family.builds)


def opcode_family(game_build):
    return next((family for family in OPCODE_FAMILIES if game_build in family.builds), None)


def compatible_opcode_build(table_build, capture_build):
    family = opcode_family(capture_build)
    return table_build == capture_build or bool(family and table_build == family.defining_build)
