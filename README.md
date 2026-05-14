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
