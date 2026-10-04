# M0 Phase D — bounded visual search

Status: **offline-tested; not live-validated.**

`SEEK_VISUAL_CUE` is now entered through `wowbot.skills.SearchSkill`.
The existing four-sector camera scan and optional visual-servo approach were
preserved, but their mutable `SeekVisualCueController` is created per attempt
and stored inside `ActiveSkillRuntime.skill_context`. Therefore cancellation or
terminal finalization cannot leave a long-lived engine-owned search controller
behind.

The skill remains bounded by its existing scan-sector and time budgets. It
returns typed terminal failures at the M0 boundary while preserving the legacy
reason in metadata for existing planner fallback routing. `agent.vision_seek`
is now a read-only diagnostic compatibility projection only.

Targeted regression after the migration: **138 passed**. Full live M0 search
acceptance still requires the replay matrix and a user-operated client test.
