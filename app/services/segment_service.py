from __future__ import annotations

from app.schemas.request_models import SegmentRequest


class SegmentService:
    @staticmethod
    def segment_colors(payload: SegmentRequest) -> dict:
        image_url = str(payload.image_url) if payload.image_url else "https://example.com/images/default.jpg"
        base_regions = [
            {
                "id": "region-1",
                "name": "主体暖红",
                "hex": "#D9534F",
                "rgb": {"r": 217, "g": 83, "b": 79},
                "hsl": {"h": 2, "s": 64, "l": 58},
                "percentage": 34.0,
                "role": "主体",
                "mask_url": "https://example.com/masks/region-1.png",
                "soft_mask_url": "https://example.com/masks/region-1-soft.png",
                "description": "画面中最吸引注意力的暖色区域",
            },
            {
                "id": "region-2",
                "name": "背景中灰",
                "hex": "#7F8C8D",
                "rgb": {"r": 127, "g": 140, "b": 141},
                "hsl": {"h": 184, "s": 6, "l": 52},
                "percentage": 27.0,
                "role": "背景",
                "mask_url": "https://example.com/masks/region-2.png",
                "soft_mask_url": "https://example.com/masks/region-2-soft.png",
                "description": "提供稳定基底的低饱和背景色",
            },
            {
                "id": "region-3",
                "name": "辅助蓝",
                "hex": "#5DADE2",
                "rgb": {"r": 93, "g": 173, "b": 226},
                "hsl": {"h": 204, "s": 69, "l": 63},
                "percentage": 22.0,
                "role": "辅助",
                "mask_url": "https://example.com/masks/region-3.png",
                "soft_mask_url": "https://example.com/masks/region-3-soft.png",
                "description": "与暖红形成冷暖对比，增强层次",
            },
            {
                "id": "region-4",
                "name": "高光浅黄",
                "hex": "#F9E79F",
                "rgb": {"r": 249, "g": 231, "b": 159},
                "hsl": {"h": 48, "s": 88, "l": 80},
                "percentage": 17.0,
                "role": "点缀",
                "mask_url": "https://example.com/masks/region-4.png",
                "soft_mask_url": "https://example.com/masks/region-4-soft.png",
                "description": "小面积高亮点缀，提升活力",
            },
        ]

        return {
            "status": "success",
            "message": "MVP mock segmentation completed",
            "image_id": "img-mock-001",
            "original_image_url": image_url,
            "annotated_image_url": "https://example.com/annotated/img-mock-001.png",
            "color_regions": base_regions[: payload.color_count],
        }
