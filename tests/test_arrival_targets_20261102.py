"""REV4 P8.4 ARRIVE / AREA_TRIGGER: the client AreaTrigger is the arrival target.

An objective of type 10 names the trigger; older exploration quests list it in
TDB areatrigger_involvedrelation (62 "The Fargodeep Mine" -> 88).  The client
DB2 row gives the centre with height and the radius: walk there; inside it,
await the server's credit.  No trigger, another continent or an unusable
shape proposes nothing (the POI region walk stays)."""
from types import SimpleNamespace

from wowbot.agent.arrival_targets import ArrivalTargetPolicy, inside

FARGODEEP = {"Pos": [-9800., 100., 40.], "ContinentID": 0, "Radius": 20, "Box_length": 0, "Box_width": 0}


class Supplement:
    def __init__(self, rows):
        self.rows = rows

    def area_trigger(self, identifier):
        row = self.rows.get(identifier)
        return {"status": "REFERENCE_ONLY", "trigger": row} if row else {}


def objective(text="Scout through the Fargodeep Mine", done=False):
    return SimpleNamespace(objective_id="62:0", description=text,
                           completion_state="COMPLETE" if done else "INCOMPLETE", raw={"mechanism": "ARRIVE"})


def world(*objectives):
    record = SimpleNamespace(quest_id=62, current_state="ACTIVE", objectives=list(objectives or [objective()]))
    return SimpleNamespace(quest_model=SimpleNamespace(records={62: record}))


def state(x=-9600., y=100., z=60., reference=None):
    return {"map_id": 37, "player_world_position": {"x": x, "y": y, "z": z, "z_observed": True,
                                                    "instance_id": 0, "coordinate_space": "WORLD_YARDS"},
            "reference_knowledge": {"quests": {"62": reference or {"objectives": [], "area_triggers": [88]}}}}


def test_an_exploration_quest_walks_to_its_trigger_centre_with_height():
    (move,) = ArrivalTargetPolicy(Supplement({88: FARGODEEP})).propose(world(), state())
    assert move.skill == "MOVE" and move.parameters["purpose"] == "ARRIVE_AREA_TRIGGER"
    assert (move.parameters["x"], move.parameters["y"], move.parameters["z"]) == (-9800., 100., 40.)
    assert move.parameters["z_source"] == "CLIENT_DB2_AREATRIGGER" and move.parameters["area_trigger_id"] == 88
    assert move.parameters["stop_distance"] == 6. and move.priority == 58.


def test_a_type_10_objective_names_its_own_trigger():
    reference = {"objectives": [{"objective_id": 9, "order": 0, "raw_type": 10, "credit_object_id": 10352,
                                 "description": "Locate the Spirit Forge"}]}
    rows = {10352: {**FARGODEEP, "Pos": [1., 2., 3.]}}
    (move,) = ArrivalTargetPolicy(Supplement(rows)).propose(
        world(objective("Locate the Spirit Forge")), state(x=50., y=50., reference=reference))
    assert move.parameters["area_trigger_id"] == 10352


def test_inside_the_trigger_another_continent_or_no_shape_proposes_nothing():
    policy = ArrivalTargetPolicy(Supplement({88: FARGODEEP}))
    assert policy.propose(world(), state(x=-9805., z=41.)) == []
    assert policy.diagnostic["62:62:0"] == "inside_trigger_awaiting_credit"
    elsewhere = ArrivalTargetPolicy(Supplement({88: {**FARGODEEP, "ContinentID": 1}}))
    assert elsewhere.propose(world(), state()) == []
    shapeless = ArrivalTargetPolicy(Supplement({88: {**FARGODEEP, "Radius": 0}}))
    assert shapeless.propose(world(), state()) == []
    two_open = world(objective(), SimpleNamespace(objective_id="62:1", description="Kill 4 kobolds",
                                                  completion_state="INCOMPLETE", raw={"mechanism": "KILL"}))
    assert policy.propose(two_open, state()) == []          # whose trigger? not guessed


def test_height_counts_when_the_server_reports_it():
    trigger = {"x": 0., "y": 0., "z": 0., "radius": 10.}
    assert inside({"x": 3., "y": 0., "z": 2., "z_observed": True}, trigger)
    assert not inside({"x": 3., "y": 0., "z": 30., "z_observed": True}, trigger)
