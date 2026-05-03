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

## 工程验收

### 本地验收顺序

```bash
pip install -r requirements.txt
pytest -q
uvicorn app.main:app --reload
```

启动后访问：

- `http://127.0.0.1:8000/health`
- `http://127.0.0.1:8000/docs`

也可以运行内置脚本做基础 smoke test：

```bash
python scripts/smoke_test.py
```

### Docker 验收顺序

```bash
docker build -t color-agent-plugins .
docker run -p 8000:8000 color-agent-plugins
```

容器启动后访问：

- `http://127.0.0.1:8000/health`

### CI 说明

仓库已新增 GitHub Actions（`.github/workflows/test.yml`）：

- 在 `push` 和 `pull_request` 时自动运行；
- 使用 `Python 3.11`；
- 自动安装 `requirements.txt` 依赖并执行 `pytest -q`；
- 额外执行一次 `docker build -t color-agent-plugins .` 做镜像构建检查。


## OpenAPI 插件描述文件（智能体平台接入）

仓库已提供 OpenAPI 3.0 描述文件：`docs/openapi.plugin.yaml`。

当前 Render 部署地址为 `https://color-agent-plugins.onrender.com`。

部署到公网后，请先将该文件中的 `servers.url` 从 `https://YOUR_DEPLOYED_DOMAIN` 替换为真实 API 域名；本仓库现已替换为上述 Render 地址。

然后可在 HiAgent / 扣子等平台直接尝试导入该 YAML 文件；若平台暂不支持 YAML 导入，也可按文件中的 schema 手动创建三个工具：

- `segment_image_colors`（`POST /segment`）
- `recolor_image_region`（`POST /recolor`）
- `analyze_color_comparison`（`POST /analyze`）

推荐调用顺序：

用户上传图片  
→ `segment_image_colors`  
→ 用户选择色块并调整 HSL  
→ `recolor_image_region`  
→ 用户确认分析  
→ `analyze_color_comparison`

## 网页实验台（/experiment）

新增“色彩构成实验台”页面：`GET /experiment`。

功能说明：

1. `/experiment` 是学生主动色彩实验页面，聚焦“上传、观察、操作、比较、解释”的学习流程；
2. 只保留本地图片上传入口（`POST /upload-image`，支持 png/jpg/jpeg/webp），不再提供在线图片 URL 输入；
3. 支持识别 4 个主色区域（调用 `POST /segment`）；
4. 页面布局为两段式：上方三栏图像区（上传原图 / 当前选中色块区域 / 调整后整图实时预览）+ 下方双栏操作区（左侧主色区域选择 / 右侧 H/S/L 调色面板）；
5. 色块区域仅支持 click 选中，hover 仅用于卡片轻微样式反馈，不再切换当前选区；
6. 当前选中色块区域采用“原图底图 + 非选区压暗 + 选区强调 + 高对比边界 + 标签”观察模式，不直接展示灰度 mask；
7. 右栏实时预览基于 mask 灰度值（而非 alpha 通道）做软混合，只对选区做 HSL 局部变化，避免整图被误调色；
8. H/S/L 滑杆采用颜色语义渐变，并实时显示原始值 → 当前值与 ΔH/ΔS/ΔL；
9. 点击“记录这次调整”后调用 `POST /recolor`，由后端生成正式预览图；
10. 点击“生成实验反馈”后调用 `POST /analyze`，以学习反馈卡片展示解释；
11. 提供“实验导师”侧边栏 UI 占位，当前版本不接入 HiAgent；
12. 当前仍是 MVP 近似实验：基于颜色聚类与 mask，不是 Photoshop 级精修。

### 本地访问

启动服务后访问：

- `http://127.0.0.1:8000/experiment`

### Render 访问

将域名替换为你的 Render 服务域名：

- `https://<你的-render-域名>/experiment`
