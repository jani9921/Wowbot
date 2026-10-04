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

Keep the shared AutonomousAgent / WorldModel / evidence / planner / skills / verification architecture. Do not introduce independent quest/fishing/mining brains or discard existing working detectors. No process-memory inspection, injection, or secret-value bypasses.

Use Retail 12.1.0 (Interface 120100). Only the explicitly selected PID and bindings-cache are authoritative. Missing bindings require an explicit, verified configuration change, not a guessed fallback.

Keep every numbered master-prompt requirement in the coverage ledger. Distinguish absent, partial, offline-tested, and live-validated functionality. Never equate synthetic replay with a completed real quest. Record live evidence and unresolved issues in `docs/LIVE_VALIDATION.md` after testing milestones.

Implement incrementally, preserve user changes, and test regressions. The latest user direction is that the user operates live tests and the assistant inspects logs; do not take over client input without renewed authorization. Stop on new user instructions, lost target identity, missing authority, or unsafe/unknown input state. Never leave an uncontrolled FULL_AI process running at handoff.
