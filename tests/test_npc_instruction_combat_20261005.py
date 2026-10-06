"""Live 2026-10-05 (Enhanced Combat Tactics, 59254): Captain Garrick said
"Charge at me again to close the distance" three times; Charge is a
once-per-fight opener in the rotation, so the agent pressed Slam (out of
range) and the user had to Charge by hand."""
from test_m0_combat_loot_skills import active

from wowbot.skills import CombatSkill

CHARGE = {"id": 100, "name": "Charge", "kind": "spell", "action": "ACTIONBUTTON1",
          "is_harmful": True, "is_usable": True, "in_range": True, "cooldown_remaining": 0}
SLAM = {"id": 1464, "name": "Slam", "kind": "spell", "action": "ACTIONBUTTON2",
        "is_harmful": True, "is_usable": False, "in_range": False, "cooldown_remaining": 0}


def _garrick(sequence, *, events=(), timestamp=1000):
    return {"target": {"guid": "Creature-garrick", "name": "Captain Garrick", "attackable": True,
                       "dead": False, "health": 100},
            "actionbar": [CHARGE, SLAM], "fast_sequence": sequence, "timestamp": timestamp,
            "events": list(events)}


def _said(message, sequence, timestamp=1000):
    return {"event_type": "NPC_INSTRUCTION", "sequence": sequence, "timestamp": timestamp,
            "payload": {"channel": "CHAT_MSG_MONSTER_SAY", "sender": "Captain Garrick",
                        "message": message}}


def test_fresh_instruction_lets_the_opener_be_used_again_once():
    skill = CombatSkill()
    start = _garrick(1)
    runtime = active("COMBAT", {"guid": "Creature-garrick"}, start)
    assert skill.begin(runtime, start, 1.).commands[0].binding == "ACTIONBUTTON1"   # opener

    again = _garrick(2, events=[_said("Charge at me again to close the distance between us.", 1409)])
    charged = skill.verify(runtime, again, 3.)
    assert charged.commands and charged.commands[0].binding == "ACTIONBUTTON1"

    # The same instruction is followed once; the opener limit is back.
    repeat = skill.verify(runtime, {**again, "fast_sequence": 3}, 5.)
    assert not any(command.binding == "ACTIONBUTTON1" for command in repeat.commands or ())


def test_stale_instruction_does_not_override_the_rotation():
    skill = CombatSkill()
    start = _garrick(1)
    runtime = active("COMBAT", {"guid": "Creature-garrick"}, start)
    skill.begin(runtime, start, 1.)
    old = _garrick(2, events=[_said("Charge!", 1409, timestamp=900)], timestamp=1000)
    result = skill.verify(runtime, old, 3.)
    assert not any(command.binding == "ACTIONBUTTON1" for command in result.commands or ())
