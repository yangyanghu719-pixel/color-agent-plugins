# Color Agent Plugins

这是「色彩构成实验 Agent」的 FastAPI 插件服务，提供三个核心接口：`/segment`、`/recolor`、`/analyze`。

## 接口概览

- `GET /health`：服务健康检查
- `POST /segment`：识别图片主要色彩区域
- `POST /recolor`：基于区域 mask 做局部 HSL 调色
- `POST /analyze`：分析调色前后色彩构成变化

## 本地运行

### 1) 安装依赖

```bash
pip install -r requirements.txt
```

### 2) 启动服务

```bash
uvicorn app.main:app --reload
```

### 3) 运行测试

```bash
pytest -q
```

## Docker 运行

### 构建镜像

```bash
docker build -t color-agent-plugins .
```

### 运行容器

```bash
docker run -p 8000:8000 color-agent-plugins
```

容器内默认启动命令：

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

## API 完整调用流程

### Step 1: 调用 `POST /segment`

输入：`image_url`

输出：
- `image_id`
- `color_regions`
- `mask_url`
- `annotated_image_url`

示例请求见：`examples/segment_request.json`

### Step 2: 调用 `POST /recolor`

输入：
- `image_id`
- `target_region_id`
- `original_hsl`
- `new_hsl`

输出：
- `preview_image_url`

示例请求见：`examples/recolor_request.json`

### Step 3: 调用 `POST /analyze`

输入：
- `original_color_regions`
- `adjusted_color_regions`
- `before_image_url`
- `after_image_url`
- `user_goal`

输出：
- `tags`
- `color_relation`
- `visual_feeling`
- `summary`
- `ai_explanation`
- `risk`
- `next_step`

示例请求见：`examples/analyze_request.json`

## 最小验收标准（API Smoke Test）

服务启动后：

1. 访问 `GET /health`，应返回正常状态。
2. 打开 `http://127.0.0.1:8000/docs`（Swagger），按顺序测试：
   - `/segment`
   - `/recolor`
   - `/analyze`

## Swagger 文档地址

- Swagger UI: `http://127.0.0.1:8000/docs`
- ReDoc: `http://127.0.0.1:8000/redoc`
