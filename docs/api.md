# Color Agent Web App API

## GET /health
健康检查。

## POST /segment
输入图片路径或 URL，返回：
- image_id
- processed_image_url
- color_regions[]
- annotated_image_url

## POST /recolor
输入：
- image_id
- region_id（兼容 target_region_id）
- original_image_url
- original_hsl
- new_hsl

输出：
- preview_image_url
- 色相/饱和度/明度变化

## POST /analyze
输入原始与调整后的区域数据和图片 URL，输出结构化色彩分析结果。

> 说明：`/analyze` 是 **rule-based** 对比分析，仅根据请求中的色块结构化数据计算，不执行图像语义理解。

## GET /experiment
教学实验台页面入口。


### POST /analyze（图像分析主入口）
- 输入：`before_image_url`、`after_image_url`、`original_color_regions`、`adjusted_color_regions`、`user_goal`。
- 行为：后端读取前后图片（支持本地路径、`/static/...`、绝对 URL 的本地 path 解析），联合规则分析上下文调用视觉大模型。
- 输出结构：`summary`、`overall_impression`、`hue_analysis`、`saturation_analysis`、`lightness_analysis`、`color_relationship_analysis`、`visual_focus_analysis`、`emotional_expression`、`learning_explanation`、`suggestions`、`rule_based_tags`、`fallback_used`。
- 失败策略：模型调用失败自动 fallback；图片路径无效返回明确错误信息。
