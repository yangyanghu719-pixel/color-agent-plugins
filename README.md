# Composition Lab / 构图测试实验台

Composition Lab / 构图测试实验台 是一个面向设计学生的纯构图实验台 baseline。

## 当前功能

- `GET /health`
- `POST /upload-image`
- `GET /composition`

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
