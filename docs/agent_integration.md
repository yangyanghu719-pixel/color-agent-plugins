# 智能体插件接入说明

本文档说明如何将 Color Agent Plugins 的三个核心 API 注册为智能体平台可调用工具。

## 工具定义

### 1) segment_image_colors
- **对应接口**：`POST /segment`
- **用途**：识别图片主色区域
- **建议入参**：`image_url`
- **关键出参**：`image_id`、`color_regions`、`mask_url`、`annotated_image_url`

### 2) recolor_image_region
- **对应接口**：`POST /recolor`
- **用途**：基于 mask 调整某个色彩区域
- **建议入参**：`image_id`、`target_region_id`、`original_hsl`、`new_hsl`
- **关键出参**：`preview_image_url`

### 3) analyze_color_comparison
- **对应接口**：`POST /analyze`
- **用途**：分析调整前后色彩构成变化
- **建议入参**：`original_color_regions`、`adjusted_color_regions`、`before_image_url`、`after_image_url`、`user_goal`
- **关键出参**：`tags`、`color_relation`、`visual_feeling`、`summary`、`ai_explanation`、`risk`、`next_step`

## 智能体调用顺序

用户上传图片  
→ 调用 `segment_image_colors`  
→ 用户选择色块并调整 HSL  
→ 调用 `recolor_image_region`  
→ 用户确认分析  
→ 调用 `analyze_color_comparison`

## 接入建议

1. 在智能体平台中将三个工具都注册为 `POST` 类型 HTTP 工具。
2. 工具入参结构保持与 FastAPI Schema 一致，不要在平台层擅自改名或改类型。
3. 把 `image_id` 和 `color_regions` 作为会话上下文缓存，供下一步调色与分析复用。
4. 在智能体提示词中明确工具调用顺序，避免跳过 `segment` 直接调用 `recolor`。
5. 可将 `examples/*.json` 作为工具调用样例，降低集成出错率。


## 基于 OpenAPI 文件接入（推荐）

仓库提供了 `docs/openapi.plugin.yaml`，用于对接 HiAgent / 扣子等智能体平台。

### 1) 先替换部署域名

部署后，先把 `openapi.plugin.yaml` 中的：

- `servers.url: https://YOUR_DEPLOYED_DOMAIN`

替换为真实公网 API 域名（例如 `https://api.example.com`）。

### 2) 导入智能体平台

- 优先直接导入 `docs/openapi.plugin.yaml`。
- 如果平台不支持 YAML 导入，可依据该文件手动创建 3 个 HTTP POST 工具：
  - `segment_image_colors` → `/segment`
  - `recolor_image_region` → `/recolor`
  - `analyze_color_comparison` → `/analyze`

### 3) 工具调用顺序（建议固化在提示词中）

用户上传图片  
→ `segment_image_colors`  
→ 用户选择色块并调整 HSL  
→ `recolor_image_region`  
→ 用户确认分析  
→ `analyze_color_comparison`
