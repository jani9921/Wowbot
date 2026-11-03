"""Turn to the selected mob by its exact position (user 2026-10-20).

"Facing does not work with the mob, although the server tells where the mob
is and where we look."  Live 16:46:57 and 16:47:06-07 (Murloc Mania) COMBAT
failed facing_wrong_way three times; the recovery only knew screen positions
or a blind 35-degree sweep.
"""
import math

from wowbot.skills import CombatSkill
from test_m0_combat_loot_skills import active, combat_state

MURLOC = "Creature-0-1465-2175-71046-150228-0000D77EC7"


def world(target_xy, *, facing=0., ui_error=None, sequence=None, server=True):
    state = combat_state(ui_error=ui_error)
    state["target"]["guid"] = MURLOC
    state["player_world_position"] = {"x": 0., "y": 0., "instance_id": 2175}
    state["orientation"] = facing

    if sequence is not None:
        state["ui_error_sequence"] = sequence
    x, y = target_xy
    if server:
        state["packet_entities"] = {MURLOC: {
            "guid": MURLOC, "kind": "CREATURE", "entry_id": 150228, "map_id": 2175,
            "position": {"x": x, "y": y, "z": 0., "source": "PACKET_CREATE_MOVEMENT", "age": 1.}}}
    else:
        state["target"]["world_position"] = {"x": x, "y": y, "instance_id": 2175}
    return state


def test_a_mob_behind_is_faced_before_the_attack():
    skill = CombatSkill()
    behind = world((-3., 0.5))                              # ~170 deg to the left
    runtime = active("COMBAT", {"guid": MURLOC}, behind)
    turned = skill.begin(runtime, behind, 1.)
    assert [c.binding for c in turned.commands] == ["TURNLEFT"]
    expected = math.atan2(.5, -3.)
    assert abs(turned.commands[0].duration - min(.34, expected/math.pi*.9)) < .01   # one input step
    assert turned.metadata["facing_turn_source"] == "TARGET_WORLD_POSITION"
    # In front now: the attack goes out.
    ahead = world((3., .2))
    assert skill.verify(runtime, ahead, 1.6).commands[0].binding == "ACTIONBUTTON1"


def test_the_addon_target_position_works_without_server_data():
    skill = CombatSkill()
    right = world((0., -3.), server=False)                  # 90 deg to the right
    turned = skill.begin(active("COMBAT", {"guid": MURLOC}, right), right, 1.)
    assert [c.binding for c in turned.commands] == ["TURNRIGHT"]


def test_facing_the_wrong_way_turns_exactly_then_attacks():
    skill = CombatSkill()
    ahead = world((3., 0.))
    runtime = active("COMBAT", {"guid": MURLOC}, ahead)
    assert skill.begin(runtime, ahead, 1.).commands[0].binding == "ACTIONBUTTON1"
    # The client says "not in front": the mob sits 40 deg right by now.
    wrong = world((3., -2.5), ui_error="You are facing the wrong way.", sequence=1)
    result = skill.verify(runtime, wrong, 2.)
    assert [c.binding for c in result.commands][0] == "TURNRIGHT"
    assert len(result.commands) == 2                         # turn, then the attack key
    assert "facing_sweep" not in runtime.skill_context["combat"]
