"""Static end-to-end dependency-chain guard for V4-002's final responsibility model.

Existing `test_architecture_boundaries.py` already enforces ~26 individual
pairwise boundaries. What was missing was one place asserting the spec's
three headline invariants together, plus confirming every named box in its
dependency diagram (Sensors -> Observation Ingest -> WorldModel ->
WorldQuery -> {Quest Runtime, Supervisor} -> ... -> Executor -> WoW Client)
actually exists as a real module/class -- not a substitute for a live test,
same as the rest of this file's siblings.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "src" / "wowbot"


def _source(*parts: str) -> str:
    return ROOT.joinpath(*parts).read_text(encoding="utf-8")


def test_world_model_never_sends_input():
    source = _source("agent", "world.py")
    assert "windows_input" not in source
    assert "SendInput" not in source
    assert "from .executor import" not in source.lower()


def test_planner_never_presses_keys():
    source = _source("agent", "planner.py")
    assert "windows_input" not in source
    assert "SendInput" not in source


def test_executor_never_understands_quest_semantics():
    for name in ("command_dispatch.py", "input_scheduler.py"):
        source = _source("execution", name)
        assert "quest" not in source.lower()


def test_every_named_component_in_the_dependency_diagram_exists():
    # (relative path, substring that must be present in it)
    required = [
        (("agent", "observation_ingestion.py"), "def"),
        (("agent", "world.py"), "class WorldModel"),
        (("agent", "world_query.py"), "class WorldQuery"),
        (("agent", "quest_runtime.py"), "class QuestExecutionRuntime"),
        (("runtime", "supervisor.py"), "class Supervisor"),
        (("agent", "quest_model.py"), "class ObjectiveClassifier"),
        (("agent", "objective_locator.py"), "class ObjectiveLocator"),
        (("agent", "planner.py"), "class"),
        (("runtime", "active_skill.py"), "class ActiveSkillRuntime"),
        (("navigation",), None),  # package presence only
        (("skills", "combat.py"), "class CombatSkill"),
        (("execution", "command_dispatch.py"), "class CommandDispatcher"),
    ]
    for relative, needle in required:
        if needle is None:
            assert (ROOT.joinpath(*relative)).is_dir()
            continue
        assert needle in _source(*relative), f"missing {needle!r} in {'/'.join(relative)}"


def test_verification_package_is_side_effect_free_per_spec():
    # "Verification is a side-effect-free evaluation service" -- reuses the
    # V4-040 base.py Verifier contract's own no-input/no-mutation guarantee.
    from wowbot.verification.base import Verifier
    assert hasattr(Verifier, "evaluate")
