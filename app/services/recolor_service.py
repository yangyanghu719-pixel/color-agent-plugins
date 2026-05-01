from __future__ import annotations

from app.schemas.request_models import RecolorRequest
from app.utils.color_convert import clamp_hsl, compute_hsl_change


class RecolorService:
    @staticmethod
    def recolor(payload: RecolorRequest) -> dict:
        before = clamp_hsl(payload.original_hsl.h, payload.original_hsl.s, payload.original_hsl.l)
        after = clamp_hsl(payload.new_hsl.h, payload.new_hsl.s, payload.new_hsl.l)
        change = compute_hsl_change(before, after)

        return {
            "status": "success",
            "message": "MVP mock recolor preview generated",
            "target_region_id": payload.target_region_id,
            "preview_image_url": f"https://example.com/previews/{payload.image_id}-{payload.target_region_id}.png",
            "before_hsl": before,
            "after_hsl": after,
            "change": change,
        }
