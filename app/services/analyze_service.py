from __future__ import annotations

from app.schemas.request_models import AnalyzeRequest


class AnalyzeService:
    @staticmethod
    def analyze(payload: AnalyzeRequest) -> dict:
        original_avg_s = sum(item.hsl.s for item in payload.original_color_regions) / len(payload.original_color_regions)
        adjusted_avg_s = sum(item.hsl.s for item in payload.adjusted_color_regions) / len(payload.adjusted_color_regions)
        original_avg_l = sum(item.hsl.l for item in payload.original_color_regions) / len(payload.original_color_regions)
        adjusted_avg_l = sum(item.hsl.l for item in payload.adjusted_color_regions) / len(payload.adjusted_color_regions)

        sat_trend = "提高" if adjusted_avg_s > original_avg_s else "降低" if adjusted_avg_s < original_avg_s else "基本不变"
        light_trend = "提高" if adjusted_avg_l > original_avg_l else "降低" if adjusted_avg_l < original_avg_l else "基本不变"

        tags = ["色彩对比"]
        tags.append("高饱和强化" if sat_trend == "提高" else "低饱和克制" if sat_trend == "降低" else "饱和度稳定")
        tags.append("明亮通透" if light_trend == "提高" else "低调沉稳" if light_trend == "降低" else "明度平衡")
        if payload.user_goal:
            tags.append("目标导向调整")

        explanation = (
            f"整体饱和度由 {original_avg_s:.1f} 变为 {adjusted_avg_s:.1f}（{sat_trend}），"
            f"明度由 {original_avg_l:.1f} 变为 {adjusted_avg_l:.1f}（{light_trend}）。"
            "这会直接影响视觉刺激强度与空间层次：饱和度上升通常更有冲击力，"
            "而明度下降会带来更稳重的情绪。"
        )

        return {
            "status": "success",
            "message": "Rule-based analysis generated",
            "tags": tags[:4],
            "color_relation": "当前配色保留冷暖对比，主辅关系清晰。",
            "visual_feeling": f"整体观感在{sat_trend}饱和度与{light_trend}明度后呈现新的情绪倾向。",
            "suitable_scenario": "适合用于设计学习中的配色推演、海报风格练习与情绪板对比。",
            "summary": f"本次调整核心是饱和度{sat_trend}、明度{light_trend}，建议结合面积比例继续微调。",
            "ai_explanation": explanation,
            "risk": "若高饱和区域面积过大，可能造成视觉疲劳；若明度过低，信息可读性可能下降。",
            "next_step": "建议下一步锁定主色面积不变，仅微调辅助色相 5-15 度，观察对统一感的影响。",
        }
