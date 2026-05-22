from __future__ import annotations

import os
from io import BytesIO
from pathlib import Path
from typing import Any

import httpx
from PIL import Image


class ReplicateSegmentService:
    @staticmethod
    def build_replicate_model_ref() -> tuple[str, str, str | None]:
        model = os.getenv("REPLICATE_GROUNDED_SAM_MODEL", "schananas/grounded_sam").strip()
        version = (os.getenv("REPLICATE_GROUNDED_SAM_VERSION") or "").strip() or None
        if model.startswith("http://") or model.startswith("https://"):
            raise ValueError("REPLICATE_GROUNDED_SAM_MODEL should be owner/model, not API page URL")
        if ":" in model:
            return model, model.split(":", 1)[0], model.split(":", 1)[1] or None
        if version and len(version) != 64:
            raise ValueError("REPLICATE_GROUNDED_SAM_VERSION must be full 64-character version id")
        if model == "schananas/grounded_sam" and not version:
            raise ValueError("community model schananas/grounded_sam requires REPLICATE_GROUNDED_SAM_VERSION")
        model_ref = f"{model}:{version}" if version else model
        return model_ref, model, version

    @staticmethod
    def _load_mask_from_output(output: Any) -> Image.Image:
        parsed = ReplicateSegmentService.parse_grounded_sam_output(output)
        if parsed.get("mask_image"):
            return parsed["mask_image"].convert("L")
        if parsed.get("mask_url"):
            resp = httpx.get(parsed["mask_url"], timeout=60)
            resp.raise_for_status()
            return Image.open(BytesIO(resp.content)).convert("L")
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
        if hasattr(output, "read"):
            data = output.read()
            if isinstance(data, bytes):
                return {"mask_image": Image.open(BytesIO(data)).convert("L")}
            return {}
        if isinstance(output, dict):
            for k in ["mask", "mask_url", "segmentation", "output", "image"]:
                v = output.get(k)
                if isinstance(v, str) and v.startswith("http"):
                    return {"mask_url": v, "bbox": output.get("bbox")}
            return {}
        return {}

    @staticmethod
    def segment_objects(image_path: str, objects: list[dict[str, Any]]) -> list[dict[str, Any]]:
        model_ref, model_name, model_version = ReplicateSegmentService.build_replicate_model_ref()

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
            output = client.run(model_ref, input=inputs)
            parsed = ReplicateSegmentService.parse_grounded_sam_output(output)
            raw_output_preview = str(output)[:500]
            masks.append({
                "object": obj,
                "prompt": prompt,
                "replicate_model": model_name,
                "replicate_version": model_version,
                "replicate_model_ref": model_ref,
                "input_keys": sorted(list(inputs.keys())),
                "raw_output_type": type(output).__name__,
                "raw_output_preview": raw_output_preview,
                "mask_output": parsed.get("mask_url"),
                "mask": ReplicateSegmentService._load_mask_from_output(output),
            })
        return masks
