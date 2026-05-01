from app.utils.color_convert import (
    clamp_hsl,
    compute_hsl_change,
    hex_to_rgb,
    hsl_to_hex,
    hsl_to_rgb,
    rgb_to_hex,
    rgb_to_hsl,
)


def test_hex_rgb_roundtrip():
    rgb = hex_to_rgb("#FF8800")
    assert rgb == {"r": 255, "g": 136, "b": 0}
    assert rgb_to_hex(**rgb) == "#FF8800"


def test_rgb_hsl_roundtrip():
    hsl = rgb_to_hsl(255, 0, 0)
    assert hsl["h"] in (0, 360)
    assert hsl["s"] == 100
    assert hsl["l"] == 50
    rgb = hsl_to_rgb(hsl["h"], hsl["s"], hsl["l"])
    assert rgb == {"r": 255, "g": 0, "b": 0}


def test_hsl_to_hex_and_clamp_change():
    assert hsl_to_hex(120, 100, 50) == "#00FF00"
    clamped = clamp_hsl(361, 120, -2)
    assert clamped == {"h": 1, "s": 100, "l": 0}
    delta = compute_hsl_change({"h": 10, "s": 20, "l": 30}, {"h": 15, "s": 10, "l": 40})
    assert delta == {"delta_h": 5, "delta_s": -10, "delta_l": 10}
