"""Live 2026-10-07 12:06 (pid 15440, addon 0.9.61, "Who Lurks in the Pit" 5/5).

* Every FAST packet carried ``health=0``: 12.1 returns a secret
  UnitHealth("player") and the addon's safeNumber turned it into 0, so the
  agent saw 0 % health for the whole run (defensive-spell rules fired).
* The 4th cocoon's freeing cast was running (is_casting) when OBJECT_USE
  failed "credit not received"; the credit arrived 1.9 s later.
* After the FAST digest credited the 5th cocoon, the snapshot still showed
  4/5 and a second OBJECT_USE right-clicked the freed prisoner.
* Killed Barrow Spiderlings (no loot) were ``lootable=false`` while
  selected, but LOOT ran after the target was cleared: two
  ``corpse_not_found`` attempts per spiderling, back and forth after fights.
"""
from pathlib import Path
from types import SimpleNamespace

from adapters.telemetry_packets import normalize
from wowbot.agent.object_interaction_flow import ObjectInteractionFlow
from wowbot.agent.world import WorldModel
from wowbot.skills.object_use import ObjectUseSkill

ADDON = Path(__file__).resolve().parents[1] / "addon" / "AIPlayerControllerExport"
SPIDERLING = "Creature-0-4242-2175-7-160433-0000461B3D"


def test_a_living_player_at_zero_health_is_unknown_health():
    assert normalize({"health": 0, "max_health": 472, "is_dead": False})["health"] is None
    assert normalize({"health": 0, "max_health": 472, "is_dead": True})["health"] == 0
    assert normalize({"health": 300, "max_health": 472})["health"] == 300
    lua = (ADDON / "AIPlayerControllerExport.lua").read_text(encoding="utf-8")
    assert 'health = optionalNumber(safeCall(UnitHealth, "player"))' in lua
    assert 'health = safeNumber(safeCall(UnitHealth, "player"))' not in lua


def test_object_use_waits_while_its_cast_runs_after_the_deadline():
    skill = ObjectUseSkill()
    context = {"used_at": 100.}
    casting = {"is_casting": True, "state_sample_time": 103.}         # snapshot is fresh
    assert skill._use_cast_running(context, casting, 104., 103.)
    assert not skill._use_cast_running(context, {**casting, "is_casting": False}, 104., 103.)
    assert not skill._use_cast_running(context, casting, 109.5, 103.)  # bounded
    assert not skill._use_cast_running({}, casting, 104., 103.)       # nothing was used


def _cursor(t, x=.51, y=.52):
    return {"monotonic_time": t, "cursor_position": {"nx": x, "ny": y}}


def test_no_second_object_use_on_the_object_just_credited():
    flow = ObjectInteractionFlow()
    flow.note_result({"action_id": "a1", "skill": "OBJECT_USE", "outcome": "SUCCESS"}, _cursor(10.))
    assert flow.just_credited(_cursor(11.))
    assert not flow.just_credited(_cursor(11., x=.70))              # another object
    assert not flow.just_credited(_cursor(13.5))                    # the hold is short
    other = ObjectInteractionFlow()
    other.note_result({"action_id": "a2", "skill": "OBJECT_USE", "outcome": "FAILURE"}, _cursor(10.))
    assert not other.just_credited(_cursor(11.))


def _dead(world, lootable, guid=SPIDERLING):
    world.addon_state = {"target": {"guid": guid, "name": "Barrow Spiderling", "dead": True,
                                    "lootable": lootable}}


def test_a_corpse_reported_empty_is_retired_even_after_the_target_is_cleared():
    world = WorldModel()
    world.mark_combat_kill(SPIDERLING, 10.)
    _dead(world, False)
    world.note_corpse_lootability(10.2)                 # right at death: could still be loading
    assert SPIDERLING in world.owned_corpse_guids
    world.note_corpse_lootability(11.3)
    assert SPIDERLING not in world.owned_corpse_guids
    assert world.corpse_was_recently_looted(SPIDERLING, 12.)


def test_an_empty_report_before_the_kill_is_booked_retires_the_new_corpse():
    world = WorldModel()
    _dead(world, False)
    world.note_corpse_lootability(10.)
    world.note_corpse_lootability(11.2)
    world.mark_combat_kill(SPIDERLING, 11.5)
    assert SPIDERLING not in world.owned_corpse_guids


def test_a_lootable_corpse_keeps_its_loot():
    world = WorldModel()
    world.mark_combat_kill(SPIDERLING, 10.)
    _dead(world, False)
    world.note_corpse_lootability(10.1)
    _dead(world, True)                                  # loot appeared
    world.note_corpse_lootability(11.5)
    assert SPIDERLING in world.owned_corpse_guids
