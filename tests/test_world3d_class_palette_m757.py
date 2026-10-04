from dataclasses import replace

from wowbot.vision.world3d.candidates import CLASS_COLORS, CLASS_COLOR_ALIASES, _Component, _class_match


def component_for_hex(hex_color: str) -> _Component:
    r = int(hex_color[1:3], 16)
    g = int(hex_color[3:5], 16)
    b = int(hex_color[5:7], 16)
    return _Component(None, 100, 0.8, max(r, g, b) - min(r, g, b), max(r, g, b), r, g, b)


def test_all_declared_class_colors_match_their_class():
    for name, color in CLASS_COLORS.items():
        detected_name, detected_color = _class_match(component_for_hex(color))
        assert detected_name == name
        assert detected_color == color


def test_mage_alias_matches_mage():
    alias = next(iter(CLASS_COLOR_ALIASES["mage"]))
    detected_name, detected_color = _class_match(component_for_hex(alias))
    assert detected_name == "mage"
    assert detected_color == CLASS_COLORS["mage"]
