"""Compatibility bookkeeping after one command batch crosses dispatch."""
from __future__ import annotations

from .interaction_range import recently_verified_in_range

from dataclasses import dataclass

from .models import Attempt, Outcome, Proposal


_MOVEMENT_SKILLS = frozenset({"MOVE", "FOLLOW", "REACH_OBJECT", "REACH_LOCATION"})


def _possible_quest_npc_or_out_of_range(state: dict, guid: str) -> bool:
    """Whether a silent INTERACT says nothing about the NPC having nothing to offer.

    Live 2026-09-30 09:12: a user-selected Lady Jaina (quest '!' visible) was
    interacted with from far away; the silent failure blacklisted her for
    300 s, so later exact mouseovers of her were never targeted.
    """
    from .target_planning import interaction_out_of_range

    if interaction_out_of_range(state):
        return True
    from .quest_giver_evidence import npc_shows_quest_symbol
    if npc_shows_quest_symbol(state, guid):
        return True
    target = state.get("target") or {}
    if target.get("quest_role") in {"QUEST_GIVER", "QUEST_TURN_IN"}:
        return True
    anchor = (state.get("confirmed_mouseover_anchors") or {}).get(guid) or {}
    track_ids = {str(value) for value in (anchor.get("track_id"), target.get("visual_track_id")) if value}
    for candidate in state.get("visual_candidates") or ():
        if not isinstance(candidate, dict) or str(candidate.get("track_id")) not in track_ids:
            continue
        group = candidate.get("visual_group") if isinstance(candidate.get("visual_group"), dict) else {}
        if str(group.get("belief") or "").upper() == "SUPPORTED":
            return True
    return False


@dataclass(frozen=True)
class TerminalBookkeeping:
    recovery_resume: Proposal | None


class ExecutionBookkeeper:
    """Update bounded planner diagnostics; never execute or verify a skill."""

    def record(self, proposal, now: float, *, planner,
               approach_counts: dict) -> None:
        if proposal.skill in {"APPROACH_TARGET", "VISUAL_APPROACH"}:
            guid = proposal.parameters.get("guid")
            approach_counts[guid] = approach_counts.get(guid, 0) + 1
        if proposal.skill == "INSPECT":
            if proposal.parameters.get("camera_pan"):
                planner.camera_search_step += 1
                planner.camera_search_next_at = now + .75
            if proposal.parameters.get("map_zoom_in"):
                planner.map_zoom_count += 1
                planner.map_zoom_requested = False
            if proposal.parameters.get("map_step_out"):
                planner.map_search_policy.state.step_out_attempts += 1
            on_map = proposal.parameters.get("source") in {"MINIMAP_CV", "WORLD_MAP_CV"}
            if proposal.parameters.get("source") == "WORLD3D":
                planner.world3d_probe_count += 1
            planner.recent[proposal.key] = now + (
                30 if on_map or proposal.parameters.get("kind") == "object_candidate" else 5)
            if (proposal.parameters.get("source") == "WORLD_MAP_CV"
                    and not proposal.parameters.get("map_zoom_in")):
                planner.map_probes += 1
        if proposal.skill in {"CAMERA_CONTROL", "REACQUIRE_TARGET"}:
            planner.camera_search_step += 1
            planner.camera_search_next_at = now + .35
        if proposal.skill == "OPEN_MAP":
            planner.recent[proposal.key] = now + 30
            # This gate is keyed by the skill/search session, not Proposal.key.
            # Live PID 1468 produced two consecutive failed OPEN_MAP attempts:
            # the first carried a committed GUID and the second did not, so
            # the existing key-specific cooldown was bypassed. Start the gate
            # once input actually crosses dispatch, regardless of whether
            # delayed telemetry later verifies that the map opened.
            planner.map_search_policy.state.reopen_blocked_until = max(
                planner.map_search_policy.state.reopen_blocked_until, now + 30.)

    def record_terminal(self, attempt: Attempt, outcome: Outcome, reason: str,
                        now: float, *, planner, world,
                        recovery_resume: Proposal | None) -> TerminalBookkeeping:
        """Project terminal compatibility facts without finishing the skill."""
        skill = attempt.proposal.skill
        parameters = attempt.proposal.parameters
        if (skill == "SEEK_VISUAL_CUE" and outcome == Outcome.FAILURE
                and reason in {"seek_visual_cue_sectors_exhausted",
                               "seek_visual_cue_safety_deadline"}):
            planner.camera_search_step = 4
            planner.camera_search_next_at = now
        planner.map_search_policy.on_terminal(
            attempt, outcome, reason, planner.quest)
        if (skill == "MOVE" and outcome == Outcome.FAILURE
                and reason in {"supported_stuck", "movement_safety_deadline"}):
            planner.quest.failed_map_locations.add(attempt.proposal.key)
        if (skill in _MOVEMENT_SKILLS and outcome == Outcome.FAILURE
                and reason == "supported_stuck"):
            recovery_resume = attempt.proposal
        if (skill == "MOVE" and outcome == Outcome.SUCCESS
                and parameters.get("quest_id") is not None):
            planner.quest.mark_location_reached(parameters, world.state)
        dungeon = getattr(planner, "dungeon", None)
        if skill == "MOVE" and outcome == Outcome.SUCCESS and dungeon is not None:
            dungeon.map_pois.mark_reached(parameters, now)
        if skill in {"INTERACT", "TALK", "QUEST_DIALOG"} and outcome == Outcome.SUCCESS:
            guid = parameters.get("guid") or (world.state.get("target") or {}).get("guid")
            if guid:
                planner.quest.interacted_guids[guid] = world.quest_signature(world.state)
                planner.quest.interacted_at[guid] = now
        if (skill in {"VISUAL_APPROACH", "APPROACH_TARGET"} and outcome == Outcome.SUCCESS
                and parameters.get("purpose") in {None, "INTERACT"}):
            # Standing next to the unit is new evidence: an earlier silent
            # INTERACT from far away says nothing about it.  Clear the range
            # block (otherwise VISUAL_APPROACH is re-proposed until the
            # approach budget stops FULL_AI, live 2026-09-30) and any
            # unresponsive verdict so INTERACT is proposed next.
            guid = str(parameters.get("guid") or (world.state.get("target") or {}).get("guid") or "")
            if guid:
                planner.quest.interaction_range_blocks.pop(guid, None)
                planner.quest.unresponsive_guids.pop(guid, None)
                verified = getattr(planner.quest, "approach_verified_at", None)
                if isinstance(verified, dict):
                    verified[guid] = now
        if (skill in {"INTERACT", "TALK"} and outcome == Outcome.FAILURE
                and reason in {"no_response", "expected_observation_missing"}
                and not world.state.get("active_quests")):
            # Questing with no active quest: a friendly NPC without a "!" that
            # offers nothing is skipped for a while (user 2026-10-02, Kee-La
            # took ~45 s).  A "!"-NPC keeps the cautious rule below: its
            # silence may only mean "out of range".
            from .quest_giver_evidence import npc_shows_quest_symbol
            target = world.state.get("target") or {}
            guid = str(parameters.get("guid") or target.get("guid") or "")
            state_time = world.state.get("monotonic_time")
            if (guid and target.get("attackable", target.get("is_attackable")) is not True
                    and not npc_shows_quest_symbol(world.state, guid)):
                planner.quest.__dict__.setdefault("not_quest_giver_at", {})[guid] = (
                    float(state_time) if isinstance(state_time, (int, float)) else now)
        if skill == "INTERACT" and outcome == Outcome.FAILURE and reason == "no_response":
            target = world.state.get("target") or {}
            guid = parameters.get("guid") or target.get("guid")
            state_time = world.state.get("monotonic_time")
            ranged_at = (getattr(planner.quest, "out_of_range_at", {}) or {}).get(guid)
            recently_out_of_range = guid in getattr(planner.quest, "out_of_range_at", {}) and (
                ranged_at is None or not isinstance(state_time, (int, float))
                or state_time-ranged_at <= 120.)
            # Only a silent INTERACT after range was verified by an approach
            # means "nothing to offer"; otherwise it is a probable range miss.
            if (guid and target.get("attackable", target.get("is_attackable")) is not True
                    and recently_verified_in_range(planner.quest, guid, now)
                    and not recently_out_of_range
                    and not _possible_quest_npc_or_out_of_range(world.state, guid)):
                state_time = world.state.get("monotonic_time")
                planner.quest.unresponsive_guids[guid] = (
                    world.quest_signature(world.state),
                    float(state_time) if isinstance(state_time, (int, float)) else None)
        return TerminalBookkeeping(recovery_resume)
