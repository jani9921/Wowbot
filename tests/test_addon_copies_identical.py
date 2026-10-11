"""Issue #32: the two addon folders must not drift apart; the installer
copies AIPlayerControllerExport-12.1.0 while tests load the other one."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "addon"


def test_both_addon_copies_are_byte_identical():
    first, second = ROOT / "AIPlayerControllerExport", ROOT / "AIPlayerControllerExport-12.1.0"
    names = sorted(path.name for path in first.iterdir() if path.is_file())
    assert names == sorted(path.name for path in second.iterdir() if path.is_file())
    for name in names:
        assert (first / name).read_bytes() == (second / name).read_bytes(), name
