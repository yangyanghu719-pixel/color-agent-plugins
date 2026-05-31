from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from pydantic import ValidationError

from app.schemas.composition_param_models import CompositionParamDocument, SUPPORTED_TYPES
from app.services.qwen_client import image_to_data_url

DEFAULT_QWEN_BASE_URL = "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"
DEFAULT_QWEN_MODEL = "qwen-vl-max"


class QwenConfigurationError(RuntimeError):
    """Raised when Qwen environment configuration is incomplete."""


class QwenRequestError(RuntimeError):
    """Raised when the Qwen API request fails or produces no content."""


def format_validation_errors(exc: ValidationError) -> list[dict[str, str]]:
    errors = []
    for error in exc.errors():
        parts: list[str] = []
        for part in error.get("loc", []):
            if isinstance(part, int) and parts:
                parts[-1] = f"{parts[-1]}[{part}]"
            else:
                parts.append(str(part))
        errors.append({"path": ".".join(parts), "message": error.get("msg", "invalid")})
    return errors


def build_generation_prompt(user_hint: str | None = None) -> str:
    supported = ", ".join(sorted(SUPPORTED_TYPES))
    schema = json.dumps(CompositionParamDocument.model_json_schema(), ensure_ascii=False)
    hint = user_hint.strip() if user_hint and user_hint.strip() else "无额外提示"
    return f"""你是一个“构成图像参数化转译助手”。你的唯一任务是把用户上传的白底抽象构成参考图转译为可编辑的 CompositionParamDocument JSON 草案，而不是精确像素复制。

严格规则：
1. 只能使用以下图元 type：{supported}。
2. 优先用少量较大的结构概括，不要碎片化。大结构优先，小装饰其次。
3. 默认目标元素数量为 6~20 个。即使图像复杂，也绝对不要超过 24 个 elements。不要输出几十上百个小元素。
4. 所有位置、尺寸、半径、线宽使用 normalized coordinate，数值范围为 0~1；canvas 建议使用 1000x1000。
5. 顶层必须包含 version、canvas、source_summary、elements。
6. source_summary 至少包含 input_type、abstract_style、visual_center、balance、density。
7. 输出必须是严格合法 JSON，且符合下方 CompositionParamDocument JSON Schema。
8. 不要输出 Markdown 代码块，不要解释，不要输出任何 JSON 以外的文字。
9. 每个元素需要唯一 id、合法 role、opacity 和 z_index，并满足相应 type 的字段约束。

用户可选提示：{hint}

CompositionParamDocument JSON Schema：
{schema}
"""


class QwenParamClient:
    def generate(self, image_path: str | Path, user_hint: str | None = None) -> str:
        api_key = os.getenv("QWEN_API_KEY")
        if not api_key:
            raise QwenConfigurationError("未配置环境变量 QWEN_API_KEY，无法调用 Qwen 视觉模型")
        base_url = os.getenv("QWEN_BASE_URL", DEFAULT_QWEN_BASE_URL)
        model = os.getenv("QWEN_MODEL", DEFAULT_QWEN_MODEL)
        from openai import OpenAI

        client = OpenAI(api_key=api_key, base_url=base_url)
        try:
            completion = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": build_generation_prompt(user_hint)},
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": "请将这张白底抽象构成参考图转译为可编辑的参数 JSON 草案。只输出 JSON。"},
                            {"type": "image_url", "image_url": {"url": image_to_data_url(str(image_path))}},
                        ],
                    },
                ],
                extra_body={"enable_thinking": False},
            )
        except Exception as exc:
            raise QwenRequestError(f"Qwen API 调用失败: {exc}") from exc
        content = completion.choices[0].message.content
        if not content:
            raise QwenRequestError("Qwen API 返回了空内容")
        return content.strip()


qwen_client = QwenParamClient()


@dataclass
class GenerationResult:
    status: str
    message: str
    raw_text: str
    valid: bool
    errors: list[dict[str, str]]
    document: dict | None

    def as_dict(self) -> dict:
        return {
            "status": self.status,
            "message": self.message,
            "raw_text": self.raw_text,
            "valid": self.valid,
            "errors": self.errors,
            "document": self.document,
        }


class CompositionParamGenerationService:
    def __init__(self, generate_text: Callable[[str | Path, str | None], str] | None = None) -> None:
        self.generate_text = generate_text or qwen_client.generate

    def generate(self, image_path: str | Path, user_hint: str | None = None) -> GenerationResult:
        raw_text = self.generate_text(image_path, user_hint)
        try:
            payload = json.loads(raw_text)
        except json.JSONDecodeError as exc:
            return GenerationResult("error", "Qwen 返回内容不是合法 JSON", raw_text, False, [{"path": "", "message": f"JSON parse error: {exc.msg} at line {exc.lineno} column {exc.colno}"}], None)
        if not isinstance(payload, dict):
            return GenerationResult("error", "Qwen 返回 JSON 顶层必须是对象", raw_text, False, [{"path": "", "message": "document must be a JSON object"}], None)
        try:
            document = CompositionParamDocument.model_validate(payload)
        except ValidationError as exc:
            return GenerationResult("error", "Qwen 返回 JSON 未通过 CompositionParamDocument schema 校验", raw_text, False, format_validation_errors(exc), None)
        return GenerationResult("success", "参数 JSON 草案生成成功", raw_text, True, [], document.model_dump())
