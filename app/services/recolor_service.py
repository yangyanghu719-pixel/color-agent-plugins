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
        if cleaned.startswith("static/"):
            return Path(cleaned)
        return Path(cleaned)

    @staticmethod
    def _load_image_with_fallback(payload: RecolorRequest, segment_result: dict) -> Image.Image:
        working_path = segment_result.get("working_image_path")
        if working_path:
            try:
                return load_image(working_path)
            except Exception:
                pass

        value = str(payload.original_image_url)
        try:
            if value.startswith("http://") or value.startswith("https://"):
                return load_image(value)
            return load_image(str(RecolorService._static_url_to_path(value)))
        except Exception:
            original_image_path = segment_result.get("original_image_path")
            if original_image_path:
                return load_image(original_image_path)
            raise

    @staticmethod
    def recolor(payload: RecolorRequest) -> dict:
        segment_result_path = Path("static/outputs") / payload.image_id / "segment_result.json"
        if not segment_result_path.exists():
            return {"status": "error", "message": "未找到对应的图片识别结果，请先调用 /segment。", "target_region_id": payload.target_region_id, "preview_image_url": "", "before_hsl": payload.original_hsl.model_dump(), "after_hsl": payload.new_hsl.model_dump(), "change": {"hue_change": 0, "saturation_change": 0, "lightness_change": 0}}

        with segment_result_path.open("r", encoding="utf-8") as f:
            segment_result = json.load(f)

        region = next((r for r in segment_result.get("color_regions", []) if r.get("id") == payload.target_region_id), None)
        if not region:
            return {"status": "error", "message": "未找到对应的色彩区域。", "target_region_id": payload.target_region_id, "preview_image_url": "", "before_hsl": payload.original_hsl.model_dump(), "after_hsl": payload.new_hsl.model_dump(), "change": {"hue_change": 0, "saturation_change": 0, "lightness_change": 0}}

        mask_path_str = region.get("mask_path") or region.get("soft_mask_path", "")
        mask_path = Path(mask_path_str)
        if not mask_path.exists():
            return {"status": "error", "message": "目标区域 mask 文件不存在，无法进行局部调色。", "target_region_id": payload.target_region_id, "preview_image_url": "", "before_hsl": payload.original_hsl.model_dump(), "after_hsl": payload.new_hsl.model_dump(), "change": {"hue_change": 0, "saturation_change": 0, "lightness_change": 0}}

        original = RecolorService._load_image_with_fallback(payload, segment_result)
        original_rgb = np.array(original.convert("RGB"), dtype=np.uint8)
        mask_gray = np.array(Image.open(mask_path).convert("L"), dtype=np.uint8)
        selected = mask_gray > 127
        before = clamp_hsl(payload.original_hsl.h, payload.original_hsl.s, payload.original_hsl.l)
        after = clamp_hsl(payload.new_hsl.h, payload.new_hsl.s, payload.new_hsl.l)
        delta_h, delta_s, delta_l = after["h"] - before["h"], after["s"] - before["s"], after["l"] - before["l"]

        import colorsys

        output_rgb = original_rgb.copy()
        selected_pixels = original_rgb[selected]
        if selected_pixels.size:
            selected_norm = selected_pixels.astype(np.float32) / 255.0
            selected_hls = np.array([colorsys.rgb_to_hls(px[0], px[1], px[2]) for px in selected_norm], dtype=np.float32)
            h = (selected_hls[:, 0] * 360.0 + delta_h) % 360.0
            l = np.clip(selected_hls[:, 1] * 100.0 + delta_l, 0.0, 100.0)
            s = np.clip(selected_hls[:, 2] * 100.0 + delta_s, 0.0, 100.0)
            adjusted_selected = np.array(
                [colorsys.hls_to_rgb((hh % 360.0) / 360.0, ll / 100.0, ss / 100.0) for hh, ll, ss in zip(h, l, s)],
                dtype=np.float32,
            )
            output_rgb[selected] = (adjusted_selected * 255.0).clip(0, 255).astype(np.uint8)

        output_dir = Path("static/outputs") / payload.image_id
        output_dir.mkdir(parents=True, exist_ok=True)
        output_name = f"recolor_{payload.target_region_id}_{hashlib.md5(f'{payload.target_region_id}-{before}-{after}'.encode('utf-8')).hexdigest()[:8]}.png"
        output_path = output_dir / output_name
        Image.fromarray(output_rgb, mode="RGB").save(output_path)

        segment_result["working_image_path"] = str(output_path)
        segment_result.setdefault("adjustment_history", []).append({"target_region_id": payload.target_region_id, "before_hsl": before, "after_hsl": after})
        with segment_result_path.open("w", encoding="utf-8") as f:
            json.dump(segment_result, f, ensure_ascii=False, indent=2)

        return {"status": "success", "message": "Mask-based local recolor preview generated", "target_region_id": payload.target_region_id, "preview_image_url": f"/static/outputs/{payload.image_id}/{output_name}", "before_hsl": before, "after_hsl": after, "change": {"hue_change": int(delta_h), "saturation_change": int(delta_s), "lightness_change": int(delta_l)}}
