from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass
from typing import Any

import requests

DASHSCOPE_APP_BASE_URL = "https://dashscope.aliyuncs.com/api/v1/apps"
DASHSCOPE_COMPATIBLE_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
VISION_ANALYSIS_MODEL = "qwen3.6-plus"
TEXT_MODE = "snapshot_latest_text"
PREVIEW_CHARS = 1200
RECENT_PREVIEW_COUNT = 20


def default_upstream_debug(message: str | None = None) -> dict[str, Any]:
    return {
        "chunk_count": 0,
        "raw_line_count": 0,
        "first_chunk_ms": None,
        "total_elapsed_ms": None,
        "request_id": None,
        "finish_reason": None,
        "error_message": message,
    }


def strip_markdown_code_fence(text: str) -> str:
    stripped = text.strip()
    match = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", stripped, flags=re.IGNORECASE | re.DOTALL)
    if match:
        return match.group(1).strip()
    if stripped.lower().startswith("```json"):
        stripped = stripped[7:].strip()
    elif stripped.startswith("```"):
        stripped = stripped[3:].strip()
    if stripped.endswith("```"):
        stripped = stripped[:-3].strip()
    return stripped


@dataclass
class AliyunAppResult:
    ok: bool
    error: str
    message: str
    public_image_url: str
    upstream_status: int | None
    sse_event_count: int
    text_mode: str
    final_text: str
    final_text_length: int
    raw_text_preview: str
    textarea_json: str
    parsed_json: Any | None
    recent_data_previews: list[str]
    request_debug: dict[str, Any]
    upstream_debug: dict[str, Any]
    raw_sse_data_lines: list[str]
    parsed_events: list[dict[str, Any]]
    text_fragments: list[str]
    full_raw_preview: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "error": self.error,
            "message": self.message,
            "public_image_url": self.public_image_url,
            "upstream_status": self.upstream_status,
            "sse_event_count": self.sse_event_count,
            "text_mode": self.text_mode,
            "final_text": self.final_text,
            "final_text_length": self.final_text_length,
            "raw_text_preview": self.raw_text_preview,
            "textarea_json": self.textarea_json,
            "parsed_json": self.parsed_json,
            "recent_data_previews": self.recent_data_previews,
            "request_debug": self.request_debug,
            "upstream_debug": self.upstream_debug,
            # Backwards-compatible debug fields used only by this isolated test page/tests.
            "raw_sse_data_lines": self.raw_sse_data_lines,
            "parsed_events": self.parsed_events,
            "text_fragments": self.text_fragments,
            "full_raw_preview": self.full_raw_preview,
        }


@dataclass
class AliyunVisionAnalysisResult:
    ok: bool
    message: str
    analysis: str
    image_a_url: str
    image_b_url: str
    upstream_status: int | None
    request_debug: dict[str, Any]
    upstream_debug: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "message": self.message,
            "analysis": self.analysis,
            "image_a_url": self.image_a_url,
            "image_b_url": self.image_b_url,
            "upstream_status": self.upstream_status,
            "request_debug": self.request_debug,
            "upstream_debug": self.upstream_debug,
        }


class AliyunAppClient:
    """Minimal DashScope App client for /aliyun-app-chat-test only."""

    def _env(self, key: str) -> str:
        return os.getenv(key, "").strip()

    def build_payload(self, prompt: str, public_image_url: str) -> dict[str, Any]:
        return {
            "input": {
                "prompt": prompt,
                "image_list": [public_image_url],
            },
            "parameters": {},
        }

    def build_request_debug(
        self,
        endpoint_url: str,
        prompt: str,
        public_image_url: str,
        *,
        filename: str = "",
        local_saved_path: str = "",
    ) -> dict[str, Any]:
        return {
            "filename": filename,
            "local_saved_path": local_saved_path,
            "public_image_url": public_image_url,
            "prompt": prompt,
            "aliyun_application_id_present": bool(self._env("ALIYUN_APPLICATION_ID")),
            "aliyun_api_key_present": bool(self._env("ALIYUN_API_KEY")),
            "request_url": endpoint_url,
            "request_body_preview": self.build_payload(prompt, public_image_url),
            # Legacy names retained for old debug consumers.
            "endpoint_url": endpoint_url,
            "app_id_present": bool(self._env("ALIYUN_APPLICATION_ID")),
            "api_key_present": bool(self._env("ALIYUN_API_KEY")),
            "payload_preview": self.build_payload(prompt, public_image_url),
        }

    def call(
        self,
        public_image_url: str,
        prompt: str | None = None,
        *,
        filename: str = "",
        local_saved_path: str = "",
    ) -> AliyunAppResult:
        prompt_text = (prompt or "").strip() or "go"
        app_id = self._env("ALIYUN_APPLICATION_ID")
        api_key = self._env("ALIYUN_API_KEY")
        endpoint_url = f"{DASHSCOPE_APP_BASE_URL}/{app_id}/completion"
        request_debug = self.build_request_debug(
            endpoint_url,
            prompt_text,
            public_image_url,
            filename=filename,
            local_saved_path=local_saved_path,
        )
        if not app_id or not api_key:
            missing = []
            if not app_id:
                missing.append("ALIYUN_APPLICATION_ID")
            if not api_key:
                missing.append("ALIYUN_API_KEY")
            return self._failure(
                "缺少环境变量: " + ", ".join(missing),
                public_image_url,
                request_debug,
                None,
                "",
                [],
                [],
                [],
                default_upstream_debug("缺少环境变量: " + ", ".join(missing)),
            )

        payload = self.build_payload(prompt_text, public_image_url)
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "X-DashScope-SSE": "enable",
        }
        started = time.monotonic()
        response = None
        raw_lines: list[str] = []
        raw_sse_data_lines: list[str] = []
        parsed_events: list[dict[str, Any]] = []
        text_snapshots: list[str] = []
        recent_data_previews: list[str] = []
        latest_text = ""
        upstream_debug = default_upstream_debug()
        sse_event_count = 0
        try:
            response = requests.post(endpoint_url, headers=headers, json=payload, stream=True, timeout=300)
            upstream_status = getattr(response, "status_code", None)
            headers_obj = getattr(response, "headers", {}) or {}
            upstream_debug["request_id"] = headers_obj.get("X-Request-Id") or headers_obj.get("x-request-id")
            for line in response.iter_lines(decode_unicode=True):
                if isinstance(line, bytes):
                    line = line.decode("utf-8", errors="replace")
                line = line or ""
                raw_lines.append(line)
                upstream_debug["raw_line_count"] += 1
                stripped = line.strip()
                if not stripped or stripped.startswith("event:"):
                    continue
                if not stripped.startswith("data:"):
                    continue
                data_text = stripped[5:].strip()
                preview = data_text[:PREVIEW_CHARS]
                recent_data_previews.append(preview)
                recent_data_previews = recent_data_previews[-RECENT_PREVIEW_COUNT:]
                if not data_text or "HTTP_STATUS" in data_text:
                    continue
                raw_sse_data_lines.append(data_text)
                sse_event_count += 1
                upstream_debug["chunk_count"] = sse_event_count
                if upstream_debug["first_chunk_ms"] is None:
                    upstream_debug["first_chunk_ms"] = round((time.monotonic() - started) * 1000)
                try:
                    event = json.loads(data_text)
                except json.JSONDecodeError:
                    parsed_events.append({"_parse_error": True, "raw_data_preview": preview})
                    continue
                parsed_events.append(event)
                self._capture_debug_fields(event, upstream_debug)
                text = self._extract_text(event)
                if text:
                    text_snapshots.append(text)
                    latest_text = text
            upstream_debug["total_elapsed_ms"] = round((time.monotonic() - started) * 1000)
            final_text = latest_text
            status_ok = bool(upstream_status and 200 <= upstream_status < 300)
            if not status_ok:
                error = "阿里云调用返回非 2xx 状态"
                if upstream_debug["error_message"] is None:
                    upstream_debug["error_message"] = error
                return self._failure(
                    error,
                    public_image_url,
                    request_debug,
                    upstream_status,
                    final_text,
                    recent_data_previews,
                    raw_sse_data_lines,
                    parsed_events,
                    upstream_debug,
                    text_snapshots,
                    raw_lines,
                    sse_event_count,
                )
            cleaned_text = strip_markdown_code_fence(final_text)
            try:
                parsed_json = json.loads(cleaned_text)
            except json.JSONDecodeError as exc:
                return self._failure(
                    f"JSON 解析失败: {exc}",
                    public_image_url,
                    request_debug,
                    upstream_status,
                    final_text,
                    recent_data_previews,
                    raw_sse_data_lines,
                    parsed_events,
                    upstream_debug,
                    text_snapshots,
                    raw_lines,
                    sse_event_count,
                )
            textarea_json = json.dumps(parsed_json, ensure_ascii=False, indent=2)
            return AliyunAppResult(
                ok=True,
                error="",
                message="调用完成",
                public_image_url=public_image_url,
                upstream_status=upstream_status,
                sse_event_count=sse_event_count,
                text_mode=TEXT_MODE,
                final_text=final_text,
                final_text_length=len(final_text),
                raw_text_preview=final_text[:PREVIEW_CHARS],
                textarea_json=textarea_json,
                parsed_json=parsed_json,
                recent_data_previews=recent_data_previews,
                request_debug=request_debug,
                upstream_debug=upstream_debug,
                raw_sse_data_lines=raw_sse_data_lines,
                parsed_events=parsed_events,
                text_fragments=text_snapshots,
                full_raw_preview="\n".join(raw_lines)[:10000],
            )
        except requests.RequestException as exc:
            upstream_debug["total_elapsed_ms"] = round((time.monotonic() - started) * 1000)
            upstream_debug["error_message"] = str(exc)
            return self._failure(
                "调用阿里云失败",
                public_image_url,
                request_debug,
                getattr(response, "status_code", None),
                latest_text,
                recent_data_previews,
                raw_sse_data_lines,
                parsed_events,
                upstream_debug,
                text_snapshots,
                raw_lines,
                sse_event_count,
            )

    def _failure(
        self,
        error: str,
        public_image_url: str,
        request_debug: dict[str, Any],
        upstream_status: int | None,
        final_text: str,
        recent_data_previews: list[str],
        raw_sse_data_lines: list[str],
        parsed_events: list[dict[str, Any]],
        upstream_debug: dict[str, Any],
        text_fragments: list[str] | None = None,
        raw_lines: list[str] | None = None,
        sse_event_count: int | None = None,
    ) -> AliyunAppResult:
        return AliyunAppResult(
            ok=False,
            error=error,
            message=error,
            public_image_url=public_image_url,
            upstream_status=upstream_status,
            sse_event_count=len(raw_sse_data_lines) if sse_event_count is None else sse_event_count,
            text_mode=TEXT_MODE,
            final_text=final_text,
            final_text_length=len(final_text),
            raw_text_preview=final_text[:PREVIEW_CHARS],
            textarea_json="",
            parsed_json=None,
            recent_data_previews=recent_data_previews[-RECENT_PREVIEW_COUNT:],
            request_debug=request_debug,
            upstream_debug=upstream_debug,
            raw_sse_data_lines=raw_sse_data_lines,
            parsed_events=parsed_events,
            text_fragments=text_fragments or [],
            full_raw_preview="\n".join(raw_lines or [])[:10000],
        )


    def build_vision_analysis_prompt(self) -> str:
        return (
            "你是一位面向图像构成课学生的专业指导老师。请比较接下来两张图：第一张为图A，第二张为图B。"
            "重点从构图而不是题材内容本身出发分析差异，并用适合课堂反馈的中文 Markdown 输出。"
            "请使用 Markdown 标题、列表和加粗重点，结构包含：\n"
            "## 整体构图差异：画面重心、主体位置、正负形、疏密与留白；\n"
            "## 视觉动线与节奏：线条/形状/色块如何引导视线，节奏是否稳定或有变化；\n"
            "## 层次与平衡：前后关系、大小比例、对称/不对称、稳定感或张力；\n"
            "## A/B 各自的优势与可能问题；\n"
            "## 可操作修改建议：至少 3 条，并说明如果想表达更稳定、更有张力或更聚焦，应该优先调整什么。"
            "请避免泛泛而谈，尽量指向画面中的具体位置和构图关系。"
        )

    def build_vision_analysis_payload(self, image_a_url: str, image_b_url: str) -> dict[str, Any]:
        return {
            "model": VISION_ANALYSIS_MODEL,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": image_a_url}},
                        {"type": "image_url", "image_url": {"url": image_b_url}},
                        {"type": "text", "text": self.build_vision_analysis_prompt()},
                    ],
                }
            ],
            "enable_thinking": False,
        }

    def analyze_composition_ab(self, image_a_url: str, image_b_url: str) -> AliyunVisionAnalysisResult:
        api_key = self._env("ALIYUN_API_KEY")
        endpoint_url = f"{DASHSCOPE_COMPATIBLE_BASE_URL}/chat/completions"
        payload = self.build_vision_analysis_payload(image_a_url, image_b_url)
        request_debug = {
            "request_url": endpoint_url,
            "model": VISION_ANALYSIS_MODEL,
            "aliyun_api_key_present": bool(api_key),
            "image_a_url": image_a_url,
            "image_b_url": image_b_url,
            "request_body_preview": payload,
        }
        upstream_debug = default_upstream_debug()
        if not api_key:
            upstream_debug["error_message"] = "缺少环境变量: ALIYUN_API_KEY"
            return AliyunVisionAnalysisResult(False, upstream_debug["error_message"], "", image_a_url, image_b_url, None, request_debug, upstream_debug)

        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        started = time.monotonic()
        try:
            response = requests.post(endpoint_url, headers=headers, json=payload, timeout=300)
            upstream_debug["total_elapsed_ms"] = round((time.monotonic() - started) * 1000)
            upstream_debug["request_id"] = response.headers.get("X-Request-Id") or response.headers.get("x-request-id")
            upstream_status = response.status_code
            try:
                data = response.json()
            except ValueError:
                upstream_debug["error_message"] = response.text[:PREVIEW_CHARS]
                return AliyunVisionAnalysisResult(False, "阿里云视觉模型返回了无法解析的响应", "", image_a_url, image_b_url, upstream_status, request_debug, upstream_debug)
            if not 200 <= upstream_status < 300:
                upstream_debug["error_message"] = str(data.get("message") or data.get("error") or "阿里云视觉模型返回非 2xx 状态")
                return AliyunVisionAnalysisResult(False, upstream_debug["error_message"], "", image_a_url, image_b_url, upstream_status, request_debug, upstream_debug)
            analysis = self._extract_chat_completion_content(data)
            if not analysis:
                upstream_debug["error_message"] = "阿里云视觉模型响应中没有可显示的文本内容"
                return AliyunVisionAnalysisResult(False, upstream_debug["error_message"], "", image_a_url, image_b_url, upstream_status, request_debug, upstream_debug)
            return AliyunVisionAnalysisResult(True, "分析完成", analysis, image_a_url, image_b_url, upstream_status, request_debug, upstream_debug)
        except requests.RequestException as exc:
            upstream_debug["total_elapsed_ms"] = round((time.monotonic() - started) * 1000)
            upstream_debug["error_message"] = str(exc)
            return AliyunVisionAnalysisResult(False, "调用阿里云视觉模型失败", "", image_a_url, image_b_url, None, request_debug, upstream_debug)

    def _extract_chat_completion_content(self, data: dict[str, Any]) -> str:
        choices = data.get("choices")
        if not isinstance(choices, list) or not choices:
            return ""
        message = choices[0].get("message") if isinstance(choices[0], dict) else None
        if not isinstance(message, dict):
            return ""
        content = message.get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts = []
            for item in content:
                if isinstance(item, dict):
                    text = item.get("text")
                    if isinstance(text, str):
                        parts.append(text)
                elif isinstance(item, str):
                    parts.append(item)
            return "".join(parts).strip()
        return ""

    def _capture_debug_fields(self, event: dict[str, Any], upstream_debug: dict[str, Any]) -> None:
        request_id = event.get("request_id") or event.get("requestId")
        if request_id and not upstream_debug.get("request_id"):
            upstream_debug["request_id"] = request_id
        output = event.get("output") if isinstance(event.get("output"), dict) else {}
        finish_reason = output.get("finish_reason") or event.get("finish_reason")
        if finish_reason:
            upstream_debug["finish_reason"] = finish_reason
        message = event.get("message") or event.get("error_message") or event.get("error")
        if message:
            upstream_debug["error_message"] = str(message)

    def _extract_text(self, event: dict[str, Any]) -> str:
        output = event.get("output")
        if isinstance(output, dict):
            text = output.get("text")
            if isinstance(text, str):
                return text
            message = output.get("message")
            if isinstance(message, dict):
                content = message.get("content")
                if isinstance(content, str):
                    return content
        text = event.get("text")
        if isinstance(text, str):
            return text
        return ""


# Backwards-compatible name for existing imports; this is the single Aliyun App client.
AliyunAppChatTestService = AliyunAppClient
