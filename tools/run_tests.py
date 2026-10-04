"""
Minimal, dependency-free test runner.

This project's test files intentionally use plain `assert` statements
and plain `test_*` functions (no pytest-specific fixtures/decorators),
so they can run under this tiny runner in environments without network
access to install pytest. When pytest IS available (e.g. in the real
dev environment / CI), just run `pytest tests/` directly instead --
these same test files work unmodified under pytest.
"""

from __future__ import annotations

import importlib
import inspect
import sys
import tempfile
import traceback
from pathlib import Path


def discover_test_modules(tests_dir: Path):
    for path in sorted(tests_dir.glob("test_*.py")):
        module_name = f"tests.{path.stem}"
        yield module_name


def main() -> int:
    repo_root = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(repo_root))
    tests_dir = repo_root / "tests"

    total = 0
    failed = 0

    for module_name in discover_test_modules(tests_dir):
        module = importlib.import_module(module_name)
        test_funcs = [
            (name, obj) for name, obj in inspect.getmembers(module, inspect.isfunction)
            if name.startswith("test_") and obj.__module__ == module.__name__
        ]
        for name, func in test_funcs:
            total += 1
            try:
                params = inspect.signature(func).parameters
                if "tmp_path" in params:
                    with tempfile.TemporaryDirectory() as temp_dir:
                        func(tmp_path=Path(temp_dir))
                else:
                    func()
                print(f"PASS  {module_name}.{name}")
            except Exception:
                failed += 1
                print(f"FAIL  {module_name}.{name}")
                traceback.print_exc()

    print(f"\n{total - failed}/{total} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
