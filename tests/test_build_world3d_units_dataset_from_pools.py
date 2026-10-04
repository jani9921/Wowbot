import importlib.util
from pathlib import Path

_TOOL = Path(__file__).resolve().parents[1] / "tools" / "build_world3d_units_dataset_from_pools.py"
_spec = importlib.util.spec_from_file_location("build_world3d_units_dataset_from_pools", _TOOL)
builder = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(builder)


def test_original_stem_strips_nested_combine_prefixes_but_keeps_frame_parts():
    exported = ("s0_world3d_annotation_combined_1794_v3__s0_world3d_annotation_combined_1077_v1__"
                "s0_world3d_labeling_4k_reviewed_577_export_v3__video-6671fd10__f000000180__t0000003.000")
    assert builder.original_stem(exported) == "video-6671fd10__f000000180__t0000003.000"
    assert builder.original_stem("video__f1__t2") == "video__f1__t2"


def test_new_frames_inherit_nearest_assigned_neighbour():
    ordered = [("a", None), ("b", "train"), ("c", None), ("d", None), ("e", "test"), ("f", None)]
    assert builder.inherit_splits(ordered) == ["train", "train", "train", "test", "test", "test"]


def test_unassigned_source_uses_contiguous_blocks():
    splits = builder.inherit_splits([(str(i), None) for i in range(400)])
    assert splits[:20] == ["train"] * 20
    assert splits.count("train") == 280 and splits.count("val") == 60 and splits.count("test") == 60
