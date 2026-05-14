from __future__ import annotations

from typing import List

from app.schemas.request_models import AnalyzeRequest
from app.services.vision_analyze_service import VisionAnalyzeService
from app.utils.color_analysis import classify_color_relation, classify_contrast_level, compare_color_regions, compute_hue_difference


class AnalyzeService:
    @staticmethod
    def _weighted_avg(values: List[tuple[int, float]]) -> float:
        total_weight = sum(weight for _, weight in values) or 1.0
        return sum(value * weight for value, weight in values) / total_weight

    @staticmethod
    def generate_tags(sat_delta: float, light_delta: float, contrast_changed: float, subject_prominence: bool) -> List[str]:
        tags: List[str] = []
        if sat_delta > 3:
            tags.append("饱和度提升")
        elif sat_delta < -3:
            tags.append("更克制")
        if contrast_changed > 4:
            tags.append("对比增强")
        if light_delta > 3:
            tags.append("明度层次增强")
        elif light_delta < -3:
            tags.append("更柔和")
        if subject_prominence:
            tags.append("主体更突出")
        if not tags:
            tags.append("色彩关系更统一")
        return tags[:4]

    @staticmethod
    def analyze_rule_based(payload: AnalyzeRequest) -> dict:
        changes, major_changes = compare_color_regions(payload.original_color_regions, payload.adjusted_color_regions)
        original_avg_s = AnalyzeService._weighted_avg([(r.hsl.s, r.percentage) for r in payload.original_color_regions])
        adjusted_avg_s = AnalyzeService._weighted_avg([(r.hsl.s, r.percentage) for r in payload.adjusted_color_regions])
        original_avg_l = AnalyzeService._weighted_avg([(r.hsl.l, r.percentage) for r in payload.original_color_regions])
        adjusted_avg_l = AnalyzeService._weighted_avg([(r.hsl.l, r.percentage) for r in payload.adjusted_color_regions])
        sat_delta = adjusted_avg_s - original_avg_s
        light_delta = adjusted_avg_l - original_avg_l
        sat_trend = "提高" if sat_delta > 2 else "降低" if sat_delta < -2 else "基本不变"
        light_trend = "提高" if light_delta > 2 else "降低" if light_delta < -2 else "基本不变"
        top_two = sorted(payload.adjusted_color_regions, key=lambda x: x.percentage, reverse=True)[:2]
        hue_diff = compute_hue_difference(top_two[0].hsl.h, top_two[1].hsl.h) if len(top_two) == 2 else 0
        sat_diff = abs(top_two[0].hsl.s - top_two[1].hsl.s) if len(top_two) == 2 else 0
        light_diff = abs(top_two[0].hsl.l - top_two[1].hsl.l) if len(top_two) == 2 else 0
        relation = classify_color_relation(hue_diff)
        contrast_level = classify_contrast_level(sat_diff, light_diff, hue_diff)
        color_relation = f"主色对的色相关系为{relation}（色相差约{hue_diff}°），整体属于{contrast_level}。"
        subject_prominence = any(((item["role"] in {"主体", "main", "主色"} and item["lightness_change"] > 2) or item["saturation_change"] > 6) for item in major_changes[:2])
        tags = AnalyzeService.generate_tags(sat_delta, light_delta, light_diff, subject_prominence)
        summary = f"本次调整以{sat_trend}饱和度和{light_trend}明度为主，主色关系呈现{relation}，画面对比为{contrast_level}。"
        return {
            "status": "success", "message": "Rule-based analysis built from color regions.", "analysis_type": "rule-based",
            "tags": tags, "color_relation": color_relation, "visual_feeling": "整体观感更平衡，主辅关系较清晰。",
            "suitable_scenario": "设计课堂配色推演、风格探索练习", "summary": summary,
            "ai_explanation": "规则分析可作为学习参考，结合图像观察进一步判断主体突出度和情绪表达。",
            "risk": "如主体不够突出，可提升主体与背景明度差。", "next_step": "建议微调辅助色饱和度与背景明度。",
            "sat_trend": sat_trend, "light_trend": light_trend,
        }

    @staticmethod
    def analyze(payload: AnalyzeRequest) -> dict:
        rule_result = AnalyzeService.analyze_rule_based(payload)
        try:
            context = VisionAnalyzeService.build_analysis_context(payload)
            images = VisionAnalyzeService.load_image_inputs(context)
            messages = VisionAnalyzeService.build_multimodal_prompt(context, rule_result)
            model_result = VisionAnalyzeService.call_vision_model(messages, images)
            return VisionAnalyzeService.merge_model_and_rule_based_result(model_result, rule_result, fallback_used=False)
        except (FileNotFoundError, ValueError) as exc:
            return {"status": "error", "message": str(exc)}
        except Exception:
            return VisionAnalyzeService.merge_model_and_rule_based_result({}, rule_result, fallback_used=True)
