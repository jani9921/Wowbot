"""Issues #81/#87: every retained module under src/adapters, src/core and
src/mocks must import; broken legacy modules were retired, not redirected."""
import importlib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
MODULES = sorted(
    ".".join(path.relative_to(ROOT).with_suffix("").parts)
    for package in ("src/adapters", "src/core", "src/mocks") if (ROOT / package).is_dir()
    for path in (ROOT / package).glob("*.py"))


@pytest.mark.parametrize("module", MODULES)
def test_retained_legacy_module_imports(module):
    importlib.import_module(module)


def test_retired_modules_stay_retired():
    for path in ("src/adapters/world_map.py", "src/adapters/minimap.py",
                 "src/core/observation_replay.py", "src/mocks/mock_client.py",
                 "tools/replay_observations.py", "tools/observe_client_state.py"):
        assert not (ROOT / path).exists(), path
