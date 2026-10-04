import importlib.util
from pathlib import Path

_TOOL = Path(__file__).resolve().parents[1] / "tools" / "export_world3d_unit_review_pool.py"
_spec = importlib.util.spec_from_file_location("export_world3d_unit_review_pool", _TOOL)
export = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(export)


def test_frame_key_for_exported_and_appended_records():
    exported = {"image": "review/images/s0_world3d_a__s0_world3d_b__vid-1__f000000180__t0000003.000.jpg"}
    appended = {"image": "review/images/world3d_dragonflight_part7_300_v1__vid-2__f000000060__t0000001.000.jpg",
                "source_pool": "world3d_dragonflight_part7_300_v1"}
    assert export.frame_key(exported) == ("vid-1", "vid-1__f000000180__t0000003.000", 180)
    assert export.frame_key(appended) == ("vid-2", "vid-2__f000000060__t0000001.000", 60)
