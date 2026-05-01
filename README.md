# Color Agent Plugins

这是「色彩构成实验 Agent」的插件 API 服务。

## 接口概览

- `GET /health`：服务健康检查
- `POST /segment`：基于颜色聚类识别图片主要色彩区域（真实实现，MVP 近似）
- `POST /recolor`：基于 mask 的局部 HSL 调色并输出真实 preview image（MVP 近似）
- `POST /analyze`：基于调整前后色彩区域数据进行规则化“前后对比分析”（不调用真实大模型）

## 安装依赖

```bash
pip install -r requirements.txt
```

## 启动服务

```bash
uvicorn app.main:app --reload
```

## 访问 API 文档

- Swagger UI: `http://127.0.0.1:8000/docs`
- ReDoc: `http://127.0.0.1:8000/redoc`

## /segment + /recolor 完整调色流程

1. 调用 `/segment` 上传图片（本地路径或 URL）并获取：
   - `image_id`
   - `color_regions[].id`
   - `mask_url` / `soft_mask_url`
2. 服务会落盘 `static/outputs/{image_id}/segment_result.json`，记录原图、标注图、每个区域的 mask 路径映射。
3. 调用 `/recolor`，传入：
   - `image_id`
   - `original_image_url`
   - `target_region_id`
   - `original_hsl`
   - `new_hsl`
4. `/recolor` 读取 `segment_result.json` 与目标 `soft_mask_path`，对目标区域做相对 HSL 调整并进行软 mask 羽化混合。
5. 输出真实预览图：`static/outputs/{image_id}/recolor_{target_region_id}_{hash}.png`，返回 `preview_image_url`。

## /recolor 调色算法说明（当前版本）

- 当前实现是面向学习与快速实验的 MVP 近似效果，不是 Photoshop 级精修换色。
- 算法不是纯色覆盖，而是相对 HSL 调整：
  - `delta_h = new_hsl.h - original_hsl.h`
  - `delta_s = new_hsl.s - original_hsl.s`
  - `delta_l = new_hsl.l - original_hsl.l`
- 在 mask 区域内每个像素执行：
  - `hue = (hue + delta_h) mod 360`
  - `saturation = clamp(saturation + delta_s, 0, 100)`
  - `lightness = clamp(lightness + delta_l, 0, 100)`
- 使用 soft mask 按权重混合（值越高影响越强），尽量保留原图纹理和明暗关系。

## 错误处理（/recolor）

- 未找到 `segment_result.json`：`未找到对应的图片识别结果，请先调用 /segment。`
- 找不到 `target_region_id`：`未找到对应的色彩区域。`
- 找不到 mask 文件：`目标区域 mask 文件不存在，无法进行局部调色。`
- 当 `original_image_url` 无法读取时，会优先回退到 `segment_result.json` 中的 `original_image_path`。

## 下一步迭代建议

- 强化 `/analyze`：结合调整前后图片与色彩统计差异，生成更准确的构成分析与建议。
- 增加区域边缘保护、亮部/暗部约束与色相保护策略，提升复杂图像下的调色稳定性。

## 测试

```bash
pytest -q
```


## /analyze 升级说明（规则引擎版）

当前 `/analyze` 已升级为基于结构化色彩数据的前后对比分析：

1. 对齐 `original_color_regions` 与 `adjusted_color_regions` 的同 ID 区域，计算色相/饱和度/明度变化。
2. 自动识别主要调整区域，并结合面积占比判断整体趋势（饱和度、明度、对比、主体突出度）。
3. 取占比最高的两个区域作为主色对，按色相夹角判断同类色/邻近色/中差色/对比色/近互补关系。
4. 结合主色对的饱和度差与明度差，判定低对比~高对比强度。
5. 输出标签、视觉感受、适用场景、风险提示和下一步建议，并生成面向设计学习者的中文解释。

> 说明：当前版本不会调用真实大模型，`ai_explanation` 由规则 + 模板生成，用于稳定教学反馈。

## 推荐工作流（/segment → /recolor → /analyze）

1. `/segment` 获取主色区域、占比、HSL 与 mask。
2. `/recolor` 基于目标区域 soft mask 做局部 HSL 调整，得到预览图。
3. `/analyze` 对比调整前后色彩构成，输出结构化分析与学习建议。

## 下一步可迭代方向

- 在保留结构化规则结果的基础上，将 `/analyze` 接入真实大模型，让解释语言更自然。
- 引入更多版式与任务上下文（如海报/包装/导视）以提升建议的场景针对性。
