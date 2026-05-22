from __future__ import annotations

import os
from io import BytesIO
from pathlib import Path
from typing import Any

import httpx
from PIL import Image


class ReplicateSegmentService:
    @staticmethod
    def _load_mask_from_output(output: Any) -> Image.Image:
        parsed = ReplicateSegmentService.parse_grounded_sam_output(output)
        if parsed.get("mask_url"):
            resp = httpx.get(parsed["mask_url"], timeout=60)
            resp.raise_for_status()
            return Image.open(BytesIO(resp.content)).convert("L")
        if parsed.get("mask_image"):
            return parsed["mask_image"].convert("L")
        raise RuntimeError("grounded_sam output missing mask")

    @staticmethod
    def parse_grounded_sam_output(output: Any) -> dict[str, Any]:
        if isinstance(output, list):
            # grounded_sam output order:
            # 1) annotated_picture_mask
            # 2) neg_annotated_picture_mask
            # 3) mask
            # 4) inverted_mask
            if len(output) >= 3:
                parsed = ReplicateSegmentService.parse_grounded_sam_output(output[2])
                if parsed:
                    return parsed
            for item in output:
                parsed = ReplicateSegmentService.parse_grounded_sam_output(item)
                if parsed.get("mask_url") and "/mask." in parsed["mask_url"] and "inverted_mask" not in parsed["mask_url"]:
                    return parsed
            for item in output:
                parsed = ReplicateSegmentService.parse_grounded_sam_output(item)
                if parsed:
                    return parsed
            return {}
        if isinstance(output, str):
            if output.startswith("http"):
                return {"mask_url": output}
            return {}
        if hasattr(output, "read") and hasattr(output, "url"):
            return {"mask_url": str(output.url)}
        if isinstance(output, dict):
            for k in ["mask", "mask_url", "segmentation", "output", "image"]:
                v = output.get(k)
                if isinstance(v, str) and v.startswith("http"):
                    return {"mask_url": v, "bbox": output.get("bbox")}
            return {}
        return {}

    @staticmethod
    def segment_objects(image_path: str, objects: list[dict[str, Any]]) -> list[dict[str, Any]]:
        model = os.getenv("REPLICATE_GROUNDED_SAM_MODEL", "schananas/grounded_sam")
        version = os.getenv("REPLICATE_GROUNDED_SAM_VERSION")

        with Path(image_path).open("rb") as f:
            img_bytes = f.read()

        import replicate
        client = replicate.Client(api_token=os.getenv("REPLICATE_API_TOKEN"))
        masks: list[dict[str, Any]] = []
        for obj in objects:
            prompt = (obj.get("label_en") or obj.get("name") or "").strip()
            if not prompt:
                continue
            inputs = {
                "image": BytesIO(img_bytes),
                "mask_prompt": prompt,
                "negative_mask_prompt": "",
                "adjustment_factor": 0,
            }
            if version:
                output = client.run(f"{model}:{version}", input=inputs)
            else:
                output = client.run(model, input=inputs)
            parsed = ReplicateSegmentService.parse_grounded_sam_output(output)
            masks.append({
                "object": obj,
                "prompt": prompt,
                "mask_output": parsed.get("mask_url"),
                "mask": ReplicateSegmentService._load_mask_from_output(output),
            })
        return masks
