from wowbot.vision.world3d.candidates import (
    CLASS_COLORS,
    CLASS_COLOR_ALIASES,
    _Component,
    _class_match,
    _plate_appearance,
)


def component_for_hex(hex_color: str) -> _Component:
    r = int(hex_color[1:3], 16)
    g = int(hex_color[3:5], 16)
    b = int(hex_color[5:7], 16)
    return _Component(None, 100, 0.8, max(r, g, b) - min(r, g, b), max(r, g, b), r, g, b)


def test_all_reference_class_colors_have_a_palette_match():
    for name, color in CLASS_COLORS.items():
        detected_name, detected_color = _class_match(component_for_hex(color))
        assert detected_name == name
        assert detected_color == color


def test_mage_alternate_color_maps_to_mage():
    detected_name, detected_color = _class_match(component_for_hex("#3FC7EB"))
    assert detected_name == "mage"
    assert detected_color == CLASS_COLORS["mage"]


def test_colour_is_only_appearance_evidence():
    for color in ("#ABD473", "#FFF569", "#C41E3A"):
        appearance = _plate_appearance(component_for_hex(color))
        assert appearance["cue"] == "possible_nameplate_like"
        assert not any(key in appearance for key in ("entity_type", "relation", "role"))


def test_unique_class_colors_do_not_become_player_semantics():
    expected = {
        "demon_hunter": "#A330C9",
        "druid": "#FF7D0A",
        "evoker": "#33937F",
        "mage": "#69CCF0",
        "monk": "#00FF96",
        "paladin": "#F58CBA",
        "priest": "#FFFFFF",
        "shaman": "#0070DE",
        "warlock": "#9482C9",
        "warrior": "#C79C6E",
    }
    for name, color in expected.items():
        appearance = _plate_appearance(component_for_hex(color))
        assert appearance["hue_family"]
        assert "player" not in appearance.values()
