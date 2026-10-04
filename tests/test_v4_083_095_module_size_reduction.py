"""V4-083/V4-095: lock in the two authority-neutral runtime extractions.

Runtime recognition stabilization and engine status/event projection live in
small pure modules.  The canonical AgentRuntime/AutonomousAgent retain the one
orchestration and finalization authority; the extracted modules cannot ingest,
dispatch, plan or finalize actions.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "src" / "wowbot"


def test_runtime_py_is_measurably_smaller_after_extraction():
    lines = (ROOT / "agent" / "runtime.py").read_text(encoding="utf-8").splitlines()
    # Was 981 lines before the V4-083/V4-095 extraction.
    assert len(lines) < 600
    diagnostics = (ROOT / "agent" / "runtime_diagnostics_phase.py").read_text(
        encoding="utf-8")
    forbidden = ("CommandDispatcher", "InputBackend", ".dispatch(",
                 "Planner(", "SkillExecutor", ".ingest(")
    assert not any(token in diagnostics for token in forbidden)
    safety = (ROOT / "agent" / "runtime_safety_phase.py").read_text(encoding="utf-8")
    assert not any(token in safety for token in forbidden)
    observation = (ROOT / "agent" / "runtime_observation_phase.py").read_text(
        encoding="utf-8")
    perception = (ROOT / "agent" / "runtime_perception_phase.py").read_text(
        encoding="utf-8")
    authority_forbidden = (
        "CommandDispatcher", "InputBackend", ".dispatch(", "Planner(",
        "SkillExecutor", ".finish(", ".finalize(",
    )
    assert not any(token in observation for token in authority_forbidden)
    assert not any(token in perception for token in authority_forbidden)


def test_runtime_observation_and_perception_phases_are_explicitly_wired():
    runtime = (ROOT / "agent" / "runtime.py").read_text(encoding="utf-8")
    assert "update_runtime_perception(self, payload, current)" in runtime
    assert "build_runtime_observations(" in runtime
    assert "Observation.create(" not in runtime


def test_engine_py_is_measurably_smaller_after_pure_projection_extraction():
    lines = (ROOT / "agent" / "engine.py").read_text(encoding="utf-8").splitlines()
    assert len(lines) < 900


def test_world_model_trace_projection_is_extracted_from_world_py():
    lines = (ROOT / "agent" / "world.py").read_text(encoding="utf-8").splitlines()
    assert len(lines) < 850
    source = "\n".join((
        (ROOT / "agent" / "world_trace_graph.py").read_text(encoding="utf-8"),
        (ROOT / "agent" / "world_prediction_runtime.py").read_text(encoding="utf-8"),
    ))
    forbidden = ("CommandDispatcher", "InputBackend", ".dispatch(", "Planner(",
                 "SkillExecutor", ".finalize(")
    assert not any(token in source for token in forbidden)


def test_engine_projection_module_has_no_input_or_planning_authority():
    source = (ROOT / "agent" / "engine_runtime_projection.py").read_text(encoding="utf-8")
    forbidden = ("CommandDispatcher", "InputBackend", ".dispatch(", ".ingest(",
                 "SkillExecutor", "Planner(", ".finish(", ".finalize(")
    assert not any(token in source for token in forbidden)


def test_extracted_helpers_live_in_their_own_module():
    from wowbot.agent import visual_recognition_stabilizer as extracted
    assert hasattr(extracted, "_manual_mouseover_learning_probe")
    assert hasattr(extracted, "_publishable_visual_matches")
    assert hasattr(extracted, "_VisualRecognitionStabilizer")


def test_every_pre_existing_import_path_still_resolves_identically():
    # tests/test_agent_runtime.py imports these three names directly from
    # wowbot.agent.runtime -- confirm the re-export keeps that path working
    # and pointing at the exact same objects (not a copy).
    from wowbot.agent import runtime, visual_recognition_stabilizer
    assert runtime._manual_mouseover_learning_probe is visual_recognition_stabilizer._manual_mouseover_learning_probe
    assert runtime._publishable_visual_matches is visual_recognition_stabilizer._publishable_visual_matches
    assert runtime._VisualRecognitionStabilizer is visual_recognition_stabilizer._VisualRecognitionStabilizer
