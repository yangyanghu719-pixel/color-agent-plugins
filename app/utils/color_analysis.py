from __future__ import annotations

from typing import Dict, List, Tuple


def compute_hue_difference(h1: int, h2: int) -> int:
    diff = abs(h1 - h2) % 360
    return int(min(diff, 360 - diff))


def classify_color_relation(hue_difference: int) -> str:
    if hue_difference <= 15:
        return "同类色"
    if hue_difference <= 45:
        return "邻近色"
    if hue_difference <= 105:
        return "中差色"
    if hue_difference <= 150:
        return "对比色"
    return "近互补/互补色"


def classify_contrast_level(
    saturation_difference: float,
    lightness_difference: float,
    hue_difference: float,
) -> str:
    score = saturation_difference * 0.4 + lightness_difference * 0.35 + (hue_difference / 180.0 * 100) * 0.25
    if score < 25:
        return "低对比"
    if score < 45:
        return "中等对比"
    if score < 65:
        return "较高对比"
    return "高对比"


def compare_color_regions(original_regions: List, adjusted_regions: List) -> Tuple[List[Dict], List[Dict]]:
    original_map = {region.id: region for region in original_regions}
    adjusted_map = {region.id: region for region in adjusted_regions}

    changes: List[Dict] = []
    major_changes: List[Dict] = []
    for region_id in original_map:
        if region_id not in adjusted_map:
            continue
        before = original_map[region_id]
        after = adjusted_map[region_id]

        hue_change = ((after.hsl.h - before.hsl.h + 540) % 360) - 180
        sat_change = after.hsl.s - before.hsl.s
        light_change = after.hsl.l - before.hsl.l

        item = {
            "id": region_id,
            "hue_change": int(hue_change),
            "saturation_change": int(sat_change),
            "lightness_change": int(light_change),
            "hex_before": before.hex,
            "hex_after": after.hex,
            "percentage": before.percentage,
            "role": before.role,
            "before_hsl": before.hsl,
            "after_hsl": after.hsl,
        }
        changes.append(item)

        magnitude = abs(hue_change) / 180 * 100 + abs(sat_change) + abs(light_change)
        if magnitude >= 25:
            major_changes.append(item)

    changes.sort(key=lambda x: x["percentage"], reverse=True)
    major_changes.sort(key=lambda x: x["percentage"], reverse=True)
    return changes, major_changes
