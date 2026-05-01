from __future__ import annotations

from typing import List

from app.schemas.request_models import AnalyzeRequest
from app.utils.color_analysis import (
    classify_color_relation,
    classify_contrast_level,
    compare_color_regions,
    compute_hue_difference,
)


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
    def generate_visual_feeling(sat_delta: float, light_delta: float, contrast_level: str) -> str:
        if sat_delta > 3 and contrast_level in {"较高对比", "高对比"}:
            return "整体更醒目，视觉张力增强。"
        if sat_delta < -3 and light_delta < 3:
            return "画面更柔和、稳定，情绪更克制。"
        if contrast_level == "低对比":
            return "画面统一柔和，但视觉焦点相对弱。"
        return "整体观感更平衡，主辅关系较清晰。"

    @staticmethod
    def generate_suitable_scenario(sat_delta: float, light_delta: float, contrast_level: str) -> str:
        if sat_delta > 3 and contrast_level in {"较高对比", "高对比"}:
            return "宣传海报、活动视觉、社交媒体封面"
        if sat_delta < -3 and abs(light_delta) <= 4:
            return "品牌视觉、展览导视、产品包装、文艺类视觉"
        if sat_delta <= 0 and contrast_level == "低对比":
            return "背景视觉、生活方式海报、教学案例"
        return "设计课堂配色推演、风格探索练习"

    @staticmethod
    def generate_risk(sat_after: float, contrast_level: str, light_diff: float, relation: str) -> str:
        if sat_after >= 75:
            return "部分区域饱和度偏高，可能造成视觉刺激过强。"
        if light_diff < 12:
            return "主辅明度对比偏低，主体可能不够突出，远距离可读性会下降。"
        if contrast_level == "高对比":
            return "对比强度较高，长时间观看可能产生视觉疲劳。"
        if relation in {"同类色", "邻近色"} and contrast_level == "低对比":
            return "色彩关系较统一，但可能缺少明确视觉重点。"
        return "当前风险较低，可继续微调辅助色以优化层次。"

    @staticmethod
    def generate_next_step(sat_delta: float, light_delta: float, relation: str, contrast_level: str) -> str:
        if sat_delta > 5:
            return "可以略微降低辅助色饱和度，让主色更突出。"
        if light_delta < -4:
            return "可以提高主体色明度，增强远距离识别度。"
        if relation in {"对比色", "近互补/互补色"} and contrast_level == "高对比":
            return "可以减少色相跳变，让画面更稳定。"
        return "可以保留当前主色关系，只微调明度层次。"

    @staticmethod
    def generate_ai_explanation(
        major_change_text: str,
        sat_trend: str,
        light_trend: str,
        relation: str,
        contrast_level: str,
        visual_feeling: str,
        scenario: str,
        risk: str,
    ) -> str:
        return (
            f"相比原图，这次调整主要改变了{major_change_text}。"
            f"因为整体饱和度{sat_trend}、明度{light_trend}，所以画面的视觉节奏发生了变化。"
            f"从色彩构成上看，主色与辅助色之间形成了{relation}（{contrast_level}）关系，这使画面{visual_feeling.rstrip('。')}。"
            f"这种调整更适合{scenario}。"
            f"需要注意的是，{risk}"
        )

    @staticmethod
    def analyze(payload: AnalyzeRequest) -> dict:
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

        original_light_diff = 0
        if len(payload.original_color_regions) >= 2:
            original_top_two = sorted(payload.original_color_regions, key=lambda x: x.percentage, reverse=True)[:2]
            original_light_diff = abs(original_top_two[0].hsl.l - original_top_two[1].hsl.l)
        contrast_changed = light_diff - original_light_diff

        subject_prominence = any(
            (item["role"] in {"主体", "main", "主色"} and item["lightness_change"] > 2) or item["saturation_change"] > 6
            for item in major_changes[:2]
        )

        tags = AnalyzeService.generate_tags(sat_delta, light_delta, contrast_changed, subject_prominence)
        visual_feeling = AnalyzeService.generate_visual_feeling(sat_delta, light_delta, contrast_level)
        suitable_scenario = AnalyzeService.generate_suitable_scenario(sat_delta, light_delta, contrast_level)
        risk = AnalyzeService.generate_risk(adjusted_avg_s, contrast_level, light_diff, relation)
        next_step = AnalyzeService.generate_next_step(sat_delta, light_delta, relation, contrast_level)

        major_change_text = "、".join(
            f"{item['id']}（色相{item['hue_change']:+d}°、饱和度{item['saturation_change']:+d}、明度{item['lightness_change']:+d}）"
            for item in (major_changes[:2] or changes[:1])
        )

        summary = f"本次调整以{sat_trend}饱和度和{light_trend}明度为主，主色关系呈现{relation}，画面对比为{contrast_level}。"
        ai_explanation = AnalyzeService.generate_ai_explanation(
            major_change_text, sat_trend, light_trend, relation, contrast_level, visual_feeling, suitable_scenario, risk
        )

        return {
            "status": "success",
            "message": "Rule-based comparative analysis generated",
            "tags": tags,
            "color_relation": color_relation,
            "visual_feeling": visual_feeling,
            "suitable_scenario": suitable_scenario,
            "summary": summary,
            "ai_explanation": ai_explanation,
            "risk": risk,
            "next_step": next_step,
        }
