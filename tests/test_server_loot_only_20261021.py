"""Server mode loots by the killed GUID's server position only (live 2026-10-21).

10:57:48 the server walk reached three Primal Proto-Whelp corpses lying on one
spot; the soft-interact unit was one of them, the walk aimed at another, so
nothing was pressed and the old screen search (addon tooltip anchor, hover
cells) took over and failed ``corpse_not_found``.  User: "a régi cellás loot
keresés még mindig benne van, a szerveres loot kéne maradjon: megölés GUID
alapján halott mob x,y,z, odamegy, lootol F7-tel".
"""
from wowbot.agent.models import Attempt, Prediction
from wowbot.agent.server_loot_planning import ServerLootPolicy
from wowbot.runtime import ActiveSkillRuntime, Intent, SkillStatus
from wowbot.skills import InteractSkill, LootSkill

from test_combat_planning_policy import _policy, _quest, _world
from test_server_kill_target_20261020 import unit, state as server_state

WHELP_A = "Creature-0-3769-2444-47-192103-0000587AB1"
WHELP_B = "Creature-0-3769-2444-47-192103-0001587AB1"
WHELP_C = "Creature-0-3769-2444-47-192103-0000D87AB1"


def whelps(**extra):
    value = server_state(unit(WHELP_A, 1.1, 0., flags=0x4), unit(WHELP_B, 1.1, 0., flags=0x4),
                         unit(WHELP_C, 1.9, 0., flags=0x4))
    value.update(extra)
    return value


def start(skill, proposal, here):
    attempt = Attempt("a", proposal, here, "o", 100., 107., (), Prediction("p", "a", "x", 100., 107., "o"))
    runtime = ActiveSkillRuntime()
    runtime.start(intent=Intent(proposal.skill, proposal.parameters, proposal.parameters.get("guid")),
                  attempt=attempt, now=100., before_snapshot=here)
    return runtime.state, skill.begin(runtime.state, here)


def test_the_corpse_under_the_interact_key_is_looted_even_if_not_the_nearest():
    here = whelps(soft_targets=[{"source_unit": "softinteract", "guid": WHELP_B}])
    (loot,) = ServerLootPolicy().propose(here)
    assert loot.skill == "LOOT" and loot.parameters["guid"] == WHELP_B
    assert loot.parameters["soft_interact"] is True and loot.parameters["server_lootable"] is True
    _, started = start(LootSkill(), loot, here)
    assert [c.binding for c in started.commands] == ["INTERACTTARGET"]
    # Another unit (the rib cage) under the key: no press, as before.
    cage = whelps(soft_targets=[{"source_unit": "softinteract", "guid": "GameObject-0-1-2444-1-379137-01"}])
    assert ServerLootPolicy().propose(cage) == []


def test_a_selected_corpse_of_ours_is_looted_with_the_interact_key():
    here = whelps(target={"guid": WHELP_C, "name": "Primal Proto-Whelp"})       # no dead flag yet
    (loot,) = ServerLootPolicy().propose(here)
    assert loot.parameters["guid"] == WHELP_C and loot.parameters["soft_interact"] is False
    _, started = start(LootSkill(), loot, here)
    assert [c.binding for c in started.commands] == ["INTERACTTARGET"]


def test_server_mode_has_no_screen_corpse_search():
    guid = "Creature-0-1-2-3-150228-00000001"
    world = _world(
        active_quests=_quest(),
        mouseover={"guid": guid, "name": "Murloc", "is_dead": True, "lootable": True},
        cursor_position={"nx": .42, "ny": .51},
        cursor_sample_time=1., mouseover_sample_time=1., event_sequence=1,
        events=[{"sequence": 1, "timestamp": 1., "event_type": "MOUSEOVER_CHANGED",
                 "payload": {"tooltip": "Murloc ~ Corpse",
                             "tooltip_data": {"guid": guid, "unit_guid": guid, "lootable": True}}}])
    assert any(p.parameters.get("corpse_anchor") for p in _policy(world).proposals)   # vision mode
    world.state["server_mode"] = {"active": True}
    assert not any(p.parameters.get("corpse_anchor") for p in _policy(world).proposals)
    world.owned_corpse_guids["Creature-0-1-2-3-161131-000040E861"] = .9
    assert not any(p.skill == "RECOVER" for p in _policy(world).proposals)            # no step-back reveal


def rescue_state(done=0, **extra):
    return {"monotonic_time": 100., "target": {}, "soft_targets": [],
            "quest_digest": [{"id": 70122, "done": done}],
            "active_quests": [{"quest_id": 70122, "is_complete": False, "objectives": [
                {"description": f"{done}/1 Archivist Rellid rescued", "current": done, "required": 1,
                 "is_complete": done == 1}]}], **extra}


def test_a_rescue_press_waits_for_and_counts_the_objective_credit():
    from wowbot.agent.models import Proposal
    press = Proposal.make("INTERACT", "rescue", {
        "activation_source": "SOFT_INTERACT", "soft_guid": "Creature-0-3769-2444-47-189055-00005824CB",
        "guid": "Creature-0-3769-2444-47-189055-00005824CB",
        "purpose": "RESCUE_SOFT_INTERACT_NPC", "quest_id": "70122"})
    skill = InteractSkill()
    active, _ = start(skill, press, rescue_state())
    waiting = skill.verify(active, rescue_state(monotonic_time=102.), 102.)
    assert waiting.status is SkillStatus.RUNNING
    credited = skill.verify(active, rescue_state(done=1, monotonic_time=103.5), 103.5)
    assert credited.status is SkillStatus.SUCCESS and "rescue_objective_progress" in credited.evidence
