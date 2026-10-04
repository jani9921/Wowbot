# M0 Phase E — visual approach ownership

Status: **offline-tested; not live-validated.**

`VISUAL_APPROACH` now runs through `wowbot.skills.VisualApproachSkill`. The
existing `VisualApproachController` remains the proven visual-servo algorithm,
but is constructed once per active attempt and kept in
`ActiveSkillRuntime.skill_context`. The engine's `visual_approach` property is
only a compatibility diagnostics projection.

This migration intentionally changes no steering threshold, movement pulse,
camera behavior, or target-recognition policy. It only removes a second
long-lived lifecycle owner, so cancellation/finalization also drops the servo
state. Targeted tests: **56 passed**.
