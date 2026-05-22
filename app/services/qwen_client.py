from __future__ import annotations

import base64
import json
import logging
import mimetypes
import os
from pathlib import Path
from typing import Any

from pydantic import BaseModel

logger = logging.getLogger(__name__)


def _json_default(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump()
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def image_to_data_url(image_path: str) -> str:
    path = Path(image_path)
    if not path.exists():
        raise FileNotFoundError(f"image not found: {image_path}")

    mime_type, _ = mimetypes.guess_type(path.name)
    mime_type = mime_type or "image/png"
    encoded = base64.b64encode(path.read_bytes()).decode("utf-8")
    return f"data:{mime_type};base64,{encoded}"


def analyze_composition_with_qwen(
    before_image_path: str,
    after_image_path: str,
    color_regions: list[dict[str, Any]],
    hsl_change: dict[str, Any],
    rule_analysis: dict[str, Any],
) -> str:
    api_key = os.getenv("DASHSCOPE_API_KEY")
    if not api_key:
        raise RuntimeError("DASHSCOPE_API_KEY is not configured")

    before_image_data_url = image_to_data_url(before_image_path)
    after_image_data_url = image_to_data_url(after_image_path)
    prompt = (
        "你是中文‘构图与形式构成’课程助教。请基于两张图片与结构化数据，仅输出简短 Markdown 反馈。\n"
        "严格使用以下结构，不要增加其他标题或前言：\n"
        "### 总体判断\n"
        "用 1-2 句话说明本次调整的构图整体效果。\n\n"
        "### 构图差异\n"
        "- **点线面**：概括两图在点、线、面组织上的差异。\n"
        "- **主体关系**：说明主体与次主体、背景的关系变化。\n"
        "- **视觉重心与均衡**：说明重心偏移、画面均衡与张力变化。\n\n"
        "### 形式节奏\n"
        "分析节奏、层次、方向感与留白的变化。\n\n"
        "### 学习建议\n"
        "给设计学生一句具体可操作建议。\n\n"
        "限制要求：\n"
        "- 总字数不超过 350 字。\n"
        "- 不要输出 JSON。\n"
        "- 不要输出多余前言。\n"
        "- 不要编造图片中没有的信息。\n"
        "- 只围绕点线面、主体关系、视觉重心、画面均衡、节奏、层次、方向感、留白、画面张力分析。\n\n"
        f"结构化数据如下：\n{json.dumps({'color_regions': color_regions, 'adjustment_change': hsl_change, 'rule_analysis': rule_analysis}, ensure_ascii=False, default=_json_default)}"
    )

    from openai import OpenAI

    client = OpenAI(api_key=api_key, base_url="https://dashscope-intl.aliyuncs.com/compatible-mode/v1")
    completion = client.chat.completions.create(
        model="qwen3.5-flash",
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "第一张图片是调整前图片，第二张图片是调整后图片。请从构图与形式构成角度做对比分析。"},
                    {"type": "image_url", "image_url": {"url": before_image_data_url}},
                    {"type": "image_url", "image_url": {"url": after_image_data_url}},
                    {"type": "text", "text": prompt},
                ],
            }
        ],
        extra_body={"enable_thinking": False},
    )
    content = completion.choices[0].message.content
    if not content:
        raise RuntimeError("qwen returned empty content")
    logger.info("Qwen composition analysis generated successfully")
    return content.strip()
