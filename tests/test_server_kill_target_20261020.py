"""KILL objectives by server position + Tab with GUID check (offline).

User 2026-10-20: "the server sends the nearby quest mobs too, doesn't it?"
Live 09:04-09:13 every Harpy Snatcher/Ambusher, Hunting Worg and Bloodbeak
came with exact x,y,z (create blocks, monster-move splines).  A killed Harpy
Snatcher's unit dynamic flags went 0 -> 0x4 (lootable) at 09:08:06.
"""
import math
from types import SimpleNamespace

from wowbot.agent.models import Command
from wowbot.agent.packet_entity_facts import TAB_SERVER_GUID, kill_objective_units, tab_target_check
from wowbot.agent.server_kill_planning import ServerKillTargetPolicy
from wowbot.runtime.skill_identity import check_command_identity
from wowbot.skills.target import TargetSkill

SNATCHER = "Creature-0-1465-2175-71046-152571-0000570FE8"
OTHER_SNATCHER = "Creature-0-1465-2175-71046-152571-0000D70E26"
WORG = "Creature-0-1465-2175-71046-152998-000057107E"
MEREDY = "Creature-0-1465-2175-71046-153211-0000570F00"


def unit(guid, x, y, z=50., flags=0, npc_flags=0):
    return {"guid": guid, "kind": "CREATURE", "entry_id": int(guid.split("-")[5]), "map_id": 2175,
            "info": {"object_kind": "UNIT", "npc_flags": npc_flags}, "dynamic_flags": {"value": flags},
            "position": {"x": x, "y": y, "z": z, "source": "PACKET_CREATE_MOVEMENT", "age": 3.}}


def state(*units, facing=0., target=None, actionbar=(), combat=False, done=False):
    return {"monotonic_time": 100., "map_id": 1409, "orientation": facing, "is_in_combat": combat,
            "soft_targets": [], "target": target, "actionbar": list(actionbar),
            "player_world_position": {"x": 0., "y": 0., "z": 50., "z_observed": True, "instance_id": 2175,
                                      "coordinate_space": "WORLD_YARDS"},
            "active_quests": [{"quest_id": 55882, "is_complete": False, "objectives": [
                {"description": f"{3 if done else 1}/3 Harpy Snatcher slain", "type": "KILL",
                 "raw_type": "monster", "is_complete": done}]}],
            "reference_knowledge": {"quests": {"55882": {"objectives": [
                {"objective_id": 389820, "credit_kind": "CREATURE", "credit_object_id": 152571,
                 "description": "Harpy Snatcher slain",
                 "named_creatures": [{"entry": 152571, "name": "Harpy Snatcher"}]}]}}},
            "packet_entities": {item["guid"]: item for item in units}}


def test_live_objective_mobs_come_from_the_server_never_corpses_or_service_npcs():
    live = state(unit(SNATCHER, 12., 0.), unit(OTHER_SNATCHER, 30., 5., flags=0x4),
                 unit(WORG, 8., 8.), unit(MEREDY, 5., -5., npc_flags=0x3))
    assert [item["guid"] for item in kill_objective_units(live)] == [SNATCHER]
    assert kill_objective_units(state(unit(SNATCHER, 12., 0.), done=True)) == []


def test_tab_only_when_the_wanted_mob_is_the_nearest_straight_ahead():
    assert tab_target_check(state(unit(SNATCHER, 12., 0.)), SNATCHER) == (True, "SERVER_TAB_NEAREST")
    assert tab_target_check(state(unit(SNATCHER, 30., 0.)), SNATCHER)[1] == "OUT_OF_TAB_RANGE"
    assert tab_target_check(state(unit(SNATCHER, 0., 12.)), SNATCHER)[1] == "NOT_FACING"
    assert tab_target_check(state(unit(SNATCHER, 12., 0., z=70.)), SNATCHER)[1] == "OTHER_FLOOR"
    assert tab_target_check(state(unit(SNATCHER, 12., 0.), unit(WORG, 8., 1.)), SNATCHER)[1] \
        == "OTHER_UNIT_NEARER"
    # A unit behind us, a corpse or a friendly service NPC does not compete.
    assert tab_target_check(state(unit(SNATCHER, 12., 0.), unit(WORG, -5., 0.),
                                  unit(OTHER_SNATCHER, 6., 0., flags=0x4),
                                  unit(MEREDY, 5., 0., npc_flags=0x3)), SNATCHER)[0]
    assert tab_target_check(state(unit(SNATCHER, 12., 0., flags=0x4)), SNATCHER)[1] == "SERVER_UNIT_DEAD"


def test_walk_face_tab_then_close_in_until_combat_takes_over():
    policy = ServerKillTargetPolicy()
    far = policy.propose(state(unit(SNATCHER, 45., 0.)))
    assert far[0].skill == "MOVE" and far[0].parameters["server_entity_guid"] == SNATCHER
    assert far[0].parameters["stop_distance"] == 12. and far[0].parameters["face_on_arrival"] is True
    side = policy.propose(state(unit(SNATCHER, 0., 10.)))           # in range, not facing
    assert side[0].skill == "MOVE" and side[0].parameters["stop_distance"] == 10.
    tab = policy.propose(state(unit(SNATCHER, 12., 0.)))
    assert tab[0].skill == "TARGET" and tab[0].parameters["activation_source"] == TAB_SERVER_GUID
    assert tab[0].parameters["guid"] == SNATCHER
    assert policy.propose(state(unit(SNATCHER, 12., 0.))) == []      # one Tab per attempt
    crowded = ServerKillTargetPolicy().propose(state(unit(SNATCHER, 12., 0.), unit(WORG, 8., 1.)))
    assert crowded[0].skill == "MOVE" and crowded[0].parameters["stop_distance"] == 4.
    selected = {"guid": SNATCHER, "name": "Harpy Snatcher", "attackable": True}
    close_in = ServerKillTargetPolicy().propose(state(unit(SNATCHER, 12., 0.), target=selected))
    assert close_in[0].skill == "MOVE" and close_in[0].parameters["stop_distance"] == 4.
    charge = [{"is_harmful": True, "in_range": True}]
    assert ServerKillTargetPolicy().propose(state(unit(SNATCHER, 12., 0.), target=selected,
                                                  actionbar=charge)) == []
    assert ServerKillTargetPolicy().propose(state(unit(SNATCHER, 12., 0.), combat=True)) == []


def test_a_tab_that_selects_nothing_gives_the_mob_a_rest():
    policy = ServerKillTargetPolicy()
    live = state(unit(SNATCHER, 12., 0.))
    assert policy.propose(live)[0].skill == "TARGET"
    assert policy.propose({**live, "monotonic_time": 101.}) == []          # waiting for the selection
    assert policy.propose({**live, "monotonic_time": 103.}) == []          # not selected: resting
    assert policy.propose({**live, "monotonic_time": 225.})[0].skill == "TARGET"


def test_the_tab_press_is_identity_checked_and_verified_by_guid():
    params = {"guid": SNATCHER, "activation_source": TAB_SERVER_GUID, "npc_id": 152571}
    tab = (Command("BIND", "TARGETNEARESTENEMY"),)
    clear = state(unit(SNATCHER, 12., 0.))
    assert check_command_identity("TARGET", params, {"guid": SNATCHER}, clear, tab, 100.)
    crowded = state(unit(SNATCHER, 12., 0.), unit(WORG, 8., 1.))
    assert not check_command_identity("TARGET", params, {"guid": SNATCHER}, crowded, tab, 100.)
    intent = SimpleNamespace(parameters=params)
    assert TargetSkill().commands_for(intent) == tab


def test_own_lootable_corpse_is_walked_to_and_looted_via_its_soft_interact_unit():
    """09:08:06 the killed Harpy Snatcher went lootable (0x4) for us; the loot
    steps failed corpse_not_found whenever it was neither selected, hovered
    nor the soft-interact unit (live 10:16:30, 10:21:09, 12:58:16)."""
    from wowbot.agent.server_loot_planning import ServerLootPolicy
    policy = ServerLootPolicy()
    far = policy.propose(state(unit(SNATCHER, 10., 0., flags=0x4)))
    assert far[0].skill == "MOVE" and far[0].parameters["server_entity_guid"] == SNATCHER
    assert far[0].parameters["purpose"] == "APPROACH_SERVER_CORPSE"
    soft = [{"source_unit": "softinteract", "guid": SNATCHER, "is_dead": True, "unit_type": "CREATURE"}]
    here = {**state(unit(SNATCHER, 2., 0., flags=0x4)), "soft_targets": soft}
    loot = policy.propose(here)
    assert loot[0].skill == "LOOT" and loot[0].parameters["guid"] == SNATCHER
    assert loot[0].parameters["soft_interact"] is True
    # Close and facing but another unit is the F7 recipient: no press.
    assert ServerLootPolicy().propose(state(unit(SNATCHER, 2., 0., flags=0x4))) == []
    # Looted (flag back to 0), alive, or a fight: nothing.
    assert ServerLootPolicy().propose(state(unit(SNATCHER, 10., 0.))) == []
    assert ServerLootPolicy().propose(state(unit(SNATCHER, 10., 0., flags=0x4), combat=True)) == []
    # Two presses without the flag clearing: rest.
    assert policy.propose({**here, "monotonic_time": 101.})[0].skill == "LOOT"
    assert policy.propose({**here, "monotonic_time": 102.}) == []


def test_kill_credit_creatures_count_and_credit_proxies_never_do():
    """Harpy Culling (55764) "Harpies and cohorts slain": credit 152843; the
    TDB gives that credit to Harpy Snatcher/Ambusher and Hunting Worgs
    through KillCredit1.  A "[DNT]" credit proxy is never walked to."""
    import sqlite3
    from wowbot.agent.tdb_knowledge import TDBKnowledgeProvider
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.execute("CREATE TABLE creature_template (entry INTEGER, name TEXT, KillCredit1 INTEGER, KillCredit2 INTEGER)")
    db.executemany("INSERT INTO creature_template VALUES (?,?,?,?)", [
        (152843, "Harpy Boltcaller", 0, 0), (152571, "Harpy Snatcher", 152843, 0),
        (152998, "Hunting Worg", 152843, 0), (194139, "Kill Credit: Rescue Cogcatcher [DNT]", 0, 0)])
    raw = SimpleNamespace(tables={"creature_template"},
                          rows=lambda sql, args=(): [dict(r) for r in db.execute(sql, args).fetchall()])
    provider = TDBKnowledgeProvider(SimpleNamespace(raw=raw))
    name, creatures = provider.kill_credit(152843)
    assert name == "Harpy Boltcaller" and {c["entry"] for c in creatures} == {152571, 152998}
    culling = state(unit(SNATCHER, 12., 0.), unit(WORG, 8., 8.))
    culling["active_quests"][0]["objectives"][0]["description"] = "4/10 Harpies and cohorts slain"
    culling["reference_knowledge"]["quests"]["55882"]["objectives"] = [
        {"description": "Harpies and cohorts slain", "credit_kind": "CREATURE_CREDIT",
         "credit_object_id": 152843, "credit_name": name, "credit_creatures": creatures,
         "named_creatures": []}]
    assert {item["guid"] for item in kill_objective_units(culling)} == {SNATCHER, WORG}
    proxy = state(unit("Creature-0-1465-2175-71046-194139-0000000001", 5., 0.))
    proxy["reference_knowledge"]["quests"]["55882"]["objectives"] = [
        {"description": "Harpy Snatcher slain", "credit_kind": "CREATURE_CREDIT", "credit_object_id": 194139,
         "credit_name": "Kill Credit: Rescue Cogcatcher [DNT]", "named_creatures": []}]
    assert kill_objective_units(proxy) == []


def test_collect_objective_targets_the_creatures_that_drop_its_item():
    """Murloc Mania (55122), live 16:46-16:48: "First Aid Kits recovered from
    defeated Murlocs" (COLLECT, item 170549) drops from murlocs 150228/150229
    (TDB creature_questitem); 14-23 of them were in server range while the
    agent searched on screen."""
    spearhunter = "Creature-0-1465-2175-71046-150228-0000D77EC7"
    watershaper = "Creature-0-1465-2175-71046-150229-0000577EDB"
    live = state(unit(spearhunter, 12., 0.), unit(watershaper, 30., 5.), unit(WORG, 8., 8.))
    live["active_quests"] = [{"quest_id": 55122, "is_complete": False, "objectives": [
        {"description": "4/6 First Aid Kits recovered from defeated Murlocs", "type": "COLLECT",
         "raw_type": "item", "is_complete": False}]}]
    sources = [{"kind": "CREATURE", "entry": entry, "relation": "QUEST_ITEM_ASSOCIATION", "item_id": 170549}
               for entry in (150228, 150229)]
    live["reference_knowledge"]["quests"] = {"55122": {"objectives": [
        {"description": "First Aid Kits recovered from defeated Murlocs", "credit_kind": "ITEM",
         "credit_object_id": 170549, "raw_type": 1,
         "item_sources": sources + [{"kind": "VENDOR", "entry": 999, "relation": "SELLS"}]}]}}
    assert {item["guid"] for item in kill_objective_units(live)} == {spearhunter, watershaper}
    tab = ServerKillTargetPolicy().propose(live)
    assert tab[0].skill == "TARGET" and tab[0].parameters["guid"] == spearhunter
    assert tab[0].parameters["quest_ids"] == ["55122"]
    done = {**live, "active_quests": [{**live["active_quests"][0], "is_complete": True}]}
    assert kill_objective_units(done) == []


def test_screen_and_map_searches_yield_while_the_server_names_the_mob():
    """Live 16:52-16:54: INSPECT/SEEK and objective-region / search-cell MOVEs
    kept preempting the server walk-up and Tab (a WORLD_YARDS MOVE ranks 20
    lower), so the agent zig-zagged between murlocs and screen searches."""
    from wowbot.agent.models import Proposal
    from wowbot.agent.planner import Planner
    server = ServerKillTargetPolicy().propose(state(unit(SNATCHER, 45., 0.)))
    search = [Proposal.make("INSPECT", "hover", {"x": .5, "y": .5}),
              Proposal.make("SEEK_VISUAL_CUE", "seek", {}),
              Proposal.make("MOVE", "region", {"purpose": "LOCATE_QUEST_OBJECTIVE_REGION", "x": 1, "y": 2}),
              Proposal.make("MOVE", "cell", {"purpose": "SEARCH_LOCAL_OBJECTIVE_AREA", "x": 1, "y": 2})]
    keep = [Proposal.make("TARGET", "hovered quest mob", {"guid": WORG}),
            Proposal.make("LOOT", "corpse", {"guid": OTHER_SNATCHER}),
            Proposal.make("MOVE", "turn-in", {"purpose": "LOCATE_TURN_IN_REGION", "x": 1, "y": 2})]
    kept = Planner.prefer_server_targets(server + search + keep)
    assert kept == server + keep
    assert Planner.prefer_server_targets(search + keep) == search + keep   # no server target: unchanged


def test_a_corpse_tab_cannot_select_is_skipped_for_the_next_mob():
    """Live 17:03:10: Tab straight at a murloc 9.4 yd ahead selected nothing --
    it lay dead (killed by someone else: no lootable flag for us).  A live
    murloc stood to the right."""
    policy = ServerKillTargetPolicy()
    live = state(unit(SNATCHER, 9.4, 0.), unit(OTHER_SNATCHER, 9., 6.))
    assert policy.propose(live)[0].parameters["guid"] == SNATCHER        # Tab
    after = {**live, "monotonic_time": 101.6}                            # nothing selected
    nxt = policy.propose(after)
    assert nxt[0].parameters.get("server_entity_guid") == OTHER_SNATCHER  # walk/face the live one
    # The addon names a corpse: never chosen.
    corpse = {**state(unit(SNATCHER, 9.4, 0.), unit(OTHER_SNATCHER, 20., 0.)),
              "mouseover": {"guid": SNATCHER, "tooltip": "Corpse ~ Murloc Mania", "name": "Murloc"}}
    other = ServerKillTargetPolicy().propose(corpse)
    assert other[0].parameters.get("server_entity_guid", other[0].parameters.get("guid")) == OTHER_SNATCHER


def test_a_facing_walk_within_its_stop_distance_is_not_dropped_as_arrived():
    """Live 17:12-17:13: the walk-up to a murloc within reach but off to the
    side was ranked "arrived" and dropped; only WAIT remained for a minute."""
    from wowbot.agent.models import Goal, Observation, Proposal
    from wowbot.agent.proposal_ranking import ProposalRanker
    from wowbot.agent.skills import SkillRegistry
    from wowbot.agent.world import WorldModel
    def world_at(facing):
        world = WorldModel()
        base = {"session_id": "s", "frame_id": "f", "timestamp": 1, "player_present": True,
                "is_casting": False, "map_id": 1409, "orientation": facing,
                "player_world_position": {"x": 0., "y": 0., "z": 50., "instance_id": 2175,
                                          "coordinate_space": "WORLD_YARDS"}}
        world.ingest(Observation.create(base, 100.))
        return world
    side = ServerKillTargetPolicy().propose(state(unit(SNATCHER, 0., 8.)))    # 90 deg left, 8 yd
    assert side[0].skill == "MOVE" and side[0].parameters["stop_distance"] == 8.
    def ranked(world):
        return ProposalRanker.rank(list(side), goal=Goal.parse("Questelj", 1), world=world, now=100.,
                                   registry=SkillRegistry(), memory=None, blocked_until={}, recent={},
                                   evidence=()).proposals
    assert [p.skill for p in ranked(world_at(0.))] == ["MOVE"]                # must still turn
    assert [p.skill for p in ranked(world_at(1.5708))] == ["WAIT"]            # facing: arrived


def test_a_server_lootable_corpse_is_looted_on_a_bare_soft_interact_guid():
    """Live 17:19:35-37: the murloc corpse was flagged 0x4 for us and was the
    soft-interact unit, but that row carried only its GUID (no dead flag),
    so Interact was never pressed and the next kill walked away."""
    from wowbot.agent.models import Attempt, Prediction
    from wowbot.agent.server_loot_planning import ServerLootPolicy
    from wowbot.runtime import ActiveSkillRuntime, Intent
    from wowbot.skills import LootSkill
    soft = [{"source_unit": "softinteract", "guid": SNATCHER}]
    here = {**state(unit(SNATCHER, .7, 0., flags=0x4)), "soft_targets": soft}
    (loot,) = ServerLootPolicy().propose(here)
    assert loot.skill == "LOOT" and loot.parameters["server_lootable"] is True
    attempt = Attempt("a", loot, here, "o", 100., 103., (), Prediction("p", "a", "loot", 100., 103., "o"))
    runtime = ActiveSkillRuntime()
    runtime.start(intent=Intent("LOOT", loot.parameters, SNATCHER), attempt=attempt, now=100., before_snapshot=here)
    started = LootSkill().begin(runtime.state, here)
    assert [c.binding for c in started.commands] == ["INTERACTTARGET"]
    # Without the server flag the bare GUID is not proof of a corpse.
    alive = {**state(unit(SNATCHER, .7, 0.)), "soft_targets": soft}
    assert ServerLootPolicy().propose(alive) == []


def test_tab_picking_another_objective_mob_is_a_success():
    """Live 17:19:53: Tab selected another murloc of the same objective and
    the TARGET step failed identity_uncertain."""
    from wowbot.agent.models import Attempt, Prediction, Proposal
    from wowbot.runtime import ActiveSkillRuntime, Intent, SkillStatus
    live = state(unit(SNATCHER, 12., 0.), unit(OTHER_SNATCHER, 14., 1.))
    (tab,) = ServerKillTargetPolicy().propose(live)
    assert OTHER_SNATCHER in tab.parameters["acceptable_guids"]
    attempt = Attempt("a", tab, live, "o", 100., 102., (), Prediction("p", "a", "t", 100., 102., "o"))
    runtime = ActiveSkillRuntime()
    runtime.start(intent=Intent("TARGET", tab.parameters, SNATCHER), attempt=attempt, now=100., before_snapshot=live)
    skill = TargetSkill()
    skill.begin(runtime.state, live)
    other = {**live, "target": {"guid": OTHER_SNATCHER, "name": "Harpy Snatcher"}, "target_sample_time": 101.,
             "monotonic_time": 101.}
    assert skill.verify(runtime.state, other, 101.).status is SkillStatus.SUCCESS


def test_the_combat_facing_turn_is_one_input_step_at_most():
    """Live 17:20:07: "an input step is at most 350 ms" rejected a 1 s turn."""
    from wowbot.skills import CombatSkill
    from test_combat_server_facing_20261020 import world as combat_world, MURLOC
    from test_m0_combat_loot_skills import active
    behind = combat_world((-3., 0.1))
    turned = CombatSkill().begin(active("COMBAT", {"guid": MURLOC}, behind), behind, 1.)
    assert turned.commands[0].binding == "TURNLEFT" and turned.commands[0].duration <= .35
