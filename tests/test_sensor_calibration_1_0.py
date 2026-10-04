from wowbot.agent.memory import AgentMemory


def context():
    return {"domain": "SENSOR", "game_build": "12.1.0", "addon_version": "1.0",
            "ui_scale": .7, "width": 1600, "height": 900}


def test_sensor_profile_exposes_precision_recall_and_confusion(tmp_path):
    memory = AgentMemory(tmp_path / "sensor.sqlite3")
    samples = [
        ("QUEST_GIVER", "QUEST_GIVER"),
        ("QUEST_GIVER", "QUEST_GIVER"),
        ("QUEST_GIVER", "SCENERY"),
        ("UNKNOWN", "QUEST_GIVER"),
    ]
    for at, (predicted, actual) in enumerate(samples, 1):
        memory.record_sensor_outcome("WORLD3D", "QUEST_GIVER", context(),
            correct=predicted == actual, at=at, latency=.03, error="" if predicted == actual else "mismatch",
            provenance={"ground_truth": "MOUSEOVER"},
            predicted_label=predicted, actual_label=actual)
    profile = memory.sensor_profile("WORLD3D", "QUEST_GIVER", context())
    assert profile["labelled_samples"] == 4
    assert 0 < profile["historical_precision"] < 1
    assert 0 < profile["historical_recall"] < 1
    assert profile["confusion_matrix"]["QUEST_GIVER"]["UNKNOWN"] == 1
    assert profile["confusion_matrix"]["SCENERY"]["QUEST_GIVER"] == 1


def test_legacy_unlabelled_sensor_trials_remain_compatible(tmp_path):
    memory = AgentMemory(tmp_path / "sensor.sqlite3")
    memory.record_sensor_outcome("MINIMAP_CV", "*", context(), correct=True,
                                 at=1, latency=.02, error="", provenance={})
    profile = memory.sensor_profile("MINIMAP_CV", "*", context())
    assert profile["samples"] == 1
    assert profile["labelled_samples"] == 0
    assert profile["historical_recall"] == profile["historical_precision"]
