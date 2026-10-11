"""Live 2026-10-11 15:39-15:45 (Re-sizing the Situation, Re-Sizer on
Wandering Boars).  The agent searched for minutes, pressed Interact on far
boars (out_of_range) and booked real uses as IDENTITY_UNCERTAIN because the
boar turned into a "Re-sized Boar" before the credit arrived."""
from types import SimpleNamespace

from test_item_use_interact_first_20261006 import _state
from test_item_use_no_combat_20261004 import BOAR, INVENTORY, QUEST, _quest_proposals, _world

from wowbot.agent.engine_runtime_projection import movement_visual_interrupt
from wowbot.agent.models import Proposal
from wowbot.runtime import SkillStatus
from wowbot.skills.quest_item import UseItemSkill

RESIZED = {"guid": "Creature-0-3113-2175-63341-160543-0000411A77", "name": "Re-sized Boar"}
CREDITED = {**QUEST, "objectives": [{**QUEST["objectives"][0], "current": 1,
                                     "description": "1/3 Re-Sizer v9.0.1 tested on Wandering Boars"}]}


def test_transformed_boar_after_a_cast_waits_for_the_credit():
    skill = UseItemSkill()
    state = _state("INTERACT_KEY")
    assert skill.verify(state, {"target": BOAR, "active_quests": [QUEST], "is_casting": True},
                        10.5).status is SkillStatus.RUNNING
    changed = {"target": RESIZED, "active_quests": [QUEST], "is_casting": False}
    assert skill.verify(state, changed, 11.).status is SkillStatus.RUNNING
    done = skill.verify(state, {**changed, "active_quests": [CREDITED]}, 11.4)
    assert done.status is SkillStatus.SUCCESS


def test_target_change_without_any_cast_is_still_identity_uncertain():
    skill = UseItemSkill()
    result = skill.verify(_state("INTERACT_KEY"),
                          {"target": RESIZED, "active_quests": [QUEST]}, 10.5)
    assert result.status is SkillStatus.FAILURE and result.reason.value == "IDENTITY_UNCERTAIN"


def test_far_selected_boar_is_approached_before_interact():
    far = {**BOAR, "world_position": {"x": 150., "y": -2400., "instance_id": 2175,
                                      "coordinate_space": "WORLD_YARDS"}}
    _, proposals = _quest_proposals(_world(inventory=INVENTORY, target=far))
    assert not any(p.skill == "USE_ON_TARGET" for p in proposals)
    assert any(p.skill in {"VISUAL_APPROACH", "MOVE"} and p.parameters.get("guid") == BOAR["guid"]
               for p in proposals)
    near = {**BOAR, "world_position": {"x": 124., "y": -2400., "instance_id": 2175,
                                       "coordinate_space": "WORLD_YARDS"}}
    _, proposals = _quest_proposals(_world(inventory=INVENTORY, target=near))
    assert any(p.skill == "USE_ON_TARGET" for p in proposals)


def test_zone_sweep_for_an_item_on_creatures_stops_for_a_creature():
    def sweep(scan_units):
        return SimpleNamespace(proposal=Proposal.make(
            "MOVE", "Quest keresési régió szisztematikus következő cellája", {
                "purpose": "SEARCH_LOCAL_OBJECTIVE_AREA", "objective_type": "USE_ITEM",
                "scan_while_moving": True, "scan_units": scan_units, "quest_id": 56034,
                "coordinate_space": "WORLD_YARDS", "instance_id": 2175, "x": 200., "y": -2400.}))
    boar_box = {"source": "WORLD3D", "kind": "unknown_subject_candidate", "track_id": "boar",
                "confidence": .8, "stable_frames": 10, "lifecycle": "STABLE", "inspectable": True,
                "observed_at": 4., "candidate_labels": ["learned_subject_like"],
                "appearance": {"learned_label_hypothesis": "creature_unit_like"}}
    state = {"monotonic_time": 4., "visual_candidates": [boar_box],
             "player_world_position": {"x": 120., "y": -2400., "instance_id": 2175}}
    handoff = movement_visual_interrupt(sweep(True), state)
    assert handoff is not None and handoff["track_id"] == "boar"
    # Without units in the objective, a creature 80 yd before the cell is no cue.
    assert movement_visual_interrupt(sweep(False), state) is None
