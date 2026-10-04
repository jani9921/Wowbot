import importlib.util
from pathlib import Path

_TOOL = Path(__file__).resolve().parents[1] / "tools" / "remap_world3d_unit_dataset.py"
_spec = importlib.util.spec_from_file_location("remap_world3d_unit_dataset", _TOOL)
remap = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(remap)


def test_humanoid_creature_corpse_become_creature_and_rare_classes_drop():
    text = ("0 0.1 0.1 0.1 0.1\n1 0.2 0.2 0.1 0.1\n2 0.3 0.3 0.1 0.1\n"
            "3 0.4 0.4 0.1 0.1\n4 0.5 0.5 0.1 0.1\n5 0.6 0.6 0.1 0.1\n6 0.7 0.7 0.1 0.1\n")
    result, counts = remap.remap_label_text(text)
    assert [line.split()[0] for line in result.splitlines()] == ["0", "0", "0", "1", "2"]
    assert counts == {0: 3, 1: 1, 2: 1}
    assert result.splitlines()[3] == "1 0.4 0.4 0.1 0.1"


def test_empty_label_stays_empty():
    assert remap.remap_label_text("") == ("", {})
