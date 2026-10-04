"""IsIndoors flips are stored as verified entrances (design doc §10.5)."""
import json

from wowbot.navigation.entrance_verification import EntranceObserver
from wowbot.navigation.navigation_context import NavigationContextClassifier


def _state(x, indoors):
    return {"player_world_position": {"x": x, "y": 0., "z": 5., "instance_id": 2175},
            "movement": {"indoors": indoors}, "map_id": 1409, "subzone_name": "Spider Cave"}


def test_enter_and_exit_are_recorded_with_the_positions_around_the_flip(tmp_path):
    observer = EntranceObserver(tmp_path / "verified_entrances.jsonl")
    assert observer.observe(_state(0., False), 1.) is None
    assert observer.observe(_state(2., False), 2.) is None
    entered = observer.observe(_state(4., True), 3.)
    assert entered["direction"] == "ENTER" and entered["before"]["x"] == 2. and entered["after"]["x"] == 4.
    exited = observer.observe(_state(1., False), 9.)
    assert exited["direction"] == "EXIT"
    lines = (tmp_path / "verified_entrances.jsonl").read_text(encoding="utf-8").splitlines()
    assert [json.loads(line)["direction"] for line in lines] == ["ENTER", "EXIT"]


def test_navigation_context_reads_the_addon_indoors_flag():
    """The addon exports IsIndoors() as movement.indoors; the classifier only
    read a top-level is_indoors that never existed."""
    assessment = NavigationContextClassifier().classify({"movement": {"indoors": True}})
    assert assessment.context.value == "INDOOR"
