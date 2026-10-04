from wowbot.vision.world3d.candidates import _Component, _hue_sector, _plate_appearance


def component_for_rgb(r: int, g: int, b: int) -> _Component:
    return _Component(None, 100, 0.8, max(r, g, b) - min(r, g, b), max(r, g, b), r, g, b)


def test_relation_colours_are_nonsemantic_appearance():
    for rgb in ((80, 180, 70), (210, 45, 35), (220, 190, 35)):
        assert _plate_appearance(component_for_rgb(*rgb))["cue"] == "possible_nameplate_like"


def test_every_other_recognized_nameplate_color_stays_appearance_only():
    # Representative class-colored/non-relation plate colors.
    samples = [
        (105, 55, 180),   # purple / Demon Hunter-ish
        (105, 190, 225),  # cyan / Mage-ish
        (245, 120, 35),   # orange / Druid-ish
        (245, 150, 195),  # pink / Paladin-ish
        (210, 175, 130),  # tan / Warrior-ish
        (245, 245, 245),  # white / Priest-ish
    ]
    for rgb in samples:
        sector = _hue_sector(component_for_rgb(*rgb))
        assert sector not in {"green", "red", "yellow", "other"}
        appearance = _plate_appearance(component_for_rgb(*rgb))
        assert "entity_type" not in appearance and "relation" not in appearance


def test_arbitrary_plate_colour_does_not_assign_identity():
    component = component_for_rgb(125, 85, 155)
    appearance = _plate_appearance(component)
    assert set(appearance) == {"hue_family", "geometry", "brightness", "saturation", "cue"}
