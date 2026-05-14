# Web App 重构基线

## 目标
将项目定位收敛为独立运行的 Color Agent Web App，不再面向第三方平台导入。

## 已完成基线
- 统一 FastAPI + `/experiment` 的教学实验流程。
- 保留 `/health`、`/segment`、`/recolor`、`/analyze` 核心 API。
- 清理平台接入叙事与相关文档。

## 后续方向
- 新增 `/vision-analyze` 作为视觉模型分析入口。
- 分析结果卡片化和可视化。
- 教学导向的交互与作品展示优化。
