from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from typing import Any

import requests

DASHSCOPE_APP_BASE_URL = "https://dashscope.aliyuncs.com/api/v1/apps"


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


@dataclass
class AliyunAppChatTestResult:
    ok: bool
    message: str
    public_image_url: str
    request_debug: dict[str, Any]
    upstream_status: int | None
    final_text: str
    raw_sse_data_lines: list[str]
    parsed_events: list[dict[str, Any]]
    text_fragments: list[str]
    full_raw_preview: str
    upstream_debug: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "message": self.message,
            "public_image_url": self.public_image_url,
            "request_debug": self.request_debug,
            "upstream_status": self.upstream_status,
            "final_text": self.final_text,
            "raw_sse_data_lines": self.raw_sse_data_lines,
            "parsed_events": self.parsed_events,
            "text_fragments": self.text_fragments,
            "full_raw_preview": self.full_raw_preview,
            "upstream_debug": self.upstream_debug,
        }


class AliyunAppChatTestService:
    def _env(self, key: str) -> str:
        return os.getenv(key, "").strip()

    def build_request_debug(self, endpoint_url: str, prompt: str, public_image_url: str) -> dict[str, Any]:
        return {
            "endpoint_url": endpoint_url,
            "app_id_present": bool(self._env("ALIYUN_APPLICATION_ID")),
            "api_key_present": bool(self._env("ALIYUN_API_KEY")),
            "payload_preview": {
                "input": {
                    "prompt": prompt,
                    "image_list": [public_image_url],
                },
                "parameters": {},
            },
        }

    def call(self, public_image_url: str, prompt: str | None = None) -> AliyunAppChatTestResult:
        prompt_text = (prompt or "").strip() or "go"
        app_id = self._env("ALIYUN_APPLICATION_ID")
        api_key = self._env("ALIYUN_API_KEY")
        endpoint_url = f"{DASHSCOPE_APP_BASE_URL}/{app_id}/completion"
        request_debug = self.build_request_debug(endpoint_url, prompt_text, public_image_url)
        if not app_id or not api_key:
            missing = []
            if not app_id:
                missing.append("ALIYUN_APPLICATION_ID")
            if not api_key:
                missing.append("ALIYUN_API_KEY")
            message = "缺少环境变量: " + ", ".join(missing)
            return AliyunAppChatTestResult(
                ok=False,
                message=message,
                public_image_url=public_image_url,
                request_debug=request_debug,
                upstream_status=None,
                final_text="",
                raw_sse_data_lines=[],
                parsed_events=[],
                text_fragments=[],
                full_raw_preview="",
                upstream_debug=default_upstream_debug(message),
            )

        payload = {
            "input": {
                "prompt": prompt_text,
                "image_list": [public_image_url],
            },
            "parameters": {},
        }
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
        text_fragments: list[str] = []
        upstream_debug = default_upstream_debug()
        try:
            response = requests.post(endpoint_url, headers=headers, json=payload, stream=True, timeout=300)
            upstream_status = getattr(response, "status_code", None)
            upstream_debug["request_id"] = getattr(response, "headers", {}).get("X-Request-Id") or getattr(response, "headers", {}).get("x-request-id")
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
                raw_sse_data_lines.append(data_text)
                upstream_debug["chunk_count"] += 1
                if upstream_debug["first_chunk_ms"] is None:
                    upstream_debug["first_chunk_ms"] = round((time.monotonic() - started) * 1000)
                if not data_text:
                    continue
                try:
                    event = json.loads(data_text)
                except json.JSONDecodeError:
                    parsed_events.append({"_parse_error": True, "raw_data": data_text})
                    continue
                parsed_events.append(event)
                self._capture_debug_fields(event, upstream_debug)
                text = self._extract_text(event)
                if text:
                    text_fragments.append(text)
            upstream_debug["total_elapsed_ms"] = round((time.monotonic() - started) * 1000)
            final_text = "".join(text_fragments)
            ok = bool(upstream_status and 200 <= upstream_status < 300)
            message = "调用完成" if ok else "阿里云调用返回非 2xx 状态"
            if not ok and upstream_debug["error_message"] is None:
                upstream_debug["error_message"] = message
            return AliyunAppChatTestResult(
                ok=ok,
                message=message,
                public_image_url=public_image_url,
                request_debug=request_debug,
                upstream_status=upstream_status,
                final_text=final_text,
                raw_sse_data_lines=raw_sse_data_lines,
                parsed_events=parsed_events,
                text_fragments=text_fragments,
                full_raw_preview="\n".join(raw_lines)[:10000],
                upstream_debug=upstream_debug,
            )
        except requests.RequestException as exc:
            upstream_debug["total_elapsed_ms"] = round((time.monotonic() - started) * 1000)
            upstream_debug["error_message"] = str(exc)
            return AliyunAppChatTestResult(
                ok=False,
                message="调用阿里云失败",
                public_image_url=public_image_url,
                request_debug=request_debug,
                upstream_status=getattr(response, "status_code", None),
                final_text="",
                raw_sse_data_lines=raw_sse_data_lines,
                parsed_events=parsed_events,
                text_fragments=text_fragments,
                full_raw_preview="\n".join(raw_lines)[:10000],
                upstream_debug=upstream_debug,
            )

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
        text = event.get("text")
        if isinstance(text, str):
            return text
        return ""
