from __future__ import annotations

import base64
import json
import logging
import mimetypes
import os
from pathlib import Path
from typing import Any


logger = logging.getLogger(__name__)


def image_to_data_url(image_path: str) -> str:
    path = Path(image_path)
    if not path.exists():
        raise FileNotFoundError(f"image not found: {image_path}")

    mime_type, _ = mimetypes.guess_type(path.name)
    mime_type = mime_type or "image/png"
    encoded = base64.b64encode(path.read_bytes()).decode("utf-8")
    return f"data:{mime_type};base64,{encoded}"


def analyze_color_with_qwen(
    image_path: str,
    color_regions: list[dict[str, Any]],
    hsl_change: dict[str, Any],
    rule_analysis: dict[str, Any],
) -> str:
    api_key = os.getenv("DASHSCOPE_API_KEY")
    if not api_key:
        raise RuntimeError("DASHSCOPE_API_KEY is not configured")

    image_data_url = image_to_data_url(image_path)
    prompt = (
        "你是一个中文色彩设计教学助手。请基于图片和结构化数据，生成面向设计学生的色彩分析。\n"
        "重点分析：\n"
        "- 主色与辅助色关系\n"
        "- 色相、饱和度、明度变化\n"
        "- 画面视觉层级\n"
        "- 调色后主体是否更突出\n"
        "- 画面情绪变化\n"
        "- 给设计学习者的一句简短建议\n\n"
        "不要泛泛描述图片内容，要围绕色彩关系分析。\n"
        "不要编造用户没有提供的信息。\n"
        "语言要清楚、具体、中文，像设计课老师在讲解。\n\n"
        f"结构化数据如下：\n{json.dumps({'color_regions': color_regions, 'hsl_change': hsl_change, 'rule_analysis': rule_analysis}, ensure_ascii=False)}"
    )

    from openai import OpenAI

    client = OpenAI(api_key=api_key, base_url="https://dashscope.aliyuncs.com/compatible-mode/v1")
    completion = client.chat.completions.create(
        model="qwen3.5-flash",
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": image_data_url}},
                ],
            }
        ],
        extra_body={"enable_thinking": False},
    )
    content = completion.choices[0].message.content
    if not content:
        raise RuntimeError("qwen returned empty content")
    logger.info("Qwen analysis generated successfully")
    return content.strip()
