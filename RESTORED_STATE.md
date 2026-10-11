# Reconstructed 2026-09-28 19:18 state

This worktree preserves the requested state after the Retail addon 0.9.36
quest-item-use update and before the later fast-vision/tracker experiments.

- Base snapshot: `3bbc112` (the later Git reconstruction of the 19:35 source)
- Kept: addon 0.9.36 `QUEST_SPECIAL_ITEM_NAME_MATCH` / `USE_ITEM` handling
- Reversed from the local Codex session record: every 19:27--19:33 continuous
  latest-frame detector source/test/tool/documentation patch
- Absent from the base: BoT-SORT/ByteTrack integration (`9734386` and later)
- Default detector behavior: legacy profile-limited cadence

The exact 19:18 filesystem state was not committed at that time. This branch is
reconstructed from the preserved 19:35 snapshot plus the original FileChange
records in the local Codex session. The item-use work finished between
19:12--19:16; the first continuous-detector source patch was recorded at
19:27:01. The reconstruction reverses that later patch series rather than
merely disabling it with an environment default.
