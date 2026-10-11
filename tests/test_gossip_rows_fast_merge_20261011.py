"""Live 2026-10-11 14:53 (Austin Huxworth, two offered quests in one window).

After the Northbound turn-in the NPC showed two quests.  The full STATE
snapshot carried both rows, but a newer FAST packet's compact ``quest_ui``
(open/action/button only) replaced the whole dict when the snapshot was
published, so the agent saw ``entries=[]`` and waited in front of the list.
"""
import json

from adapters.telemetry_packets import PacketAssembler
from wowbot.agent.quest_dialog_planning import QuestDialogPlanningPolicy

ROWS = [
    {"kind": "AVAILABLE", "quest_id": 55184, "title": "Forbidden Quilboar Necromancy",
     "x": 0.06, "y": 0.31, "acceptable": True},
    {"kind": "AVAILABLE", "quest_id": 55186, "title": "Down with the Quilboar",
     "x": 0.06, "y": 0.34, "acceptable": True},
]


def _full(t, rows=ROWS, open_=True):
    return {"monotonic_time": t, "character_guid": "Player-1",
            "target": {"guid": "Creature-0-1-2175-1-154327-0001", "name": "Austin Huxworth",
                       "attackable": False},
            "quest_ui": {"open": open_, "action": "", "quest_id": 0, "x": 0, "y": 0,
                         "entries": rows, "reward_choices": [], "reward_selected_index": 0}}


def _fast(t, open_=True):
    return {"monotonic_time": t,
            "quest_ui": {"open": open_, "action": "", "quest_id": 0, "x": 0, "y": 0}}


def _feed_live_order(full, fast):
    assembler = PacketAssembler()
    assembler.feed("AIPC5|s|1|0|1|STATE|" + json.dumps(_full(1., rows=[], open_=False)), now=1.)
    assembler.feed("AIPC5|s|5|0|1|FAST|" + json.dumps(fast), now=2.1)
    return assembler.feed("AIPC5|s|2|0|1|STATE|" + json.dumps(full), now=2.2)


def test_newer_fast_dialog_keeps_the_snapshot_rows():
    state = _feed_live_order(_full(2.), _fast(2.05))
    assert state["quest_ui"]["open"] is True
    assert [row["quest_id"] for row in state["quest_ui"]["entries"]] == [55184, 55186]
    assert [row["quest_id"] for row in state["quest_ui_entries"]] == [55184, 55186]


def test_fast_closed_dialog_drops_stale_rows():
    state = _feed_live_order(_full(2.), _fast(2.05, open_=False))
    assert state["quest_ui"]["open"] is False
    assert state["quest_ui"]["entries"] == [] and state["quest_ui_entries"] == []


def test_two_offered_quests_are_selected_not_waited_on():
    state = _feed_live_order(_full(2.), _fast(2.05))
    proposals = QuestDialogPlanningPolicy().propose(state, None)
    picks = [p for p in proposals if p.skill == "QUEST_DIALOG"]
    assert picks and picks[0].parameters["action"] == "GOSSIP_SELECT"
    assert picks[0].parameters["quest_id"] in (55184, 55186)
    assert not any(p.skill == "WAIT" for p in proposals)


def test_turn_in_walk_ignores_a_symbol_over_a_creature_far_from_the_ender():
    """Live 2026-10-11 14:52: a porcupine with a symbol-like box over it
    stopped the Northbound turn-in walk ~10 times, 155 yd from the ender."""
    from types import SimpleNamespace
    from wowbot.agent.engine_runtime_projection import movement_visual_interrupt
    from wowbot.agent.models import Proposal

    attempt = SimpleNamespace(proposal=Proposal.make(
        "MOVE", "Leadási hely mmap útvonalon", {
            "purpose": "LOCATE_TURN_IN_REGION", "quest_id": 55173,
            "coordinate_space": "WORLD_YARDS", "instance_id": 2175,
            "x": 100., "y": 100., "stop_distance": 6.}))
    porcupine = {
        "source": "WORLD3D", "kind": "unknown_subject_candidate", "track_id": "porcupine",
        "confidence": .8, "stable_frames": 10, "lifecycle": "STABLE", "inspectable": True,
        "observed_at": 4., "candidate_labels": ["learned_subject_like"],
        "appearance": {"learned_label_hypothesis": "creature_unit_like"},
        "visual_group": {"appearance_labels": ["learned_symbol_like"]},
        "visual_relations": [{"type": "ABOVE", "belief": "SUPPORTED"}]}

    def at(x):
        return {"monotonic_time": 4., "visual_candidates": [porcupine],
                "player_world_position": {"x": x, "y": 100., "instance_id": 2175}}

    assert movement_visual_interrupt(attempt, at(-55.)) is None
    near = movement_visual_interrupt(attempt, at(75.))
    assert near is not None and near["reason"] == "quest_route_visual_cue_observed"
