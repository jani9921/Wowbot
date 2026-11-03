# REV4 P1-E–P9 checkpoint

Offline-only checkpoint, 2026-10-30. See ../P1E_P9_IMPLEMENTATION.md for scope,
missing implementations and user-live gates. Baseline is the P1-E starting
state, already containing P1-D; it is retained separately from current code.

- baseline.zip/json: scoped original source/tests/addon/docs and hashes.
- implementation-current.zip/current-files.json: current matching files/hashes.
- changes.json/implementation.patch: exact changed/new files and readable diff.
- verification.json: AST, 203 preserved coverage rows, pinned backend hash and test summary.
- combined-command.json/run_combined_3.py: exact selected regression and unchanged ten exclusions.
- combined-6.log/JUnit: 3682 pass, 2 absent optional fixtures, 10 unchanged deselections.
- combined-1/2 logs: earlier broad run failure/fix history, not added to final pass count.
- boundary-final.log: 102 overlapping targeted passes.
- benchmark-p1e-p9.json/benchmark_evidence.py: synthetic timings, not live FPS.

Restore or compare inside the existing project using a reviewed file list;
the archives exclude memory databases, images, live telemetry, local auth/
session material and user configuration. Removing newly added files is a
separate reviewed operation; extracting baseline alone does not remove them.
No game process was started or controlled by the assistant; addon 0.9.80 is installed after a backed-up Lua 5.1 fix; user /reload proof is pending.
