# Color Agent Web App

Color Agent Web App 是一个面向设计学生的图像色彩调整与分析 Web 应用。

## 当前核心流程

1. 上传图片
2. 提取主要色块
3. 选择色块
4. 使用 HSL 调整颜色
5. 生成调整后图片
6. 基于原图与调整后图进行色彩分析
7. 后续接入固定任务型图像分析 Agent

## 当前已有功能

- `GET /health`
- `POST /segment`
- `POST /recolor`
- `POST /analyze`
- `GET /experiment`

## 本地运行

### 1) 安装依赖

```bash
pip install -r requirements.txt
```

### 2) 启动 FastAPI

```bash
uvicorn app.main:app --reload
```

### 3) 打开实验台

访问：`http://127.0.0.1:8000/experiment`

## 测试

```bash
pytest -q
```

## 部署说明

这是一个标准 FastAPI Web App，可直接部署到 Render 或其他 Python Web 服务平台（如 Fly.io、Railway、自托管 Docker/K8s）。

## API 调用概览

- `/segment`：输入图片并生成主色区域、mask 和标注结果。
- `/recolor`：基于选定区域做像素级 HSL 调整，输出新的实验图。
- `/analyze`：输入调色前后区域信息和图片链接，输出结构化分析建议。

## 下一步计划

- 新增 `/vision-analyze`
- 接入视觉大模型
- 将分析结果卡片化展示在前台
- 优化设计学院作品级 UI


## Analyze 接口升级（图像分析主入口）
- `/analyze` 现已升级为图像分析主入口：同时读取 before/after 图片与色块结构数据，调用 OpenAI-compatible 视觉模型生成结构化学习反馈。
- 规则分析仍保留：作为模型提示辅助上下文，并在模型不可用时自动 fallback。
- 关键环境变量：`VISION_MODEL_PROVIDER`（默认 `openai_compatible`）、`VISION_MODEL_API_KEY`、`VISION_MODEL_NAME`、`VISION_MODEL_BASE_URL`。
- 未配置 `VISION_MODEL_API_KEY` 时，接口会自动返回规则分析 fallback 结果（`fallback_used=true`）。


## 中文视觉模型配置（/analyze）

`/analyze` 使用 **OpenAI-compatible** 的 `/chat/completions` 接口接入视觉模型，支持通过环境变量配置：

```bash
VISION_MODEL_PROVIDER=openai_compatible
VISION_MODEL_API_KEY=
VISION_MODEL_BASE_URL=
VISION_MODEL_NAME=
```

说明：
- `VISION_MODEL_PROVIDER` 当前固定为 `openai_compatible`。
- `VISION_MODEL_API_KEY` 未配置时，系统会自动回退到本地规则分析（`fallback_used=true`）。
- `VISION_MODEL_NAME` 与 `VISION_MODEL_BASE_URL` 需要按你所用平台控制台配置。
- 可接入模型示例：Qwen-VL、Qwen3-VL-Flash、Qwen-VL-Plus、豆包视觉模型等（以平台实际可用名称为准）。
- **不要把 API key 写入仓库。**

> 重要：色相/饱和度/明度等色彩数值分析由本地算法完成；视觉模型负责中文教学解释、学习反馈与建议生成。
