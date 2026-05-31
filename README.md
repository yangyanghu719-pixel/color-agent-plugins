# Composition Lab / 构图测试实验台

Composition Lab / 构图测试实验台 是一个面向设计学生的纯构图实验台 baseline。

## 当前功能

- `GET /health`
- `POST /upload-image`
- `GET /composition`
- `GET /composition-param-test`：参数化编辑器测试页
- `GET /composition-reference-test`：阶段 3A 参考图转参数 JSON 草案测试页
- `POST /composition/generate-param-json`：上传参考图并调用 Qwen 生成参数 JSON 草案

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

访问：`http://127.0.0.1:8000/composition`

## 测试

```bash
pytest -q
```

## 阶段 3A：Qwen 视觉模型配置

参考图转参数 JSON 草案接口使用 OpenAI-compatible Qwen API。启动服务前配置：

```bash
export QWEN_API_KEY="..."
export QWEN_BASE_URL="https://dashscope-intl.aliyuncs.com/compatible-mode/v1"  # 可选
export QWEN_MODEL="qwen-vl-max"  # 可选
```

打开 `http://127.0.0.1:8000/composition-reference-test` 上传白底抽象构成图。该阶段只生成并校验可编辑 JSON 草案，不包含教学分析、正式学生页接入或像素级图像分割。
