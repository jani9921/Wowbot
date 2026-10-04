from types import SimpleNamespace

from wowbot.agent.execution_bookkeeping import ExecutionBookkeeper
from wowbot.agent.models import Outcome, Proposal


def planner():
    return SimpleNamespace(
        camera_search_step=0, camera_search_next_at=0., map_zoom_count=0,
        map_zoom_requested=True, world3d_probe_count=0, map_probes=0,
        recent={}, map_search_policy=SimpleNamespace(
            state=SimpleNamespace(reopen_blocked_until=0.)))


def test_world3d_inspection_updates_only_bounded_diagnostics():
    value, counts = planner(), {}
    proposal = Proposal.make("INSPECT", "probe", {"source": "WORLD3D"})
    ExecutionBookkeeper().record(proposal, 10., planner=value, approach_counts=counts)
    assert value.world3d_probe_count == 1
    assert value.recent[proposal.key] == 15.
    assert counts == {}


def test_world_map_inspection_records_zoom_and_long_cooldown():
    value = planner()
    proposal = Proposal.make(
        "INSPECT", "map", {"source": "WORLD_MAP_CV", "map_zoom_in": True})
    ExecutionBookkeeper().record(proposal, 10., planner=value, approach_counts={})
    assert value.map_zoom_count == 1
    assert value.map_zoom_requested is False
    assert value.recent[proposal.key] == 40.


def test_visual_approach_attempt_count_is_keyed_by_guid():
    counts = {}
    ExecutionBookkeeper().record(
        Proposal.make("VISUAL_APPROACH", "go", {"guid": "npc"}), 1.,
        planner=planner(), approach_counts=counts)
    assert counts == {"npc": 1}


def test_open_map_dispatch_starts_skill_level_reopen_cooldown():
    value = planner()
    first = Proposal.make(
        "OPEN_MAP", "committed", {"guid": "npc", "purpose": "LOCATE_COMMITTED_TARGET"})

    ExecutionBookkeeper().record(
        first, 10., planner=value, approach_counts={})

    assert value.recent[first.key] == 40.
    assert value.map_search_policy.state.reopen_blocked_until == 40.


class Quest:
    def __init__(self):
        self.failed_map_locations = set()
        self.interacted_guids = {}
        self.interacted_at = {}
        self.unresponsive_guids = {}
        self.out_of_range_at = {}
        self.interaction_range_blocks = {}
        self.approach_verified_at = {}
        self.reached = []

    def mark_location_reached(self, parameters, state):
        self.reached.append((parameters, state))


class MapSearch:
    def __init__(self):
        self.terminals = []

    def on_terminal(self, attempt, outcome, reason, quest):
        self.terminals.append((attempt, outcome, reason, quest))


class World:
    def __init__(self, state):
        self.state = state

    @staticmethod
    def quest_signature(state):
        return f"signature:{state.get('map_id')}"


def attempt(skill, parameters=None):
    return SimpleNamespace(proposal=Proposal.make(skill, "test", parameters))


def terminal_planner():
    return SimpleNamespace(
        camera_search_step=0, camera_search_next_at=0.,
        map_search_policy=MapSearch(), quest=Quest())


def test_terminal_bookkeeping_retains_supported_stuck_reach_for_recovery():
    value = terminal_planner()
    failed = attempt("REACH_LOCATION", {"x": .4, "y": .5})

    result = ExecutionBookkeeper().record_terminal(
        failed, Outcome.FAILURE, "supported_stuck", 10.,
        planner=value, world=World({"map_id": 2175}),
        recovery_resume=None)

    assert result.recovery_resume is failed.proposal
    assert value.map_search_policy.terminals[0][:3] == (
        failed, Outcome.FAILURE, "supported_stuck")


def test_terminal_bookkeeping_unlocks_map_fallback_after_complete_seek():
    value = terminal_planner()
    seek = attempt("SEEK_VISUAL_CUE")

    ExecutionBookkeeper().record_terminal(
        seek, Outcome.FAILURE, "seek_visual_cue_sectors_exhausted", 12.,
        planner=value, world=World({}), recovery_resume=None)

    assert value.camera_search_step == 4
    assert value.camera_search_next_at == 12.


def test_terminal_bookkeeping_records_reached_and_interacted_quest_context():
    value = terminal_planner()
    world = World({"map_id": 2175, "target": {"guid": "Creature-42"}})
    move = attempt("MOVE", {"quest_id": 701, "x": .4, "y": .5})
    dialog = attempt("QUEST_DIALOG")

    ExecutionBookkeeper().record_terminal(
        move, Outcome.SUCCESS, "arrived", 2., planner=value,
        world=world, recovery_resume=None)
    ExecutionBookkeeper().record_terminal(
        dialog, Outcome.SUCCESS, "accepted", 3., planner=value,
        world=world, recovery_resume=None)

    assert value.quest.reached == [(move.proposal.parameters, world.state)]
    assert value.quest.interacted_guids == {
        "Creature-42": "signature:2175"}
    assert value.quest.interacted_at == {"Creature-42": 3.}


def test_unresponsive_friendly_interact_is_recorded_but_hostile_is_not():
    """Live 2026-09-30: Kee-La gave no response three times in 26 s.

    Silence counts as "nothing to offer" only once a visual approach has
    verified interaction range (Retail exports no NPC distance); a far silent
    INTERACT is a probable range miss (live 13:42, Lady Jaina).
    """
    value = terminal_planner()
    friendly = World({"map_id": 2175, "monotonic_time": 50.,
                      "target": {"guid": "Creature-kee-la", "attackable": False}})
    ExecutionBookkeeper().record_terminal(
        attempt("INTERACT", {"guid": "Creature-kee-la"}), Outcome.FAILURE, "no_response", 5.,
        planner=value, world=friendly, recovery_resume=None)
    assert value.quest.unresponsive_guids == {}
    ExecutionBookkeeper().record_terminal(
        attempt("VISUAL_APPROACH", {"guid": "Creature-kee-la", "purpose": "INTERACT"}),
        Outcome.SUCCESS, "skill_postcondition_verified", 6.,
        planner=value, world=friendly, recovery_resume=None)
    ExecutionBookkeeper().record_terminal(
        attempt("INTERACT", {"guid": "Creature-kee-la"}), Outcome.FAILURE, "no_response", 7.,
        planner=value, world=friendly, recovery_resume=None)
    assert value.quest.unresponsive_guids == {"Creature-kee-la": ("signature:2175", 50.)}
    assert value.quest.interacted_guids == {}

    hostile = World({"map_id": 2175, "target": {"guid": "Creature-mob", "attackable": True}})
    ExecutionBookkeeper().record_terminal(
        attempt("INTERACT", {"guid": "Creature-mob"}), Outcome.FAILURE, "no_response", 6.,
        planner=value, world=hostile, recovery_resume=None)
    assert "Creature-mob" not in value.quest.unresponsive_guids


def test_silent_interact_with_far_or_marked_quest_npc_is_not_gated():
    """Live 2026-09-30 09:12: far-away Lady Jaina was wrongly gated for 300 s."""
    value = terminal_planner()
    value.quest.out_of_range_at["Creature-jaina"] = 40.
    far = World({"map_id": 2175, "monotonic_time": 90.,
                 "target": {"guid": "Creature-jaina", "attackable": False}})
    ExecutionBookkeeper().record_terminal(
        attempt("INTERACT", {"guid": "Creature-jaina"}), Outcome.FAILURE, "no_response", 5.,
        planner=value, world=far, recovery_resume=None)
    assert "Creature-jaina" not in value.quest.unresponsive_guids

    marked = World({"map_id": 2175, "monotonic_time": 90.,
                    "target": {"guid": "Creature-quest", "attackable": False},
                    "confirmed_mouseover_anchors": {"Creature-quest": {"track_id": "WORLD3D:2"}},
                    "visual_candidates": [{"track_id": "WORLD3D:2",
                                           "visual_group": {"belief": "SUPPORTED"}}]})
    ExecutionBookkeeper().record_terminal(
        attempt("INTERACT", {"guid": "Creature-quest"}), Outcome.FAILURE, "no_response", 6.,
        planner=value, world=marked, recovery_resume=None)
    assert "Creature-quest" not in value.quest.unresponsive_guids


def test_successful_visual_approach_clears_range_block_and_unresponsive_verdict():
    """Live 2026-09-30 13:42: after reaching Jaina (INTERACTION_READY) the kept
    range block re-proposed VISUAL_APPROACH until the approach budget stopped
    FULL_AI; INTERACT was never tried from interaction range."""
    value = terminal_planner()
    value.quest.interaction_range_blocks["Creature-jaina"] = {"started_at": 1.}
    value.quest.unresponsive_guids["Creature-jaina"] = ("signature:2175", 1.)
    near = World({"map_id": 2175, "monotonic_time": 20.,
                  "target": {"guid": "Creature-jaina", "attackable": False}})
    ExecutionBookkeeper().record_terminal(
        attempt("VISUAL_APPROACH", {"guid": "Creature-jaina", "purpose": "INTERACT"}),
        Outcome.SUCCESS, "skill_postcondition_verified", 20.,
        planner=value, world=near, recovery_resume=None)
    assert "Creature-jaina" not in value.quest.interaction_range_blocks
    assert "Creature-jaina" not in value.quest.unresponsive_guids
    assert value.quest.approach_verified_at["Creature-jaina"] == 20.
