# Color Agent Plugins

这是「色彩构成实验 Agent」的插件 API 服务。

## 接口概览

- `GET /health`：服务健康检查
- `POST /segment`：基于颜色聚类识别图片主要色彩区域（真实实现，MVP 近似）
- `POST /recolor`：按 HSL 调整指定区域并返回预览信息（预览图地址仍为 mock）
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

- Swagger UI: `http://127.0.0.1:8000/docs`
- ReDoc: `http://127.0.0.1:8000/redoc`

## /segment 当前能力说明

- 已支持通过 `image_url` 读取图片并进行主色区域识别。
- 支持本地文件路径与远程 URL。
- 算法基于 Pillow + NumPy 的颜色聚类（KMeans 近似），并输出前 `color_count` 个主色区域。
- 会生成：
  - `annotated_image_url`
  - 每个区域的 `mask_url`
  - 每个区域的 `soft_mask_url`（带轻微羽化）
- 如果 `image_url` 为空，仍会走 mock fallback。

> 注意：当前是面向色彩构成学习场景的 **近似区域识别**，不是 Photoshop 级精准选区，也不是语义分割。

## 测试 /segment（curl 示例）

```bash
curl -X POST http://127.0.0.1:8000/segment \
  -H "Content-Type: application/json" \
  -d '{
    "image_url": "./tests/assets/demo.png",
    "color_count": 4
  }'
```

也可以直接在 Swagger (`/docs`) 中提交请求查看返回结构。

## 下一步迭代建议

下一步可继续实现 `/recolor` 的真实区域调色流程：

1. 接收 `image_id` 和 `target_region_id` 对应的 mask。
2. 在 mask 区域内执行 HSL 变换。
3. 输出真实 `preview_image_url` 与调色后区域信息。
4. 保持现有 API schema 不变，实现前端无缝升级。

## 测试

```bash
pytest -q
```
