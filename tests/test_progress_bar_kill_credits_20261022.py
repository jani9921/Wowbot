"""Progress-bar quests filled by hidden kill credits (live 2026-10-22 23:50-23:52).

Fighting Fire with... Water (66998): the only live objective was "Erupting
Cavern contained (24%)".  Every Erupting Droplet killed in self-defence added
4 %, but no droplet was hunted: the TDB's description-less creature-credit
rows (Droplet, Lasher, Magma) matched no KILL objective, so the agent waited.
"""
from wowbot.agent.packet_entity_facts import kill_objective_entries, kill_objective_units
from wowbot.agent.server_kill_planning import ServerKillTargetPolicy

DROPLET = "Creature-0-3769-2444-47-191517-00005A855D"
LASHER = "Creature-0-3769-2444-47-191944-00005A8601"


def credit_row(storage, objective_id, credit, creatures):
    return {"amount": 5, "credit_kind": "CREATURE_CREDIT", "credit_object_id": credit,
            "credit_name": "Kill Credit: Elemental (Small) [DNT]", "description": "",
            "credit_creatures": [{"entry": entry, "name": name} for entry, name in creatures],
            "named_creatures": [], "objective_id": objective_id, "raw_type": 0,
            "storage_index": storage}


def state(bar="Erupting Cavern contained (24%)", raw_type="progressbar", with_bar_row=True):
    rows = [credit_row(0, 428766, 192032, [(191517, "Erupting Droplet"), (191983, "Erupting Droplet")]),
            credit_row(1, 428767, 192033, [(191944, "Erupting Lasher")]),
            credit_row(2, 428768, 192034, [(191917, "Erupting Magma")])]
    if with_bar_row:
        rows.insert(0, {"amount": 1, "credit_kind": "OTHER", "credit_object_id": 0,
                        "description": "Erupting Cavern contained", "objective_id": 428679,
                        "raw_type": 15, "storage_index": -1})
    return {
        "monotonic_time": 100., "orientation": 0., "map_id": 2022,
        "player_world_position": {"x": 3600., "y": -60., "z": 40., "instance_id": 2444,
                                  "z_observed": True},
        "active_quests": [{"quest_id": 66998, "is_complete": False, "objectives": [
            {"description": bar, "is_complete": False, "raw_type": raw_type, "type": "AREA"}]}],
        "reference_knowledge": {"quests": {"66998": {"objectives": rows}}},
        "packet_entities": {
            DROPLET: {"guid": DROPLET, "kind": "CREATURE", "entry_id": 191517, "map_id": 2444,
                      "position": {"x": 3630., "y": -60., "z": 41., "instance_id": 2444}},
            LASHER: {"guid": LASHER, "kind": "CREATURE", "entry_id": 191944, "map_id": 2444,
                     "position": {"x": 3660., "y": -60., "z": 41., "instance_id": 2444}}},
    }


def test_hidden_kill_credits_fill_the_live_progress_bar():
    wanted = kill_objective_entries(state())
    assert set(wanted) == {"191517", "191983", "191944", "191917"}
    assert {value[0] for value in wanted.values()} == {"66998"}
    units = {unit["guid"] for unit in kill_objective_units(state())}
    assert units == {DROPLET, LASHER}
    # The nearest droplet, 30 yd ahead: walk to its server point, then Tab.
    (move,) = ServerKillTargetPolicy().propose(state())
    assert move.skill == "MOVE" and move.parameters["server_entity_guid"] == DROPLET
    assert move.parameters["purpose"] == "APPROACH_SERVER_KILL_TARGET"


def test_no_bar_no_guess():
    # Without the TDB bar row, or once the live bar is done, hidden rows stay unmapped.
    assert kill_objective_entries(state(with_bar_row=False)) == {}
    done = state()
    done["active_quests"][0]["objectives"][0]["is_complete"] = True
    assert kill_objective_entries(done) == {}
    # A different live progress bar is not this one.
    assert kill_objective_entries(state(bar="Ruby Lifeshrine defended (10%)")) == {}
