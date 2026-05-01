from __future__ import annotations

from PIL import Image, ImageFilter
import numpy as np


def mask_to_image(mask: np.ndarray) -> Image.Image:
    arr = (mask.astype(np.uint8)) * 255
    return Image.fromarray(arr, mode="L")


def feather_mask(mask: np.ndarray, radius: float = 2.0) -> Image.Image:
    base = mask_to_image(mask)
    return base.filter(ImageFilter.GaussianBlur(radius=radius))


def create_annotated_overlay(base_rgba: Image.Image, masks: list[np.ndarray], colors: list[tuple[int, int, int]]) -> Image.Image:
    annotated = base_rgba.copy()
    for mask, color in zip(masks, colors):
        alpha = (mask.astype(np.uint8) * 96)
        overlay = Image.new("RGBA", base_rgba.size, color + (0,))
        overlay.putalpha(Image.fromarray(alpha, mode="L"))
        annotated = Image.alpha_composite(annotated, overlay)
    return annotated
