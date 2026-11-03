"""REV4 visual retirement step 1 (user 2026-10-30): plain world/map values live
in the shared coordinate contract, so navigation and the server path no longer
import them from the vision package."""
import ast
from pathlib import Path

from wowbot.coordinates import MapPoint, WorldPosition

SRC = Path(__file__).resolve().parents[1] / "src"
PLAIN = {"WorldPosition", "MapPoint"}
# Legacy visual dataset tooling that is itself retired with the vision package.
LEGACY_VISUAL = {"wowbot/agent/map_marker_dataset.py"}


def test_the_vision_module_re_exports_the_very_same_classes():
    from wowbot.vision import models
    assert models.WorldPosition is WorldPosition and models.MapPoint is MapPoint
    assert WorldPosition(1., 2.) == models.WorldPosition(1., 2., 0.)


def test_no_module_outside_vision_takes_plain_values_from_the_vision_package():
    offenders = []
    for path in SRC.rglob("*.py"):
        relative = path.relative_to(SRC).as_posix()
        if relative.startswith("wowbot/vision/") or relative in LEGACY_VISUAL:
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8-sig"))):
            if (isinstance(node, ast.ImportFrom) and (node.module or "").startswith("wowbot.vision")
                    and PLAIN & {alias.name for alias in node.names}):
                offenders.append(relative)
    assert offenders == []
