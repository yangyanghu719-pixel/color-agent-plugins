# Vision Analysis Agent 规划

## 目标
在当前 Web App 基线上增加固定任务型图像分析 Agent，用于教学反馈增强。

## 建议入口
- 新增 `POST /vision-analyze`。
- 由前端在完成 `/recolor` 并确认实验后触发。

## 入参建议
- original_image_url
- adjusted_image_url
- color_regions
- adjustment_history
- user_goal

## 出参建议
- color_relation
- visual_feeling
- composition_feedback
- next_iteration_suggestion
