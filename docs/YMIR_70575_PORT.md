# Ymir 70575 address-port evidence — 2026-10-25

> **Update 2026-10-25 10:07 — V3 installed.** The user built a V3 candidate
> (`ymir_retail_12.1.5.70575_PORT_CANDIDATE_V3.exe`, SHA-256
> `77cc8a63b94ee52c47090290a69f3d6fa3db3995ded3c7534c886c85dcbec6b9`, from
> `ymir_retail.exe` `a13220e8…`) with capture root `0x4A50750` (live: vtable
> at P+0, 64-byte window at P+8), locale selector `0x49F4198` and locale
> table `0x3AF06E0`. Its user-run capture (`dump_12.1.0.70575_2026-10-25_10-00-12.pkt`)
> got past the authentication transition and decoded cleanly offline (see
> `LIVE_VALIDATION.md`). It is now in `runtime/ymir/`, pinned by
> `ymir_bridge.py` and started by the GUI. The record below describes the
> earlier, failed `68a8ad1b…` candidate and stays for history.

Status: **LIVE_FAILED / ADDRESS_IDENTITY_UNVERIFIED**. This is not a functional
70575 port. Production 70448 and the original binaries have not been changed.

## Exact artifacts

- Validated 70448 Ymir SHA-256:
  `f685d3d90d5f73dc8f39ea980cff8e1c92ff0ab66c3c85d425ca29736201b267`.
- Installed 70575 `Wow.exe` SHA-256:
  `14b70997cf6c7971a4fcd533b7f421316b6a3da0c8da3710425a8dd20e356a29`.
- Failed 70575 candidate SHA-256:
  `68a8ad1b7927c22e7911cb88d28f72f91f32ea73fddcdb1a40bc61a001f1ca5d`.

The candidate already contains five build-constant replacements and three RVA
replacements. No codec, authentication check, or opcode decoder was changed.

## Address evidence, not assumed correctness

| Role | Working 70448 RVA | Current 70575 hypothesis | Evidence |
| --- | --- | --- | --- |
| Capture root | `0x4ADF710` | `0x4A50710` | Section-relative offset only; identity NOT established |
| Locale selector | `0x4A83198` | `0x49F4198` | Section-relative offset only; identity NOT established |
| Locale pointer table | `0x3B7E6D0` | `0x3AF06E0` | Unique static anchor and identical 12 locale entries |

Equal `.data` raw/virtual sizes do not prove that variables retained their
relative positions. The earlier 70448 V1 root also came from such an assumption
and required correction. The 70575 regression tests establish byte-level patch
scope and reproducibility; they do NOT establish semantic identity of the two
BSS variables or successful capture.

Static inspection of the installed file found no validated instruction
references resolving these two identities. `Wow.exe` imports `Wow_loader.dll`;
its on-disk `.text` entropy is approximately 7.9998 bits/byte. This is consistent
with a transformed on-disk code representation, not proof of a particular
protection algorithm. No loader/unpacker was executed, no protection check was
bypassed, and no client memory or session material was read during this audit.

## Observed user-run failures

The existing reports in these directories each contain four records, no
recognized gameplay opcode, and Ymir exit code zero:

- `output/compat/ymir-70575/test-20261025-085833-250834/status.json`
- `output/compat/ymir-70575/test-20261025-090020-742264/status.json`

Those four records end at the authentication/encryption transition. The user
confirmed that WoW also closes with the candidate, while WoW without Ymir works.
The exact triggering error was not preserved by the test runner's allowlist;
the absent error text must not be reconstructed by guesswork. Later WoW logs
belong to a different launch. No corresponding Windows crash event was found.

## Current scope and next gate

The user's latest direction is to correct the two addresses, not change Ymir's
termination behavior. **No termination-handler patch was applied.** No new
candidate was generated or executed during this follow-up.

The two addresses remain unverified; a guessed second displacement is not an
acceptable repair. Further live inspection requires a running, explicitly
selected 70575 PID and a narrowly authorized read-only inspection scope. Do not
extract/export session material, patch the client, inject code, weaken validation,
or start FULL_AI. Do not claim compatibility until a subsequent user-run capture
and allowlisted semantic checks actually succeed.
