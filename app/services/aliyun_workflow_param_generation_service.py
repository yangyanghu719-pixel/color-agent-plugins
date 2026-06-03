from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.services.composition_param_generation_service import sanitize_composition_document

JSON_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)


class WorkflowConfigurationError(RuntimeError):
    """Raised when Aliyun workflow environment configuration is incomplete."""


class WorkflowRequestError(RuntimeError):
    """Raised when the Aliyun workflow request fails."""

    def __init__(self, message: str, upstream_status: int | None = None, upstream_body_preview: str = "") -> None:
        super().__init__(message)
        self.upstream_status = upstream_status
        self.upstream_body_preview = upstream_body_preview[:1000]


class WorkflowParseError(RuntimeError):
    """Raised when the Aliyun workflow response cannot be parsed into a document."""

    def __init__(
        self,
        message: str,
        *,
        raw_workflow_response: Any | None = None,
        raw_text: str = "",
        errors: list[dict[str, str]] | None = None,
    ) -> None:
        super().__init__(message)
        self.raw_workflow_response = raw_workflow_response
        self.raw_text = raw_text
        self.errors = errors or [{"path": "", "message": message}]


@dataclass
class WorkflowGenerationResult:
    message: str
    image_url: str
    raw_workflow_response: Any
    raw_text: str
    document: dict[str, Any]
    textarea_json: str
    warnings: list[str]
    dropped_elements: list[dict[str, Any]]
    strict_validation: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": True,
            "valid": True,
            "message": self.message,
            "image_url": self.image_url,
            "raw_workflow_response": self.raw_workflow_response,
            "raw_text": self.raw_text,
            "document": self.document,
            "textarea_json": self.textarea_json,
            "warnings": self.warnings,
            "dropped_elements": self.dropped_elements,
            "strict_validation": self.strict_validation,
        }


class AliyunWorkflowParamGenerationService:
    def _required_env(self, name: str) -> str:
        value = os.getenv(name, "").strip()
        if not value:
            raise WorkflowConfigurationError(f"未配置环境变量 {name}")
        return value

    def public_image_url(self, public_base_url: str, saved_relative_path: str) -> str:
        base = public_base_url.strip().rstrip("/")
        if not base:
            raise WorkflowConfigurationError("PUBLIC_BASE_URL 为空，无法生成公网图片 URL")
        if not (base.startswith("http://") or base.startswith("https://")):
            raise WorkflowConfigurationError("PUBLIC_BASE_URL 必须以 http:// 或 https:// 开头")
        return f"{base}/{saved_relative_path.lstrip('/')}"

    def call_workflow(self, image_url: str, user_hint: str | None = None) -> Any:
        api_key = self._required_env("ALIYUN_WORKFLOW_API_KEY")
        app_id = self._required_env("ALIYUN_WORKFLOW_APP_ID")
        base_url = self._required_env("ALIYUN_WORKFLOW_BASE_URL").rstrip("/")
        default_prompt = os.getenv("ALIYUN_WORKFLOW_DEFAULT_PROMPT", "请根据图片生成 CompositionParamDocument 参数 JSON。只输出 JSON。")
        prompt = (user_hint or "").strip() or default_prompt
        try:
            timeout = float(os.getenv("ALIYUN_WORKFLOW_TIMEOUT_SECONDS", "60"))
        except ValueError:
            timeout = 60.0
        url = f"{base_url}/{app_id}/completion"
        body = json.dumps({"input": {"prompt": prompt, "image_list": [image_url]}, "parameters": {}}, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=body,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                raw_body = response.read().decode("utf-8", errors="replace")
                status = getattr(response, "status", 200)
        except urllib.error.HTTPError as exc:
            preview = exc.read().decode("utf-8", errors="replace") if exc.fp else str(exc)
            raise WorkflowRequestError("调用阿里云工作流失败", exc.code, preview) from exc
        except Exception as exc:
            raise WorkflowRequestError("调用阿里云工作流失败", None, str(exc)) from exc
        if status < 200 or status >= 300:
            raise WorkflowRequestError("调用阿里云工作流失败", status, raw_body)
        if not raw_body.strip():
            raise WorkflowParseError("阿里云响应为空", raw_text="")
        try:
            return json.loads(raw_body)
        except json.JSONDecodeError as exc:
            raise WorkflowParseError(
                "阿里云响应不是合法 JSON",
                raw_text=raw_body,
                errors=[{"path": "raw_workflow_response", "message": f"JSON parse error: {exc.msg}"}],
            ) from exc

    def generate(self, image_url: str, user_hint: str | None = None) -> WorkflowGenerationResult:
        response_json = self.call_workflow(image_url, user_hint)
        raw_text = extract_workflow_text(response_json)
        sanitized = extract_workflow_document(response_json, raw_text)
        document = sanitized["document"]
        textarea_json = json.dumps(document, ensure_ascii=False, indent=2)
        return WorkflowGenerationResult(
            "生成成功",
            image_url,
            response_json,
            raw_text,
            document,
            textarea_json,
            sanitized.get("warnings", []),
            sanitized.get("dropped_elements", []),
            sanitized.get("strict_validation", {"valid": True, "errors": []}),
        )


def extract_workflow_text(response_json: Any) -> str:
    candidates: list[Any] = []
    if isinstance(response_json, dict):
        output = response_json.get("output")
        if isinstance(output, dict):
            candidates.extend([output.get("text"), output.get("result")])
        candidates.append(output)
        candidates.append(response_json)
    else:
        candidates.append(response_json)
    for candidate in candidates:
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()
        if isinstance(candidate, (dict, list)):
            return json.dumps(candidate, ensure_ascii=False)
    raise WorkflowParseError("阿里云响应为空", raw_workflow_response=response_json)


def strip_markdown_fence(raw_text: str) -> str:
    text = raw_text.strip()
    if text.startswith("```"):
        text = JSON_FENCE_RE.sub("", text).strip()
    return text


def parse_json_from_text(raw_text: str, response_json: Any | None = None) -> Any:
    text = strip_markdown_fence(raw_text)
    try:
        return json.loads(text)
    except json.JSONDecodeError as original_exc:
        decoder = json.JSONDecoder()
        for marker in ("{", "["):
            offset = text.find(marker)
            while offset != -1:
                try:
                    payload, _ = decoder.raw_decode(text[offset:])
                    return payload
                except json.JSONDecodeError:
                    offset = text.find(marker, offset + 1)
        raise WorkflowParseError(
            "返回文本不是合法 JSON",
            raw_workflow_response=response_json,
            raw_text=raw_text,
            errors=[{"path": "raw_text", "message": f"JSON parse error: {original_exc.msg} at line {original_exc.lineno} column {original_exc.colno}"}],
        ) from original_exc


def extract_workflow_document(response_json: Any, raw_text: str | None = None) -> dict[str, Any]:
    parsed = parse_json_from_text(raw_text, response_json) if raw_text is not None else response_json
    candidate = parsed.get("result1") if isinstance(parsed, dict) and "result1" in parsed else parsed
    if not isinstance(candidate, dict):
        raise WorkflowParseError("返回 JSON 中没有 result1 且不是合法 document", raw_workflow_response=response_json, raw_text=raw_text or "")
    sanitized = sanitize_composition_document(candidate)
    if not sanitized.get("valid"):
        raise WorkflowParseError(
            sanitized.get("message") or "返回 JSON 中没有可渲染元素",
            raw_workflow_response=response_json,
            raw_text=raw_text or "",
            errors=sanitized.get("errors") or sanitized.get("strict_validation", {}).get("errors") or [{"path": "elements", "message": "清洗后没有可渲染元素"}],
        )
    return sanitized
