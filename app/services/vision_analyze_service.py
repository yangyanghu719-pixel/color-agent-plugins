from __future__ import annotations

import base64
import json
import os
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx


class VisionAnalyzeService:
    IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}

    @staticmethod
    def _is_http_url(value: str) -> bool:
        parsed = urlparse(value)
        return parsed.scheme in {"http", "https"}

    @staticmethod
    def _safe_local_path(input_url: str) -> Path:
        parsed = urlparse(input_url)
        raw_path = parsed.path if parsed.scheme in {"http", "https"} else input_url
        if ".." in Path(raw_path).parts:
            raise ValueError(f"invalid image path (path traversal): {input_url}")

        normalized = raw_path.lstrip("/")
        if raw_path.startswith("/static/"):
            candidate = Path("static") / raw_path.removeprefix("/static/")
        elif normalized.startswith("static/"):
            candidate = Path(normalized)
        else:
            candidate = Path(raw_path)

        suffix = candidate.suffix.lower()
        if suffix not in VisionAnalyzeService.IMAGE_EXTENSIONS:
            raise ValueError(f"unsupported image extension: {suffix or '<none>'}")
        return candidate.resolve()

    @staticmethod
    def _load_image_bytes(input_url: str) -> bytes:
        if VisionAnalyzeService._is_http_url(input_url):
            raise ValueError("http(s) image URL is not supported for local analyze image loading")

        local_path = VisionAnalyzeService._safe_local_path(input_url)
        if not local_path.exists():
            raise FileNotFoundError(f"image not found: {input_url}")
        return local_path.read_bytes()

    @staticmethod
    def build_analysis_context(payload: Any) -> dict[str, Any]:
        original = payload.original_color_regions
        adjusted = payload.adjusted_color_regions
        region_diffs: list[dict[str, Any]] = []
        adjusted_map = {r.id: r for r in adjusted}
        for src in original:
            dst = adjusted_map.get(src.id)
            if not dst:
                continue
            region_diffs.append({"id": src.id, "role": src.role, "percentage": src.percentage, "hue_delta": dst.hsl.h - src.hsl.h, "saturation_delta": dst.hsl.s - src.hsl.s, "lightness_delta": dst.hsl.l - src.hsl.l})

        top_regions = sorted(adjusted, key=lambda x: x.percentage, reverse=True)[:3]
        return {
            "before_image_url": payload.before_image_url,
            "after_image_url": payload.after_image_url,
            "user_goal": payload.user_goal or "用于课程色彩构成实验",
            "original_color_regions": [r.model_dump() for r in original],
            "adjusted_color_regions": [r.model_dump() for r in adjusted],
            "region_diffs": region_diffs,
            "top_regions": [r.model_dump() for r in top_regions],
        }

    @staticmethod
    def load_image_inputs(context: dict[str, Any]) -> dict[str, str]:
        before = VisionAnalyzeService._load_image_bytes(str(context["before_image_url"]))
        after = VisionAnalyzeService._load_image_bytes(str(context["after_image_url"]))
        return {"before_b64": base64.b64encode(before).decode("utf-8"), "after_b64": base64.b64encode(after).decode("utf-8")}

    @staticmethod
    def build_multimodal_prompt(context: dict[str, Any], rule_based_result: dict[str, Any]) -> list[dict[str, Any]]:
        instruction = (
            "你是色彩构成课程助教。必须输出 JSON，字段固定为: summary, overall_impression, hue_analysis, "
            "saturation_analysis, lightness_analysis, color_relationship_analysis, visual_focus_analysis, "
            "emotional_expression, learning_explanation, suggestions(数组), rule_based_tags(数组)。"
            "不要输出 markdown，不要输出额外字段。"
        )
        context_text = {"user_goal": context["user_goal"], "region_diffs": context["region_diffs"], "top_regions": context["top_regions"], "rule_based": rule_based_result}
        return [{"role": "system", "content": instruction}, {"role": "user", "content": [{"type": "text", "text": str(context_text)}]}]

    @staticmethod
    def call_vision_model(messages: list[dict[str, Any]], images: dict[str, str]) -> dict[str, Any]:
        provider = os.getenv("VISION_MODEL_PROVIDER", "openai_compatible")
        api_key = os.getenv("VISION_MODEL_API_KEY")
        model = os.getenv("VISION_MODEL_NAME")
        base_url = os.getenv("VISION_MODEL_BASE_URL")
        if provider != "openai_compatible":
            raise RuntimeError(f"unsupported provider: {provider}")
        if not api_key:
            raise RuntimeError("VISION_MODEL_API_KEY is not configured")
        if not model or not base_url:
            raise RuntimeError("VISION model config is incomplete")

        user_content = messages[-1]["content"]
        user_content.extend([
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{images['before_b64']}"}},
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{images['after_b64']}"}},
        ])
        payload = {"model": model, "messages": messages, "response_format": {"type": "json_object"}}
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        with httpx.Client(timeout=45.0) as client:
            resp = client.post(f"{base_url.rstrip('/')}/chat/completions", json=payload, headers=headers)
            resp.raise_for_status()
            body = resp.json()
        return json.loads(body["choices"][0]["message"]["content"])

    @staticmethod
    def merge_model_and_rule_based_result(model_result: dict[str, Any], rule_based_result: dict[str, Any], fallback_used: bool) -> dict[str, Any]:
        def _txt(key: str, default: str) -> str:
            value = model_result.get(key)
            return value if isinstance(value, str) and value.strip() else default

        suggestions = model_result.get("suggestions") if isinstance(model_result.get("suggestions"), list) else []
        tags = model_result.get("rule_based_tags") if isinstance(model_result.get("rule_based_tags"), list) else []
        if not suggestions:
            suggestions = [rule_based_result["next_step"], rule_based_result["risk"]]
        if not tags:
            tags = list(rule_based_result["tags"])

        return {
            "status": "success",
            "message": "Vision model unavailable; returned rule-based fallback analysis." if fallback_used else "Vision-model analysis generated with rule-based context.",
            "analysis_type": "rule-based-fallback" if fallback_used else "vision-model",
            "summary": _txt("summary", rule_based_result["summary"]),
            "overall_impression": _txt("overall_impression", rule_based_result["visual_feeling"]),
            "hue_analysis": _txt("hue_analysis", rule_based_result["color_relation"]),
            "saturation_analysis": _txt("saturation_analysis", f"整体饱和度趋势：{rule_based_result.get('sat_trend', '见摘要')}"),
            "lightness_analysis": _txt("lightness_analysis", f"整体明度趋势：{rule_based_result.get('light_trend', '见摘要')}"),
            "color_relationship_analysis": _txt("color_relationship_analysis", rule_based_result["color_relation"]),
            "visual_focus_analysis": _txt("visual_focus_analysis", rule_based_result["visual_feeling"]),
            "emotional_expression": _txt("emotional_expression", rule_based_result["suitable_scenario"]),
            "learning_explanation": _txt("learning_explanation", rule_based_result["ai_explanation"]),
            "suggestions": [str(x) for x in suggestions if str(x).strip()],
            "rule_based_tags": [str(x) for x in tags if str(x).strip()],
            "fallback_used": fallback_used,
        }
