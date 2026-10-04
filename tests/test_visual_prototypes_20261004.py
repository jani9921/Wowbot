"""User 2026-10-04: learn what the quest's targets look like from the
hovers, skip look-alikes of corpses / unrelated units, inspect similar ones
first."""
import numpy as np

from wowbot.agent.active_perception import ActivePerception
from wowbot.agent.models import Goal, Observation
from wowbot.agent.visual_prototypes import VisualPrototypeMemory
from wowbot.agent.world import WorldModel
from wowbot.vision.visual_signature import appearance_embedding

RNG = np.random.default_rng(7)


def crop(bgr, h=60, w=30, noise=18):
    base = np.zeros((h, w, 3), np.int16)+np.array(bgr, np.int16)
    return np.clip(base+RNG.integers(-noise, noise, base.shape), 0, 255).astype(np.uint8)


CADAVER = (70, 140, 95)      # pale green abomination (BGR)
CORPSE = (40, 45, 120)       # dark red pile
SOLDIER = (150, 110, 60)     # blue tabard


def candidate(track, look, *, h=60, w=30):
    return {"track_id": track, "source": "WORLD3D", "kind": "unknown_subject_candidate",
            "detector_kind": "unknown_subject_candidate", "x": .5, "y": .5, "stable_frames": 5,
            "semantic_type": "UNKNOWN", "confidence": .7, "appearance": {},
            "visual_signature": {"embedding": appearance_embedding(crop(look, h=h, w=w))}}


def test_embedding_keeps_one_look_close_and_others_apart():
    same = np.dot(appearance_embedding(crop(CADAVER)), appearance_embedding(crop(CADAVER, h=44, w=22)))
    other = np.dot(appearance_embedding(crop(CADAVER)), appearance_embedding(crop(SOLDIER)))
    assert same > other + .2


def test_hover_labels_the_box_and_scores_look_alikes():
    memory = VisualPrototypeMemory()
    state = {"visual_candidates": [candidate("A", CADAVER), candidate("B", CORPSE)]}
    assert memory.observe_hover(state, guid="ClientActor-1", unit={"name": "Monstrous Cadaver"},
                                track_id="A", quest_id=55879, open_quest_ids={"55879"}, at=1.) == "POSITIVE"
    assert memory.observe_hover(state, guid="Creature-2", unit={"name": "Wild Boar", "is_dead": True},
                                track_id="B", quest_id=None, open_quest_ids={"55879"}, at=2.) == "NEGATIVE"
    scene = [candidate("C", CADAVER, h=50, w=26), candidate("D", CORPSE, h=50, w=26),
             candidate("E", SOLDIER)]
    assert memory.annotate(scene, {"55879"}) == 3
    lift = {item["track_id"]: item["appearance"]["prototype_lift"] for item in scene}
    assert lift["C"] > .5 and lift["D"] < 0 and lift["C"] > lift["E"]
    # Turn-in mode (no open quest): nothing is scored, friendly NPCs stay neutral.
    fresh = [candidate("F", CORPSE)]
    assert memory.annotate(fresh, set()) == 0 and "prototype_lift" not in fresh[0]["appearance"]


def test_prototypes_persist_per_profile(tmp_path):
    memory = VisualPrototypeMemory(tmp_path / "p.json")
    memory.add([1., 0.], positive=True, quest_id=7, guid="g")
    memory.save(force=True)
    assert VisualPrototypeMemory(tmp_path / "p.json").positive["7"][0]["guid"] == "g"


def _world():
    value = WorldModel()
    value.ingest(Observation.create({"session_id": "s", "frame_id": "f", "timestamp": 1,
                                     "map_id": 1409, "position": {"x": .5, "y": .5}, "orientation": 0,
                                     "player_present": True}, 1))
    return value


def test_look_alike_of_a_confirmed_target_is_probed_first():
    perception, goal = ActivePerception(), Goal.parse("Questelj", 1)
    liked = {**candidate("C", CADAVER), "appearance": {"prototype_lift": 1.}}
    rejected = {**candidate("D", CORPSE), "appearance": {"prototype_lift": -1.}}
    good = perception.evaluate(liked, _world(), goal)
    bad = perception.evaluate(rejected, _world(), goal)
    assert good["utility"] > bad["utility"]
    assert good["world3d_features"]["prototype_lift"] == 1.


def test_mouseover_hover_feeds_the_world_prototypes():
    world = WorldModel()
    box = candidate("WORLD3D:5", CADAVER)
    quest = {"quest_id": 55879, "title": "Ride", "is_complete": False, "objectives": [
        {"description": "0/8 Monstrous Cadaver slain", "type": "KILL", "raw_type": "monster",
         "current": 0, "required": 8}]}
    world.ingest(Observation.create({
        "session_id": "s", "frame_id": "e", "timestamp": .5, "monotonic_time": .5, "map_id": 1409,
        "position": {"x": .5, "y": .5}, "orientation": 0., "player_present": True,
        "active_quests": [quest]}, .5))
    world.projections["WORLD3D_TEST"] = {"visual_candidates": [box]}
    world.ingest(Observation.create({
        "session_id": "s", "frame_id": "f", "timestamp": 1., "monotonic_time": 1., "map_id": 1409,
        "position": {"x": .5, "y": .5}, "orientation": 0., "player_present": True,
        "active_quests": [quest],
        "mouseover": {"guid": "ClientActor-3-1-79", "name": "Monstrous Cadaver", "quest_id": 55879,
                      "quest_related": True, "is_attackable": False, "is_dead": False},
        "mouseover_sample_time": 1., "cursor_position": {"nx": .5, "ny": .5, "sample_time": 1.},
        "cursor_sample_time": 1.}, 1.))
    memory = world.visual_prototypes
    assert memory.positive.get("55879"), memory.snapshot()
