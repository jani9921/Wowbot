"""REV4 P8.1: bounded live probes for unknown-source objectives at their server POI.

Live 2026-10-31 08:27 (26209 "Murder Was The Case"): the clues are credit NPCs
"Furlbrow Murder Info 001-004"; the subjects are the farm's homeless gossip
NPCs (one gives a clue, another attacks); no TDB row links them.  The agent
arrived at the server POI and waited "more data".  Server facts only; the
existing F7 path and bounded gossip trial do the work; no credit is assumed."""
from types import SimpleNamespace

from wowbot.agent.objective_probes import TALK_SECONDS, ObjectiveProbeLadder
from wowbot.agent.quest_attempt_memory import QuestAttemptMemory
from wowbot.agent.quest_dialog_planning import QuestDialogPlanningPolicy as Policy
from test_gossip_trials_20261028 import row
from test_talk_ride_credits_20261021 import unit

DRIFTER = "Creature-0-1463-2444-79-42391-0000616801"
CITIZEN = "Creature-0-1463-2444-79-42384-0000616802"
LAINE = "Creature-0-1463-2444-79-42308-0000616803"          # the quest giver: gossip + quest giver
VENDOR = "Creature-0-1463-2444-79-42390-0000616804"


def objective(mechanism="PROXY_UNKNOWN"):
    return SimpleNamespace(objective_id="26209:0", description="Clue #1 obtained", completion_state="INCOMPLETE",
                           raw={"mechanism": mechanism})


def world(mechanism="PROXY_UNKNOWN", poi=(0., 0.)):
    record = SimpleNamespace(quest_id=26209, current_state="ACTIVE", objectives=[objective(mechanism)])
    blob = {"world_map_id": 2444, "ui_map_id": 52, "objective_index": 0, "objective_id": 265754,
            "points": [{"x": poi[0], "y": poi[1], "z": 0}], "sample_time": 90., "blob_index": 0, "group_index": 1}
    return SimpleNamespace(quest_model=SimpleNamespace(records={26209: record}),
                           query=SimpleNamespace(quest_objective_pois=lambda qid, obj, now: (blob,)))


def state(**extra):
    return {"monotonic_time": 100., "orientation": 0., "map_id": 52, "session_id": "s",
            "player_world_position": {"x": 0., "y": 0., "z": 91., "instance_id": 2444,
                                      "coordinate_space": "WORLD_YARDS"},
            "packet_entities": {DRIFTER: unit(DRIFTER, 10., 0., 0x1), CITIZEN: unit(CITIZEN, 20., 0., 0x1),
                                LAINE: unit(LAINE, 2., 0., 0x3), VENDOR: unit(VENDOR, 3., 0., 0x81)},
            **extra}


def at(guid, x):
    return state(player_world_position={"x": x-2., "y": 0., "z": 91., "instance_id": 2444,
                                        "coordinate_space": "WORLD_YARDS"},
                 soft_targets=[{"source_unit": "softinteract", "guid": guid, "unit_type": "NPC"}],
                 soft_targets_sample_time=100.)


def test_at_the_poi_the_nearest_local_gossip_npc_is_walked_to_never_the_giver_or_a_vendor():
    (move,) = ObjectiveProbeLadder().propose(world(), state(), 100.)
    assert move.skill == "MOVE" and move.parameters["server_entity_guid"] == DRIFTER
    assert move.parameters["purpose"] == "OBJECTIVE_TALK_PROBE_APPROACH" and move.priority == 60.


def test_each_npc_is_talked_to_once_then_the_next_then_a_typed_exhaustion():
    ladder = ObjectiveProbeLadder()
    (press,) = ladder.propose(world(), at(DRIFTER, 10.), 100.)
    assert press.skill == "INTERACT" and press.parameters["soft_guid"] == DRIFTER
    assert press.parameters["purpose"] == "OBJECTIVE_TALK_PROBE"
    (again,) = ladder.propose(world(), at(DRIFTER, 10.), 100.+TALK_SECONDS-1)   # its talk is still running
    assert again.parameters.get("soft_guid") == DRIFTER
    (nxt,) = ladder.propose(world(), at(DRIFTER, 10.), 100.+TALK_SECONDS)
    assert nxt.skill == "MOVE" and nxt.parameters["server_entity_guid"] == CITIZEN
    ladder.propose(world(), at(CITIZEN, 20.), 120.)
    (done,) = ladder.propose(world(), at(CITIZEN, 20.), 120.+TALK_SECONDS)
    assert done.skill == "WAIT" and done.parameters["reason"] == "objective_probes_exhausted"
    assert done.parameters["probed"] == sorted([DRIFTER, CITIZEN])


def test_no_probe_for_known_mechanics_away_from_the_poi_or_in_combat():
    assert ObjectiveProbeLadder().propose(world("KILL"), state(), 100.) == []
    assert ObjectiveProbeLadder().propose(world(poi=(200., 0.)), state(), 100.) == []
    assert ObjectiveProbeLadder().propose(world(), state(is_in_combat=True), 100.) == []
    attacker = state()
    attacker["packet_entities"][DRIFTER]["unit"] = {"targets_me": True}
    (move,) = ObjectiveProbeLadder().propose(world(), attacker, 100.)
    assert move.parameters["server_entity_guid"] == CITIZEN               # the attacker is the defence's


def dialog(guid=DRIFTER):
    return {"monotonic_time": 100., "state_age": .3, "session_id": "s", "map_id": 52,
            "player_world_position": {"x": 0., "y": 0., "z": 91., "instance_id": 2444},
            "packet_entities": {guid: unit(guid, 3., 0., 0x1)}, "target": False,
            "active_quests": [{"quest_id": 26209, "is_complete": False, "objectives": [
                {"description": "0/1 Clue #1 obtained", "current": 0, "required": 1, "is_complete": False}]}],
            "reference_knowledge": {"quests": {"26209": {"title": "Murder Was The Case That They Gave Me",
                "objectives": [{"objective_id": 265754, "description": "Clue #1 obtained",
                                "mechanism": "PROXY_UNKNOWN", "credit_object_id": 42414,
                                "credit_name": "Furlbrow Murder Info 001"}]}}},
            "quest_ui": {"open": True, "action": "", "npc_guid": guid, "quest_id": 0,
                         "gossip_options": [row(1, "Did you see who killed the Furlbrows?")]}}


def test_the_probed_npcs_window_gets_the_bounded_gossip_trial_and_nothing_else_does():
    memory = QuestAttemptMemory()
    assert Policy._talk_gossip(dialog(), True, memory) is None                # unrelated actor: closed
    choice = Policy._talk_gossip(dialog(), True, memory, probe={"guid": DRIFTER, "quest_id": "26209"})
    assert choice.skill == "QUEST_DIALOG" and choice.parameters["gossip_option_id"] == 1
    assert choice.parameters["quest_id"] == 26209 and choice.parameters["gossip_trial"] is True
    other = Policy._talk_gossip(dialog(), True, memory, probe={"guid": CITIZEN, "quest_id": "26209"})
    assert other is None                                                       # another NPC's probe


def test_the_ladder_names_its_open_probe_window():
    ladder = ObjectiveProbeLadder()
    ladder.propose(world(), at(DRIFTER, 10.), 100.)
    assert ladder.active_probe(dialog()) == {"guid": DRIFTER, "quest_id": "26209"}
    assert ladder.active_probe(dialog(CITIZEN)) is None


def test_live_0941_an_empty_native_objective_query_falls_back_to_the_quests_server_blobs():
    """The native objective identity needs an observed server quest definition;
    a cached client never re-requests it, so the exact query stayed empty."""
    base = world()
    blob = base.query.quest_objective_pois(26209, None, 100.)[0]
    base.query = SimpleNamespace(quest_objective_pois=lambda qid, obj, now: (),
                                 quest_pois=lambda qid, now: (blob, {**blob, "objective_index": -1}))
    ladder = ObjectiveProbeLadder()
    (move,) = ladder.propose(base, state(), 100.)
    assert move.parameters["server_entity_guid"] == DRIFTER
    assert ladder.snapshot()["diagnostic"] == {"26209:26209:0": "probing:2_candidates"}


def test_the_diagnostic_says_why_no_probe_ran():
    none = world()
    none.query = SimpleNamespace(quest_objective_pois=lambda qid, obj, now: (), quest_pois=lambda qid, now: ())
    ladder = ObjectiveProbeLadder()
    assert ladder.propose(none, state(), 100.) == []
    assert ladder.snapshot()["diagnostic"] == {"26209:26209:0": "no_server_objective_poi:unknown"}
    far = ObjectiveProbeLadder()
    far.propose(world(poi=(200., 0.)), state(), 100.)
    assert far.snapshot()["diagnostic"] == {"26209:26209:0": "away_from_poi:200"}


def test_the_probe_asks_the_free_question_never_the_paid_one():
    """Live 10:31: the first untried row was the bribe; a money popup followed."""
    memory = QuestAttemptMemory()
    state = dialog()
    state["quest_ui"]["gossip_options"] = [
        row(1, "Maybe a couple copper will loosen your tongue. Now tell me, did you see who killed the Furlbrows?"),
        row(2, "Did you see who killed the Furlbrows?")]
    choice = Policy._talk_gossip(state, True, memory, probe={"guid": DRIFTER, "quest_id": "26209"})
    assert choice.parameters["gossip_option_id"] == 2


def test_inside_the_area_the_objective_move_does_not_pull_back_to_the_poi_centre():
    """Live 10:4x: five returns to the POI centre between the homeless."""
    from wowbot.agent.models import Proposal as P
    back = P.make("MOVE", "Quest objective graph", {"purpose": "LOCATE_QUEST_OBJECTIVE_REGION", "quest_id": 26209,
                                                    "x": 0., "y": 0.}, priority=96)
    other = P.make("MOVE", "other quest", {"purpose": "LOCATE_QUEST_OBJECTIVE_REGION", "quest_id": 62,
                                           "x": 0., "y": 0.}, priority=96)
    ladder = ObjectiveProbeLadder()
    assert ladder.suppress_area_returns([back, other], state()) == [back, other]      # not working an area yet
    ladder.propose(world(), state(), 100.)
    assert ladder.suppress_area_returns([back, other], state()) == [other]
    ladder.propose(world(poi=(200., 0.)), state(), 101.)                                # left the area
    assert ladder.suppress_area_returns([back, other], state()) == [back, other]


def test_the_clients_f7_recipient_among_the_untried_homeless_is_talked_to():
    """Live 10:4x: in the crowd the F7 recipient was another untried NPC; no press came."""
    crowd = at(CITIZEN, 16.)                        # player 4 yd from the drifter, 6 yd from the citizen
    (press,) = ObjectiveProbeLadder().propose(world(), crowd, 100.)
    assert press.skill == "INTERACT" and press.parameters["soft_guid"] == CITIZEN
    giver = at(LAINE, 4.)                           # the quest giver is never a probe subject
    (move,) = ObjectiveProbeLadder().propose(world(), giver, 100.)
    assert move.skill == "MOVE"


BOX = "GameObject-0-1463-2444-79-500100-0000616A01"


def with_box(flags=0x4, x=6., **extra):
    value = state(**extra)
    value["packet_entities"] = {LAINE: unit(LAINE, 2., 0., 0x3),
                                BOX: {"guid": BOX, "kind": "GAMEOBJECT", "entry_id": 500100, "map_id": 2444,
                                      "position": {"x": x, "y": 0., "z": 0.}, "info": {"go_type": 10},
                                      "dynamic_flags": {"value": flags}}}
    return value


def test_p81_rest_after_the_npcs_each_usable_poi_object_is_used_once():
    ladder = ObjectiveProbeLadder()
    (walk,) = ladder.propose(world(), with_box(x=20.), 100.)
    assert walk.skill == "MOVE" and walk.parameters["purpose"] == "OBJECTIVE_OBJECT_PROBE_APPROACH"
    (use,) = ladder.propose(world(), with_box(x=3.), 101.)
    assert use.skill == "OBJECT_USE" and use.parameters["object_guid"] == BOX
    assert use.parameters["activation_source"] == "INTERACT_KEY_PACKET"
    (done,) = ladder.propose(world(), with_box(x=3.), 101.+TALK_SECONDS)
    assert done.skill == "WAIT" and done.parameters["reason"] == "objective_probes_exhausted"


def test_an_object_the_server_does_not_mark_usable_is_not_probed():
    (wait,) = ObjectiveProbeLadder().propose(world(), with_box(flags=0), 100.)
    assert wait.skill == "WAIT" and wait.parameters["reason"] == "objective_probes_exhausted"


class Profiles:
    def _query(self, kind, identifier):
        return {"uses": [{"status": "RESOLVED", "target_mode": "SELF", "spell_id": 79262}]} if identifier == 57761 else {}


def with_house(bags_open=True, px=0.):
    value = state()
    value["packet_entities"] = {LAINE: unit(LAINE, 2., 0., 0x3)}
    value["player_world_position"]["x"] = px
    value.update(bags_open=bags_open, active_quests=[{"quest_id": 26209, "special_item": {"item_id": 57761}}],
                 inventory={"items": [{"item_id": 57761, "bag": 0, "slot": 4, "x": .8, "y": .3,
                                       "coordinate_space": "CLIENT_BOTTOM_LEFT"}]})
    return value


def test_live_1102_the_quests_own_self_cast_item_is_tried_first_at_the_poi_centre():
    ladder = ObjectiveProbeLadder()
    ladder.supplement = Profiles()
    (walk,) = ladder.propose(world(poi=(30., 0.)), with_house(px=10.), 100.)
    assert walk.skill == "MOVE" and walk.parameters["purpose"] == "OBJECTIVE_ITEM_PROBE_APPROACH"
    (bags,) = ladder.propose(world(), with_house(bags_open=False), 101.)
    assert bags.skill == "OPEN_BAGS"
    (use,) = ladder.propose(world(), with_house(), 102.)
    assert use.skill == "USE_ON_TARGET" and use.parameters["item_id"] == 57761
    assert use.parameters["activation_source"] == "INVENTORY_COORDINATE" and use.parameters["target_required"] is False
    (done,) = ladder.propose(world(), with_house(), 103.)                    # once per round
    assert done.skill == "WAIT" and done.parameters["reason"] == "objective_probes_exhausted"


def test_live_1102_1715_unread_bags_wait_and_the_approach_ends_inside_the_use_radius():
    ladder = ObjectiveProbeLadder()
    ladder.supplement = Profiles()
    unread = with_house()
    unread["inventory"] = {}
    (wait,) = ladder.propose(world(), unread, 100.)
    assert wait.parameters["reason"] == "objective_item_probe_waiting_inventory"
    assert not ladder.exhausted                                    # not "exhausted", no needs-user
    (walk,) = ladder.propose(world(poi=(30., 0.)), with_house(px=10.), 101.)
    assert walk.parameters["stop_distance"] == ObjectiveProbeLadder.ITEM_USE_YARDS-2.


THUG = "Creature-0-1463-0-79-42387-0000617001"


def thugs(px=0., mechanism="PROXY_UNKNOWN"):
    value = state()
    value["player_world_position"]["x"] = px
    value["packet_entities"] = {THUG: {"guid": THUG, "kind": "CREATURE", "entry_id": 42387, "map_id": 2444,
                                       "position": {"x": 18., "y": 0., "z": 0.}, "unit": {"health": 10}}}
    value["reference_knowledge"] = {"quests": {"26209": {"objectives": [
        {"objective_id": 1, "description": "Clue #1 obtained", "named_creatures": [{"entry": 42387, "name": "Thug"}]}]}}}
    return value


def test_live_1102_eavesdrop_goes_within_earshot_of_the_named_speakers_and_listens():
    ladder = ObjectiveProbeLadder()
    (walk,) = ladder.propose(world(), thugs(), 100.)
    assert walk.skill == "MOVE" and walk.parameters["purpose"] == "OBJECTIVE_LISTEN_PROBE_APPROACH"
    assert walk.parameters["server_entity_guid"] == THUG
    (listen,) = ladder.propose(world(), thugs(px=14.), 101.)
    assert listen.skill == "WAIT_EVENT" and listen.parameters["objective_kind"] == "WITNESS_PROXIMITY"
    (done,) = ladder.propose(world(), thugs(px=14.), 101.+ObjectiveProbeLadder.LISTEN_SECONDS)
    assert done.skill == "WAIT" and done.parameters["reason"] == "objective_probes_exhausted"


def test_witness_objectives_only_listen_and_never_report_exhaustion():
    ladder = ObjectiveProbeLadder()
    assert ladder.propose(world("WITNESS"), thugs(px=14.), 100.)[0].skill == "WAIT_EVENT"
    nothing = state()
    nothing["packet_entities"] = {}
    assert ObjectiveProbeLadder().propose(world("WITNESS"), nothing, 100.) == []


def test_eavesdrop_reads_as_witness_and_a_short_capitalised_name_is_named():
    from wowbot.quests.objective_mechanics import text_hint
    assert text_hint("Eavesdrop on Thugs.") == "WITNESS"
    import re
    name, text = "Thug", "Eavesdrop on Thugs."
    assert re.search(r'(?<![A-Za-z])' + re.escape(name) + r'(?:s|es)?(?![A-Za-z])', text)
    assert not re.search(r'(?<![A-Za-z])' + re.escape("Thug") + r'(?:s|es)?(?![A-Za-z])', "Thuggery spreads")


def test_user_1102_indoors_seven_yards_through_the_wall_is_not_earshot():
    inside = thugs(px=14.)                                     # 4 yd from the thug, but in the farmhouse
    inside["movement"] = {"indoors": True}
    (walk,) = ObjectiveProbeLadder().propose(world(), inside, 100.)
    assert walk.skill == "MOVE" and walk.parameters["stop_distance"] == 2.
    outside = thugs(px=14.)
    assert ObjectiveProbeLadder().propose(world(), outside, 100.)[0].skill == "WAIT_EVENT"
