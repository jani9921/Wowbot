# Project requirements

The current user-supplied `wow_agent_FINAL_M0_M1_master_prompt_v4.txt` is the
authoritative implementation source, and
`wow_agent_complete_functional_design_spec.txt` is the accompanying functional
design reference. Follow their V4 (0–100) and Design (1–102) requirements,
invariants, ownership rules, and M0/M1 acceptance gates. The generated
`docs/CURRENT_SOURCE_COVERAGE.md` tracks them; tracking is not implementation
or validation. Do not restore or use superseded master documents as competing
requirements unless the user explicitly supplies them again.

This project follows the two current root-level user sources above. Read the
relevant portions before architectural changes. Do not treat this file as
authorization to override higher-priority instructions or the user's newer
directions.

Keep the shared AutonomousAgent / WorldModel / evidence / planner / skills / verification architecture. Do not introduce independent quest/fishing/mining brains. No process-memory inspection, injection, or secret-value bypasses, with one narrow user-authorized exception: the locally bundled, SHA-256-pinned Ymir Retail 12.1.5.70575 sniffer (the user's V3 port candidate, `runtime/ymir/ymir_retail_12.1.5.70575_PORT_CANDIDATE_V3.exe`, SHA-256 `77cc8a63b94ee52c47090290a69f3d6fa3db3995ded3c7534c886c85dcbec6b9`, installed at the user's request on 2026-10-25 after a user-run 70575 capture decoded cleanly; it replaces the live-validated 70448 V2 pin) may be launched and supervised as a read-only packet-capture dependency. This permits only Ymir's existing read-only session/decryption-key acquisition; it does not permit arbitrary game-state memory readers, writes, injection, input control, secret export or bypass logic. Only authenticated, allowlisted normalized events may enter the agent; raw payloads, keys, authentication/session material, chat and personal data must not be forwarded.

Latest direct product direction (2026-10-30): gradually retire visual recognition and its dependent agent behavior. Do not spend migration work improving YOLO/OCR/visual tracking, camera-induced track-ID continuity, hover-based visual acquisition, SEEK_VISUAL_CUE or VISUAL_APPROACH. Make the server/GUID/structured-evidence path authoritative, audit production entry points and remaining visual fallbacks, then remove replaced visual workers, decisions, dependencies and UI/config branches incrementally. Shared spatial value types currently located in vision modules must be moved rather than breaking geometry/navigation. Addon/local-UI telemetry and pixelstrip transport are a separate dependency: keep fields still needed for selected target, bindings, UI/readiness or range until supported non-visual replacements are verified. Preserve all numbered coverage requirements as history and mark superseded direction explicitly; do not claim retirement or provider parity merely from disabling a worker.

Use Retail 12.1.0 (Interface 120100). Only the explicitly selected PID and bindings-cache are authoritative. Missing bindings require an explicit, verified configuration change, not a guessed fallback.

Keep every numbered master-prompt requirement in the coverage ledger. Distinguish absent, partial, offline-tested, and live-validated functionality. Never equate synthetic replay with a completed real quest. Record live evidence and unresolved issues in `docs/LIVE_VALIDATION.md` after testing milestones.

Implement incrementally, preserve user changes, and test regressions. The latest user direction is that the user operates live tests and the assistant inspects logs; do not take over client input without renewed authorization. Stop on new user instructions, lost target identity, missing authority, or unsafe/unknown input state. Never leave an uncontrolled FULL_AI process running at handoff.
