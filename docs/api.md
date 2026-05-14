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

## GET /experiment
教学实验台页面入口。
