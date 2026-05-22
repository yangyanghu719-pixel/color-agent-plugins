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
- `/analyze` 现已升级为图像分析主入口：同时读取 before/after 图片与色块结构数据，调用 Qwen 生成结构化学习反馈。
- 规则分析仍保留：作为模型提示辅助上下文，并在模型不可用时自动 fallback。
- ⚠️ `VISION_MODEL_API_KEY`、`VISION_MODEL_BASE_URL`、`VISION_MODEL_NAME` 仅为历史方案，当前 `/analyze` 不再依赖。

> 色彩数值分析（色相/饱和度/明度等）由本地算法完成；视觉模型主要负责中文教学解释与学习建议。


## 阿里云百炼 Qwen 配置（/analyze）

- 当前 `/analyze` 会先执行规则引擎分析，再尝试用 **qwen3.5-flash** 生成中文教学风格增强说明（`learning_explanation`）。
- Render 当前仅需配置：`DASHSCOPE_API_KEY`。
- 使用的 OpenAI 兼容端点：`https://dashscope-intl.aliyuncs.com/compatible-mode/v1`。
- 说明：该 `base_url` 是 API 地址，不是网页；浏览器直接打开显示 `Not Found` 属于正常现象。
- 若未配置 `DASHSCOPE_API_KEY` 或模型调用失败，接口会自动降级为纯规则分析结果，不影响 `/analyze` 成功返回。

## 色彩与形式构成实验台（升级）
1. 上传作品
2. 上传成功后选择实验方向：色彩实验 / 构图实验
3. 色彩实验：提取主色区域、HSL 调整、生成色彩反馈
4. 构图实验：提取画面元素图层、拖拽缩放旋转镜像、调整图层顺序、生成构图反馈

> 构图实验第一阶段在无外部图层模型时使用 fallback 近似图层拆解（fallback_used=true），后续可接入 Qwen-Image-Layered、SAM、DesignEdit。

## 构图实验技术路线（已修正）

构图实验的目标是：
- 物体级分割（object segmentation）
- RGBA 图层提取（layer extraction）
- 背景自动修补（inpainting）
- 图层重组（canvas editing）
- Qwen-VL 构图分析（composition analysis）

重要说明：
- 色彩实验可使用 KMeans 色彩聚类；构图实验默认**不会**使用 KMeans 伪装物体拆解。
- Render 免费版不直接运行 SAM / diffusion / 大型图层模型。
- 需要通过环境变量配置外部服务：
  - `LAYER_DECOMPOSE_PROVIDER=none|external|sam|manual`
  - `LAYER_DECOMPOSE_API_URL` / `LAYER_DECOMPOSE_API_KEY`
  - `INPAINT_PROVIDER=none|external`
  - `INPAINT_API_URL` / `INPAINT_API_KEY`
- 当 provider 未配置时，`/layers/decompose` 会返回 `needs_model_config`，并明确提示模型未配置；不会再返回颜色碎片图层。
