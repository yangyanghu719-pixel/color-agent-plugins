from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

import numpy as np
from PIL import Image

from app.schemas.request_models import SegmentRequest
from app.utils.color_convert import rgb_to_hex, rgb_to_hsl
from app.utils.image_io import load_image, resize_for_processing, save_image
from app.utils.mask_utils import create_annotated_overlay, feather_mask, mask_to_image


@dataclass
class ClusterResult:
    center: np.ndarray
    percentage: float
    mask: np.ndarray


class SegmentService:
    @staticmethod
    def _mock(payload: SegmentRequest) -> dict:
        image_url = payload.image_url or "https://example.com/images/default.jpg"
        return {
            "status": "success",
            "message": "MVP mock segmentation completed",
            "image_id": "img-mock-001",
            "original_image_url": image_url,
            "annotated_image_url": "https://example.com/annotated/img-mock-001.png",
            "color_regions": [],
        }

    @staticmethod
    def _kmeans(pixels: np.ndarray, k: int, iterations: int = 20) -> tuple[np.ndarray, np.ndarray]:
        n = len(pixels)
        k = min(k, n)
        rng = np.random.default_rng(42)
        centers = pixels[rng.choice(n, size=k, replace=False)].astype(np.float32)
        labels = np.zeros(n, dtype=np.int32)

        for _ in range(iterations):
            dists = ((pixels[:, None, :] - centers[None, :, :]) ** 2).sum(axis=2)
            new_labels = dists.argmin(axis=1)
            if np.array_equal(new_labels, labels):
                break
            labels = new_labels
            for i in range(k):
                members = pixels[labels == i]
                if len(members) == 0:
                    centers[i] = pixels[rng.integers(0, n)]
                else:
                    centers[i] = members.mean(axis=0)
        return centers, labels

    @staticmethod
    def _role(rank: int, rgb: tuple[int, int, int], hsl: dict[str, int], percentage: float) -> str:
        if rank == 0:
            return "主色"
        if rank == 1:
            return "辅助色"
        spread = max(rgb) - min(rgb)
        if spread < 18 and percentage > 15:
            return "背景色"
        if hsl["s"] >= 55 and percentage <= 20:
            return "点缀色"
        return "辅助色"

    @staticmethod
    def segment_colors(payload: SegmentRequest) -> dict:
        if not payload.image_url:
            return SegmentService._mock(payload)

        image = load_image(payload.image_url)
        image = resize_for_processing(image, max_side=512)

        rgba = np.array(image)
        rgb = rgba[:, :, :3]
        alpha = rgba[:, :, 3]
        valid = alpha > 0
        pixels = rgb[valid].astype(np.float32)

        if len(pixels) == 0:
            return SegmentService._mock(payload)

        centers, labels = SegmentService._kmeans(pixels, payload.color_count)

        label_map = np.full(valid.shape, -1, dtype=np.int32)
        label_map[valid] = labels

        clusters: list[ClusterResult] = []
        total = float(len(labels))
        for i in range(len(centers)):
            m = label_map == i
            cnt = int(m.sum())
            if cnt == 0:
                continue
            clusters.append(ClusterResult(center=centers[i], percentage=cnt * 100.0 / total, mask=m))

        clusters.sort(key=lambda x: x.percentage, reverse=True)
        image_id = f"img-{uuid4().hex[:12]}"

        masks_for_preview: list[np.ndarray] = []
        colors_for_preview: list[tuple[int, int, int]] = []
        regions = []

        for idx, c in enumerate(clusters[: payload.color_count], start=1):
            rgb_tuple = tuple(int(round(x)) for x in c.center)
            hex_color = rgb_to_hex(*rgb_tuple)
            hsl = rgb_to_hsl(*rgb_tuple)
            role = SegmentService._role(idx - 1, rgb_tuple, hsl, c.percentage)

            raw_mask = mask_to_image(c.mask)
            soft_mask = feather_mask(c.mask, radius=2.0)
            mask_url = save_image(raw_mask, f"{image_id}-region-{idx}.png")
            soft_mask_url = save_image(soft_mask, f"{image_id}-region-{idx}-soft.png")

            regions.append(
                {
                    "id": f"region-{idx}",
                    "name": f"{role}-{hex_color}",
                    "hex": hex_color,
                    "rgb": {"r": rgb_tuple[0], "g": rgb_tuple[1], "b": rgb_tuple[2]},
                    "hsl": hsl,
                    "percentage": round(c.percentage, 2),
                    "role": role,
                    "mask_url": mask_url,
                    "soft_mask_url": soft_mask_url,
                    "description": f"该区域为{role}，颜色接近 {hex_color}。",
                }
            )
            masks_for_preview.append(c.mask)
            colors_for_preview.append(rgb_tuple)

        annotated = create_annotated_overlay(image, masks_for_preview, colors_for_preview)
        annotated_url = save_image(annotated, f"{image_id}-annotated.png")

        return {
            "status": "success",
            "message": "Segmentation completed with color clustering",
            "image_id": image_id,
            "original_image_url": payload.image_url,
            "annotated_image_url": annotated_url,
            "color_regions": regions,
        }
