# Color Agent Plugins (MVP)

这是「色彩构成实验 Agent」的插件 API 服务（第一阶段 MVP）。
目标是提供稳定的后端接口结构，支持后续将 mock 能力替换为真实图像算法和模型能力。

## 项目用途

该服务主要提供 4 个接口：

- `GET /health`：服务健康检查
- `POST /segment`：识别图片中主要色彩区域（当前为 mock）
- `POST /recolor`：按 HSL 调整指定区域并返回预览信息（预览图地址为 mock）
- `POST /analyze`：基于调整前后色彩数据进行规则化分析

## 安装依赖

```bash
pip install -r requirements.txt
```

## 启动服务

```bash
uvicorn app.main:app --reload
```

## 访问 API 文档

启动后访问：

- Swagger UI: `http://127.0.0.1:8000/docs`
- ReDoc: `http://127.0.0.1:8000/redoc`

## MVP 说明

当前版本是 **MVP mock 版本**：

- `/segment` 返回结构化 mock 色彩区域数据，保证 schema 稳定。
- `/recolor` 会真实计算 `before_hsl` / `after_hsl` / `change`，但 `preview_image_url` 是占位链接。
- `/analyze` 使用规则和模板生成中文分析，不调用真实大模型。

## 后续迭代方向

下一步将把 `/segment` 从 mock 替换为真实图像主色区域识别算法，计划包括：

1. 图像下载与安全校验（URL 白名单、格式校验、尺寸限制）
2. 颜色聚类（KMeans 或 Median Cut）得到主色
3. 超像素/语义分区生成区域 mask
4. 计算区域面积占比并生成软边界 mask
5. 输出与当前 schema 完全兼容的数据结构，确保前后端无缝升级

## 测试

```bash
pytest -q
```
