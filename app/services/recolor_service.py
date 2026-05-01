from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
from PIL import Image

from app.schemas.request_models import RecolorRequest
from app.utils.color_convert import clamp_hsl
from app.utils.image_io import load_image


class RecolorService:
    @staticmethod
    def _static_url_to_path(url: str) -> Path:
        cleaned = url.split("?", 1)[0].split("#", 1)[0]
        if cleaned.startswith("/static/"):
            return Path("static") / cleaned[len("/static/") :]
        return Path(cleaned)

    @staticmethod
    def _load_image_with_fallback(payload: RecolorRequest, segment_result: dict) -> Image.Image:
        try:
            return load_image(str(payload.original_image_url))
        except Exception:
            original_image_path = segment_result.get("original_image_path")
            if original_image_path:
                return load_image(original_image_path)
            raise

    @staticmethod
    def recolor(payload: RecolorRequest) -> dict:
        segment_result_path = Path("static/outputs") / payload.image_id / "segment_result.json"
        if not segment_result_path.exists():
            return {
                "status": "error",
                "message": "未找到对应的图片识别结果，请先调用 /segment。",
                "target_region_id": payload.target_region_id,
                "preview_image_url": "",
                "before_hsl": payload.original_hsl.model_dump(),
                "after_hsl": payload.new_hsl.model_dump(),
                "change": {"hue_change": 0, "saturation_change": 0, "lightness_change": 0},
            }

        with segment_result_path.open("r", encoding="utf-8") as f:
            segment_result = json.load(f)

        region = next((r for r in segment_result.get("color_regions", []) if r.get("id") == payload.target_region_id), None)
        if not region:
            return {
                "status": "error",
                "message": "未找到对应的色彩区域。",
                "target_region_id": payload.target_region_id,
                "preview_image_url": "",
                "before_hsl": payload.original_hsl.model_dump(),
                "after_hsl": payload.new_hsl.model_dump(),
                "change": {"hue_change": 0, "saturation_change": 0, "lightness_change": 0},
            }

        soft_mask_path = Path(region.get("soft_mask_path", ""))
        if not soft_mask_path.exists():
            return {
                "status": "error",
                "message": "目标区域 mask 文件不存在，无法进行局部调色。",
                "target_region_id": payload.target_region_id,
                "preview_image_url": "",
                "before_hsl": payload.original_hsl.model_dump(),
                "after_hsl": payload.new_hsl.model_dump(),
                "change": {"hue_change": 0, "saturation_change": 0, "lightness_change": 0},
            }

        original = RecolorService._load_image_with_fallback(payload, segment_result)
        original_rgb = np.array(original.convert("RGB"), dtype=np.float32)
        mask = np.array(Image.open(soft_mask_path).convert("L"), dtype=np.float32) / 255.0
        mask = np.clip(mask, 0.0, 1.0)

        before = clamp_hsl(payload.original_hsl.h, payload.original_hsl.s, payload.original_hsl.l)
        after = clamp_hsl(payload.new_hsl.h, payload.new_hsl.s, payload.new_hsl.l)
        delta_h = after["h"] - before["h"]
        delta_s = after["s"] - before["s"]
        delta_l = after["l"] - before["l"]

        import colorsys

        rgb_norm = original_rgb / 255.0
        r, g, b = rgb_norm[..., 0], rgb_norm[..., 1], rgb_norm[..., 2]
        flat = np.stack([r.flatten(), g.flatten(), b.flatten()], axis=1)

        hls = np.array([colorsys.rgb_to_hls(px[0], px[1], px[2]) for px in flat], dtype=np.float32)
        h = (hls[:, 0] * 360.0 + delta_h) % 360.0
        l = np.clip(hls[:, 1] * 100.0 + delta_l, 0.0, 100.0)
        s = np.clip(hls[:, 2] * 100.0 + delta_s, 0.0, 100.0)

        adjusted = np.array(
            [colorsys.hls_to_rgb((hh % 360.0) / 360.0, ll / 100.0, ss / 100.0) for hh, ll, ss in zip(h, l, s)],
            dtype=np.float32,
        ).reshape(original_rgb.shape)

        adjusted_rgb = adjusted * 255.0
        alpha = mask[..., None]
        blended = (original_rgb * (1.0 - alpha) + adjusted_rgb * alpha).clip(0, 255).astype(np.uint8)

        preview = Image.fromarray(blended, mode="RGB")
        hash_str = hashlib.md5(f"{payload.target_region_id}-{before}-{after}".encode("utf-8")).hexdigest()[:8]
        output_dir = Path("static/outputs") / payload.image_id
        output_dir.mkdir(parents=True, exist_ok=True)
        output_name = f"recolor_{payload.target_region_id}_{hash_str}.png"
        output_path = output_dir / output_name
        preview.save(output_path)

        return {
            "status": "success",
            "message": "Mask-based local recolor preview generated",
            "target_region_id": payload.target_region_id,
            "preview_image_url": f"/static/outputs/{payload.image_id}/{output_name}",
            "before_hsl": before,
            "after_hsl": after,
            "change": {
                "hue_change": int(delta_h),
                "saturation_change": int(delta_s),
                "lightness_change": int(delta_l),
            },
        }
