from __future__ import annotations

import colorsys


def hex_to_rgb(hex_color: str) -> dict[str, int]:
    value = hex_color.strip().lstrip("#")
    if len(value) != 6:
        raise ValueError("HEX color must be 6 characters long")
    return {
        "r": int(value[0:2], 16),
        "g": int(value[2:4], 16),
        "b": int(value[4:6], 16),
    }


def rgb_to_hex(r: int, g: int, b: int) -> str:
    if any(not 0 <= c <= 255 for c in (r, g, b)):
        raise ValueError("RGB values must be in 0-255")
    return f"#{r:02X}{g:02X}{b:02X}"


def rgb_to_hsl(r: int, g: int, b: int) -> dict[str, int]:
    if any(not 0 <= c <= 255 for c in (r, g, b)):
        raise ValueError("RGB values must be in 0-255")
    h, l, s = colorsys.rgb_to_hls(r / 255, g / 255, b / 255)
    return {
        "h": int(round(h * 360)) % 360,
        "s": int(round(s * 100)),
        "l": int(round(l * 100)),
    }


def hsl_to_rgb(h: int, s: int, l: int) -> dict[str, int]:
    h, s, l = clamp_hsl(h, s, l).values()
    r, g, b = colorsys.hls_to_rgb((h % 360) / 360, l / 100, s / 100)
    return {
        "r": int(round(r * 255)),
        "g": int(round(g * 255)),
        "b": int(round(b * 255)),
    }


def hsl_to_hex(h: int, s: int, l: int) -> str:
    rgb = hsl_to_rgb(h, s, l)
    return rgb_to_hex(rgb["r"], rgb["g"], rgb["b"])


def clamp_hsl(h: int, s: int, l: int) -> dict[str, int]:
    clamped_h = h % 360
    clamped_s = max(0, min(100, int(round(s))))
    clamped_l = max(0, min(100, int(round(l))))
    return {"h": clamped_h, "s": clamped_s, "l": clamped_l}


def compute_hsl_change(before: dict[str, int], after: dict[str, int]) -> dict[str, int]:
    return {
        "delta_h": int(after["h"] - before["h"]),
        "delta_s": int(after["s"] - before["s"]),
        "delta_l": int(after["l"] - before["l"]),
    }
