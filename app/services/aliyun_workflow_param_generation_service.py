from __future__ import annotations

import json
import logging
import os
import re
import time
from pathlib import Path

import httpx
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any

from app.services.composition_param_generation_service import sanitize_composition_document

JSON_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)
logger = logging.getLogger(__name__)


class WorkflowConfigurationError(RuntimeError):
    """Raised when Aliyun application environment configuration is incomplete."""


class WorkflowRequestError(RuntimeError):
    """Raised when the Aliyun application request fails."""

    def __init__(
        self,
        message: str,
        upstream_status: int | None = None,
        upstream_body_preview: str = "",
        *,
        upstream_debug: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.upstream_status = upstream_status
        self.upstream_body_preview = upstream_body_preview[:1000]
        self.upstream_debug = upstream_debug or build_upstream_debug(status_code=upstream_status, error_message=message)


class WorkflowParseError(RuntimeError):
    """Raised when the Aliyun application response cannot be parsed into a document."""

    def __init__(
        self,
        message: str,
        *,
        raw_workflow_response: Any | None = None,
        raw_text: str = "",
        errors: list[dict[str, str]] | None = None,
        upstream_debug: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.raw_workflow_response = raw_workflow_response
        self.raw_text = raw_text
        self.errors = errors or [{"path": "", "message": message}]
        self.upstream_debug = upstream_debug or build_upstream_debug(error_message=message)


@dataclass
class StreamAggregationResult:
    raw_text: str
    raw_events: list[Any] = field(default_factory=list)
    upstream_debug: dict[str, Any] = field(default_factory=dict)


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
    upstream_debug: dict[str, Any]

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
            "upstream_debug": self.upstream_debug,
        }


def build_upstream_debug(
    *,
    request_id: str | None = None,
    status_code: int | None = None,
    chunk_count: int = 0,
    first_chunk_ms: int | None = None,
    total_elapsed_ms: int | None = None,
    finish_reason: str | None = None,
    error_message: str | None = None,
    **extra: Any,
) -> dict[str, Any]:
    debug = {
        "request_id": request_id,
        "status_code": status_code,
        "chunk_count": chunk_count,
        "first_chunk_ms": first_chunk_ms,
        "total_elapsed_ms": total_elapsed_ms,
        "finish_reason": finish_reason,
        "error_message": error_message,
    }
    debug.update(extra)
    return debug


def _env_enabled(value: str, *, default: bool = False) -> bool:
    normalized = value.strip().lower()
    if not normalized:
        return default
    return normalized in {"1", "true", "yes", "on"}


def mask_app_id(app_id: str) -> str:
    if len(app_id) <= 8:
        return "****" if app_id else ""
    return f"{app_id[:4]}...{app_id[-4:]}"


def mask_app_id_in_url(url: str, app_id: str) -> str:
    return url.replace(app_id, mask_app_id(app_id)) if app_id else url


def classify_image_value(value: str) -> str:
    if value.startswith("http://") or value.startswith("https://"):
        return "URL"
    if value.startswith("data:image/"):
        return "base64"
    if value.startswith("file-"):
        return "file_id"
    if value.startswith("session-file-"):
        return "session_file_id"
    if value.startswith("/") or value.startswith("static/") or value.startswith("./") or value.startswith("../"):
        return "local_path"
    return "unknown"


def build_payload_debug(
    *,
    endpoint_url: str,
    app_id: str,
    body_dict: dict[str, Any],
    image_field_name: str,
    image_url: str,
    image_debug: dict[str, Any] | None = None,
    attempt_count: int = 1,
    attempt_mode: str = "stream",
) -> dict[str, Any]:
    input_payload = body_dict.get("input") if isinstance(body_dict.get("input"), dict) else {}
    parameters = body_dict.get("parameters") if isinstance(body_dict.get("parameters"), dict) else {}
    biz_params = input_payload.get("biz_params") if isinstance(input_payload.get("biz_params"), dict) else {}
    prompt = input_payload.get("prompt")
    image_input_debug = {
        "field_name": image_field_name,
        "value_type": classify_image_value(image_url),
        "url_scheme": urllib.parse.urlparse(image_url).scheme,
        "is_absolute_url": image_url.startswith(("http://", "https://")),
    }
    if image_debug:
        image_input_debug.update(image_debug)
    return {
        "endpoint_url": mask_app_id_in_url(endpoint_url, app_id),
        "input_top_level_keys": sorted(input_payload.keys()),
        "parameters_keys": sorted(parameters.keys()),
        "prompt_present": isinstance(prompt, str) and bool(prompt.strip()),
        "prompt_length": len(prompt) if isinstance(prompt, str) else 0,
        "biz_params_present": isinstance(input_payload.get("biz_params"), dict),
        "biz_params_keys": sorted(biz_params.keys()),
        "image_input_field_name": image_field_name,
        "image_url_present": bool(image_url),
        "image_input_debug": image_input_debug,
        "public_image_url": image_input_debug.get("public_image_url") or image_url,
        "image_url_host": image_input_debug.get("image_url_host"),
        "image_url_check_mode": image_input_debug.get("image_url_check_mode"),
        "local_file_exists": image_input_debug.get("local_file_exists"),
        "local_file_size_bytes": image_input_debug.get("local_file_size_bytes"),
        "image_mime_type": image_input_debug.get("image_mime_type"),
        "source_width": image_input_debug.get("source_width"),
        "source_height": image_input_debug.get("source_height"),
        "image_url_reachable": image_input_debug.get("image_url_reachable"),
        "image_url_status": image_input_debug.get("image_url_status"),
        "image_url_error": image_input_debug.get("image_url_error"),
        "image_url_check_warning": image_input_debug.get("image_url_check_warning"),
        "application_call_attempted": image_input_debug.get("application_call_attempted", False),
        "raw_text_length": 0,
        "token_usage": None,
        "sanitized_request_payload": {
            "input": {
                "prompt": "<present>" if isinstance(prompt, str) and prompt else "",
                "biz_params": {key: ("<image-url>" if key in {"imageUrl", "image", "file", "query"} else ["<image-url>"] if key == "imageList" else value) for key, value in biz_params.items()},
            },
            "parameters": parameters,
            "debug": body_dict.get("debug", {}),
        },
        "attempt_count": attempt_count,
        "attempt_mode": attempt_mode,
    }


def merge_debug(base: dict[str, Any], extra: dict[str, Any] | None) -> dict[str, Any]:
    merged = dict(base)
    if extra:
        merged.update(extra)
    return merged


ALLOWED_PUBLIC_IMAGE_MIME_TYPES = {"image/png", "image/jpeg", "image/webp"}
IMAGE_URL_CHECK_KEYS = {
    "public_image_url",
    "image_url_host",
    "image_url_check_mode",
    "local_file_exists",
    "local_file_size_bytes",
    "image_url_reachable",
    "image_url_status",
    "image_url_content_type",
    "image_url_content_length",
    "image_url_error",
    "image_url_check_warning",
}


def _content_length(headers: Any) -> int | None:
    content_length_raw = headers.get("Content-Length") if headers else None
    return int(content_length_raw) if content_length_raw and str(content_length_raw).isdigit() else None


def _content_type(headers: Any) -> str:
    return (headers.get("Content-Type", "") if headers else "").split(";", 1)[0].strip().lower()


def build_local_file_image_url_check(image_url: str, local_file_path: str | Path) -> dict[str, Any]:
    parsed = urllib.parse.urlparse(image_url)
    path = Path(local_file_path)
    exists = path.is_file()
    size = path.stat().st_size if exists else 0
    return {
        "public_image_url": image_url,
        "image_url_host": parsed.netloc,
        "image_url_check_mode": "local_file_check",
        "local_file_exists": exists,
        "local_file_size_bytes": size,
        "image_url_reachable": "skipped_same_host",
        "image_url_status": None,
        "image_url_content_type": None,
        "image_url_content_length": None,
        "image_url_error": None if exists else "local file missing",
        "image_url_check_warning": "图片 URL 本地自检超时，已改用本地文件检查；如果本地文件存在，将继续调用阿里云。",
    }


async def check_public_image_url_async(image_url: str) -> dict[str, Any]:
    parsed = urllib.parse.urlparse(image_url)
    debug = {
        "public_image_url": image_url,
        "image_url_host": parsed.netloc,
        "image_url_check_mode": "async_http_check",
        "local_file_exists": None,
        "local_file_size_bytes": None,
        "image_url_reachable": False,
        "image_url_status": None,
        "image_url_content_type": None,
        "image_url_content_length": None,
        "image_url_error": None,
    }
    if parsed.scheme not in {"http", "https"}:
        debug["image_url_error"] = "image_url is not an absolute HTTP(S) URL"
        return debug

    timeout = httpx.Timeout(connect=10.0, read=30.0, write=10.0, pool=10.0)
    headers = {"User-Agent": "composition-lab-url-check/1.0"}
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            head_error: str | None = None
            try:
                response = await client.head(image_url, headers=headers)
                debug.update({
                    "image_url_status": response.status_code,
                    "image_url_content_type": _content_type(response.headers),
                    "image_url_content_length": _content_length(response.headers),
                })
                if 200 <= response.status_code < 300 and debug["image_url_content_type"] in ALLOWED_PUBLIC_IMAGE_MIME_TYPES and (debug["image_url_content_length"] is None or debug["image_url_content_length"] > 0):
                    debug["image_url_reachable"] = True
                    return debug
                head_error = f"HEAD status={response.status_code} content_type={debug['image_url_content_type']}"
            except Exception as exc:
                head_error = str(exc)

            get_headers = {**headers, "Range": "bytes=0-1023"}
            async with client.stream("GET", image_url, headers=get_headers) as response:
                debug.update({
                    "image_url_status": response.status_code,
                    "image_url_content_type": _content_type(response.headers),
                    "image_url_content_length": _content_length(response.headers),
                })
                sample = b""
                async for chunk in response.aiter_bytes():
                    sample += chunk[:1024 - len(sample)]
                    if sample:
                        break
                debug["image_url_reachable"] = 200 <= response.status_code < 300 and debug["image_url_content_type"] in ALLOWED_PUBLIC_IMAGE_MIME_TYPES and (debug["image_url_content_length"] is None or debug["image_url_content_length"] > 0) and bool(sample)
                if not debug["image_url_reachable"]:
                    debug["image_url_error"] = f"GET check failed after HEAD fallback ({head_error})"
    except Exception as exc:
        debug["image_url_error"] = str(exc)
    return debug


def check_public_image_url(image_url: str, *, timeout: float = 10.0) -> dict[str, Any]:
    """Synchronous fallback for non-request callers; request handlers should await check_public_image_url_async."""
    parsed = urllib.parse.urlparse(image_url)
    debug = {
        "public_image_url": image_url,
        "image_url_host": parsed.netloc,
        "image_url_check_mode": "sync_http_check",
        "local_file_exists": None,
        "local_file_size_bytes": None,
        "image_url_reachable": False,
        "image_url_status": None,
        "image_url_content_type": None,
        "image_url_content_length": None,
        "image_url_error": None,
    }
    if not image_url.startswith(("http://", "https://")):
        debug["image_url_error"] = "image_url is not an absolute HTTP(S) URL"
        return debug
    try:
        with httpx.Client(timeout=httpx.Timeout(connect=10.0, read=30.0, write=10.0, pool=10.0), follow_redirects=True) as client:
            response = client.get(image_url, headers={"Range": "bytes=0-1023", "User-Agent": "composition-lab-url-check/1.0"})
            content_type = _content_type(response.headers)
            content_length = _content_length(response.headers)
            debug.update({
                "image_url_status": response.status_code,
                "image_url_content_type": content_type,
                "image_url_content_length": content_length,
                "image_url_reachable": 200 <= response.status_code < 300 and content_type in ALLOWED_PUBLIC_IMAGE_MIME_TYPES and (content_length is None or content_length > 0) and bool(response.content[:1]),
            })
    except Exception as exc:
        debug["image_url_error"] = str(exc)
    return debug


def extract_image_url_check_debug(image_debug: dict[str, Any] | None) -> dict[str, Any] | None:
    if not image_debug or "image_url_check_mode" not in image_debug:
        return None
    return {key: image_debug.get(key) for key in IMAGE_URL_CHECK_KEYS if key in image_debug}


def image_url_check_allows_application(image_url_check: dict[str, Any]) -> bool:
    if image_url_check.get("image_url_check_mode") == "local_file_check":
        return image_url_check.get("local_file_exists") is True
    return image_url_check.get("image_url_reachable") is True


def image_url_check_error_message(image_url_check: dict[str, Any]) -> str:
    if image_url_check.get("image_url_check_mode") == "local_file_check" and not image_url_check.get("local_file_exists"):
        return "图片本地文件不存在，无法继续调用阿里云应用"
    return "图片 URL 不是公网可访问地址，阿里云应用无法读取图片"


class AliyunWorkflowParamGenerationService:
    def _required_env(self, name: str) -> str:
        value = os.getenv(name, "").strip()
        if not value:
            raise WorkflowConfigurationError(f"未配置环境变量 {name}")
        return value

    def _env(self, *names: str, default: str = "") -> str:
        for name in names:
            value = os.getenv(name, "").strip()
            if value:
                return value
        return default

    def public_image_url(self, public_base_url: str, saved_relative_path: str) -> str:
        base = public_base_url.strip().rstrip("/")
        if not base:
            raise WorkflowConfigurationError("PUBLIC_BASE_URL 为空，无法生成公网图片 URL")
        if not (base.startswith("http://") or base.startswith("https://")):
            raise WorkflowConfigurationError("PUBLIC_BASE_URL 必须以 http:// 或 https:// 开头")
        return f"{base}/{saved_relative_path.lstrip('/')}"

    def call_workflow(
        self,
        image_url: str,
        user_hint: str | None = None,
        *,
        image_debug: dict[str, Any] | None = None,
    ) -> StreamAggregationResult:
        """Backward-compatible method name; now calls the Aliyun agent application API."""
        try:
            return self.call_application(image_url, user_hint, stream=True, image_debug=image_debug, attempt_count=1)
        except WorkflowRequestError as stream_exc:
            fallback_enabled = _env_enabled(os.getenv("ALIYUN_APPLICATION_ENABLE_FALLBACK", ""), default=False)
            if not fallback_enabled:
                raise
            logger.warning("Aliyun application streaming call failed; retrying once without streaming: %s", stream_exc)
            try:
                return self.call_application(
                    image_url,
                    user_hint,
                    stream=False,
                    prior_debug=stream_exc.upstream_debug,
                    image_debug=image_debug,
                    attempt_count=2,
                )
            except WorkflowRequestError:
                raise

    def call_application(
        self,
        image_url: str,
        user_hint: str | None = None,
        *,
        stream: bool = True,
        prior_debug: dict[str, Any] | None = None,
        image_debug: dict[str, Any] | None = None,
        attempt_count: int = 1,
        skip_image_check: bool = False,
    ) -> StreamAggregationResult:
        api_key = self._env("ALIYUN_APPLICATION_API_KEY", "ALIYUN_WORKFLOW_API_KEY")
        app_id = self._env("ALIYUN_APPLICATION_APP_ID", "ALIYUN_WORKFLOW_APP_ID")
        base_url = self._env("ALIYUN_APPLICATION_BASE_URL", "ALIYUN_WORKFLOW_BASE_URL").rstrip("/")
        if not api_key:
            raise WorkflowConfigurationError("未配置环境变量 ALIYUN_APPLICATION_API_KEY/ALIYUN_WORKFLOW_API_KEY")
        if not app_id:
            raise WorkflowConfigurationError("未配置环境变量 ALIYUN_APPLICATION_APP_ID/ALIYUN_WORKFLOW_APP_ID")
        if not base_url:
            raise WorkflowConfigurationError("未配置环境变量 ALIYUN_APPLICATION_BASE_URL/ALIYUN_WORKFLOW_BASE_URL")
        default_prompt = self._env("ALIYUN_APPLICATION_DEFAULT_PROMPT", "ALIYUN_WORKFLOW_DEFAULT_PROMPT", default="请根据图片生成 CompositionParamDocument 参数 JSON。只输出 JSON。")
        prompt = (user_hint or "").strip() or default_prompt
        try:
            read_timeout = float(self._env("ALIYUN_APPLICATION_READ_TIMEOUT_SECONDS", "ALIYUN_WORKFLOW_TIMEOUT_SECONDS", default="300"))
        except ValueError:
            read_timeout = 300.0
        url = f"{base_url}/{app_id}/completion"
        skip_image_check = skip_image_check or image_debug is None
        precomputed_image_url_check = extract_image_url_check_debug(image_debug)
        if skip_image_check:
            image_url_check = {"image_url_reachable": None, "image_url_status": None, "application_call_attempted": False}
        elif precomputed_image_url_check is not None:
            image_url_check = {**precomputed_image_url_check, "application_call_attempted": False}
        else:
            image_url_check = {**check_public_image_url(image_url), "application_call_attempted": False}
        image_field_name = self._env("ALIYUN_APPLICATION_IMAGE_FIELD", default="imageUrl")
        biz_params = {
            "source_width": (image_debug or {}).get("source_width"),
            "source_height": (image_debug or {}).get("source_height"),
        }
        if image_url:
            biz_params.update({"imageUrl": image_url, "imageList": [image_url]})
            if image_field_name not in biz_params:
                biz_params[image_field_name] = image_url
        biz_params = {key: value for key, value in biz_params.items() if value is not None}
        body_dict = {
            "input": {"prompt": prompt, "biz_params": biz_params},
            "parameters": {"incremental_output": stream},
            "debug": {},
        }
        payload_debug = build_payload_debug(
            endpoint_url=url,
            app_id=app_id,
            body_dict=body_dict,
            image_field_name=image_field_name,
            image_url=image_url,
            image_debug={**(image_debug or {}), **image_url_check},
            attempt_count=attempt_count,
            attempt_mode="stream" if stream else "non_stream",
        )
        logger.info("Aliyun application sanitized request payload: %s", json.dumps(payload_debug, ensure_ascii=False, default=str))
        if not skip_image_check and not image_url_check_allows_application(image_url_check):
            message = image_url_check_error_message(image_url_check)
            debug = build_upstream_debug(
                error_message=message,
                **payload_debug,
            )
            raise WorkflowRequestError(message, None, "", upstream_debug=debug)
        payload_debug["application_call_attempted"] = True
        payload_debug["image_input_debug"]["application_call_attempted"] = True
        body = json.dumps(body_dict, ensure_ascii=False).encode("utf-8")
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream" if stream else "application/json",
        }
        if stream:
            headers["X-DashScope-SSE"] = "enable"
        request = urllib.request.Request(url, data=body, headers=headers, method="POST")
        started = time.monotonic()
        try:
            with urllib.request.urlopen(request, timeout=read_timeout) as response:
                status = getattr(response, "status", 200)
                request_id = response.headers.get("X-Request-Id") or response.headers.get("x-acs-request-id")
                if status < 200 or status >= 300:
                    raw_body = response.read().decode("utf-8", errors="replace")
                    debug = build_upstream_debug(request_id=request_id, status_code=status, total_elapsed_ms=_elapsed_ms(started), error_message=_extract_error_message(raw_body) or "调用阿里云智能体应用失败", **payload_debug)
                    raise WorkflowRequestError("调用阿里云智能体应用失败", status, raw_body, upstream_debug=debug)
                if stream:
                    aggregation = aggregate_application_stream(response, started=started, status_code=status, request_id=request_id)
                    aggregation.upstream_debug = merge_debug(payload_debug, aggregation.upstream_debug)
                    return aggregation
                raw_body = response.read().decode("utf-8", errors="replace")
                debug = build_upstream_debug(request_id=request_id, status_code=status, chunk_count=1 if raw_body else 0, first_chunk_ms=_elapsed_ms(started) if raw_body else None, total_elapsed_ms=_elapsed_ms(started), **payload_debug)
                return aggregate_non_stream_body(raw_body, debug)
        except urllib.error.HTTPError as exc:
            preview = exc.read().decode("utf-8", errors="replace") if exc.fp else str(exc)
            request_id = getattr(exc, "headers", {}).get("X-Request-Id") or getattr(exc, "headers", {}).get("x-acs-request-id") or _extract_request_id(preview)
            message = _extract_error_message(preview) or str(exc)
            debug = build_upstream_debug(request_id=request_id, status_code=exc.code, total_elapsed_ms=_elapsed_ms(started), error_message=message, **payload_debug)
            if prior_debug:
                debug["stream_retry_debug"] = prior_debug
            logger.warning("Aliyun application HTTP error status=%s request_id=%s message=%s", exc.code, request_id, message)
            raise WorkflowRequestError("调用阿里云智能体应用失败", exc.code, preview, upstream_debug=debug) from exc
        except WorkflowRequestError:
            raise
        except Exception as exc:
            debug = build_upstream_debug(total_elapsed_ms=_elapsed_ms(started), error_message=str(exc), **payload_debug)
            if prior_debug:
                debug["stream_retry_debug"] = prior_debug
            logger.exception("Aliyun application request failed")
            raise WorkflowRequestError("调用阿里云智能体应用失败", None, str(exc), upstream_debug=debug) from exc

    def generate(self, image_url: str, user_hint: str | None = None, image_debug: dict[str, Any] | None = None) -> WorkflowGenerationResult:
        try:
            aggregation_result = self.call_workflow(image_url, user_hint, image_debug=image_debug)
        except TypeError as exc:
            if "image_debug" not in str(exc):
                raise
            aggregation_result = self.call_workflow(image_url, user_hint)
        if isinstance(aggregation_result, StreamAggregationResult):
            aggregation = aggregation_result
        else:
            # Keep old tests and any local monkeypatches working while the real path now uses streaming.
            raw_text = extract_workflow_text(aggregation_result)
            aggregation = StreamAggregationResult(raw_text, [aggregation_result], build_upstream_debug(chunk_count=1 if raw_text else 0))
        raw_text = aggregation.raw_text.strip()
        if not raw_text:
            debug = dict(aggregation.upstream_debug)
            debug["error_message"] = debug.get("error_message") or "阿里云应用已被调用，但应用观测显示无模型输入/输出，疑似应用未收到有效 prompt 或图片变量。"
            raise WorkflowParseError(
                "阿里云应用已被调用，但应用观测显示无模型输入/输出，疑似应用未收到有效 prompt 或图片变量。",
                raw_workflow_response=aggregation.raw_events,
                raw_text=raw_text,
                errors=[{"path": "raw_text", "message": "模型输出为空；请检查 upstream_debug 中的 request payload、prompt 和 biz_params 图片变量"}],
                upstream_debug=debug,
            )
        sanitized = extract_workflow_document(aggregation.raw_events, raw_text, aggregation.upstream_debug)
        document = sanitized["document"]
        textarea_json = json.dumps(document, ensure_ascii=False, indent=2)
        return WorkflowGenerationResult(
            "生成成功",
            image_url,
            aggregation.raw_events,
            raw_text,
            document,
            textarea_json,
            sanitized.get("warnings", []),
            sanitized.get("dropped_elements", []),
            sanitized.get("strict_validation", {"valid": True, "errors": []}),
            aggregation.upstream_debug,
        )


def _elapsed_ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)


def aggregate_non_stream_body(raw_body: str, debug: dict[str, Any]) -> StreamAggregationResult:
    if not raw_body.strip():
        return StreamAggregationResult("", [], debug)
    try:
        event = json.loads(raw_body)
    except json.JSONDecodeError:
        return StreamAggregationResult(raw_body.strip(), [raw_body], debug)
    text, event_debug = extract_text_from_event(event)
    _merge_event_debug(debug, event_debug)
    if text:
        raw_text = text.strip()
    elif any(key in event for key in ("output", "usage", "token_usage", "request_id", "requestId")):
        raw_text = ""
    else:
        raw_text = raw_body.strip()
    debug["raw_text_length"] = len(raw_text)
    return StreamAggregationResult(raw_text, [event], debug)


def aggregate_application_stream(response: Any, *, started: float, status_code: int, request_id: str | None = None) -> StreamAggregationResult:
    text_parts: list[str] = []
    raw_events: list[Any] = []
    chunk_count = 0
    first_chunk_ms: int | None = None
    finish_reason: str | None = None
    error_message: str | None = None
    resolved_request_id = request_id
    data_lines: list[str] = []

    def dispatch(data: str) -> None:
        nonlocal chunk_count, first_chunk_ms, finish_reason, error_message, resolved_request_id
        payload = data.strip()
        if not payload or payload == "[DONE]":
            return
        if first_chunk_ms is None:
            first_chunk_ms = _elapsed_ms(started)
        chunk_count += 1
        try:
            event: Any = json.loads(payload)
        except json.JSONDecodeError:
            event = payload
        raw_events.append(event)
        text, event_debug = extract_text_from_event(event)
        if text:
            text_parts.append(text)
        resolved_request_id = event_debug.get("request_id") or resolved_request_id
        finish_reason = event_debug.get("finish_reason") or finish_reason
        error_message = event_debug.get("error_message") or error_message

    while True:
        raw_line = response.readline()
        if raw_line == b"" or raw_line == "":
            break
        line = raw_line.decode("utf-8", errors="replace") if isinstance(raw_line, bytes) else str(raw_line)
        stripped = line.strip("\r\n")
        if not stripped:
            if data_lines:
                dispatch("\n".join(data_lines))
                data_lines = []
            continue
        if stripped.startswith(":"):
            continue
        if stripped.startswith("data:"):
            data_lines.append(stripped[5:].lstrip())
            continue
        if stripped.startswith("event:") or stripped.startswith("id:") or stripped.startswith("retry:"):
            continue
        dispatch(stripped)
    if data_lines:
        dispatch("\n".join(data_lines))
    debug = build_upstream_debug(
        request_id=resolved_request_id,
        status_code=status_code,
        chunk_count=chunk_count,
        first_chunk_ms=first_chunk_ms,
        total_elapsed_ms=_elapsed_ms(started),
        finish_reason=finish_reason,
        error_message=error_message,
    )
    raw_text = "".join(text_parts).strip()
    debug["raw_text_length"] = len(raw_text)
    return StreamAggregationResult(raw_text, raw_events, debug)


def extract_text_from_event(event: Any) -> tuple[str, dict[str, Any]]:
    debug: dict[str, Any] = {}
    if isinstance(event, str):
        return event, debug
    if not isinstance(event, dict):
        return "", debug
    debug["request_id"] = event.get("request_id") or event.get("requestId") or event.get("RequestId")
    debug["finish_reason"] = event.get("finish_reason") or event.get("finishReason")
    debug["error_message"] = _extract_error_message(event)
    usage = event.get("usage") or event.get("token_usage") or event.get("tokenUsage")
    if usage is not None:
        debug["token_usage"] = usage
    output = event.get("output") if isinstance(event.get("output"), dict) else {}
    if isinstance(output.get("usage"), dict):
        debug["token_usage"] = output.get("usage")
    if output:
        debug["finish_reason"] = output.get("finish_reason") or output.get("finishReason") or debug.get("finish_reason")
    choices = event.get("choices") or output.get("choices")
    if isinstance(choices, list) and choices:
        choice = choices[0]
        if isinstance(choice, dict):
            debug["finish_reason"] = choice.get("finish_reason") or debug.get("finish_reason")
            delta = choice.get("delta") if isinstance(choice.get("delta"), dict) else {}
            message = choice.get("message") if isinstance(choice.get("message"), dict) else {}
            for candidate in (delta.get("content"), message.get("content"), choice.get("text")):
                if isinstance(candidate, str):
                    return candidate, debug
    for candidate in (
        output.get("text"),
        output.get("result"),
        output.get("content"),
        event.get("text"),
        event.get("content"),
        event.get("result"),
    ):
        if isinstance(candidate, str):
            return candidate, debug
    message = output.get("message") or event.get("message")
    if isinstance(message, dict):
        content = message.get("content")
        if isinstance(content, str):
            return content, debug
    return "", debug


def _merge_event_debug(debug: dict[str, Any], event_debug: dict[str, Any]) -> None:
    for key in ("request_id", "finish_reason", "error_message", "token_usage"):
        if event_debug.get(key):
            debug[key] = event_debug[key]


def _extract_request_id(raw: Any) -> str | None:
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            match = re.search(r'"(?:request_id|requestId|RequestId)"\s*:\s*"([^"]+)"', raw)
            return match.group(1) if match else None
    if isinstance(raw, dict):
        return raw.get("request_id") or raw.get("requestId") or raw.get("RequestId")
    return None


def _extract_error_message(raw: Any) -> str | None:
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            return raw.strip()[:500] or None
    if not isinstance(raw, dict):
        return None
    for key in ("message", "Message", "error_message", "errorMessage"):
        value = raw.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    error = raw.get("error")
    if isinstance(error, dict):
        for key in ("message", "Message", "code"):
            value = error.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return None


def extract_workflow_text(response_json: Any) -> str:
    if isinstance(response_json, StreamAggregationResult):
        return response_json.raw_text
    if isinstance(response_json, dict):
        text, _ = extract_text_from_event(response_json)
        if text.strip():
            return text.strip()
    if isinstance(response_json, str) and response_json.strip():
        return response_json.strip()
    raise WorkflowParseError("阿里云响应为空", raw_workflow_response=response_json)


def strip_markdown_fence(raw_text: str) -> str:
    text = raw_text.strip()
    if text.startswith("```"):
        text = JSON_FENCE_RE.sub("", text).strip()
    return text


def parse_json_from_text(raw_text: str, response_json: Any | None = None, upstream_debug: dict[str, Any] | None = None) -> Any:
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
            upstream_debug=upstream_debug,
        ) from original_exc


def extract_workflow_document(response_json: Any, raw_text: str | None = None, upstream_debug: dict[str, Any] | None = None) -> dict[str, Any]:
    parsed = parse_json_from_text(raw_text, response_json, upstream_debug) if raw_text is not None else response_json
    if not isinstance(parsed, dict):
        raise WorkflowParseError("返回 JSON 顶层必须是 document 对象", raw_workflow_response=response_json, raw_text=raw_text or "", upstream_debug=upstream_debug)
    sanitized = sanitize_composition_document(parsed)
    if not sanitized.get("valid"):
        raise WorkflowParseError(
            sanitized.get("message") or "返回 JSON 中没有可渲染元素",
            raw_workflow_response=response_json,
            raw_text=raw_text or "",
            errors=sanitized.get("errors") or sanitized.get("strict_validation", {}).get("errors") or [{"path": "elements", "message": "清洗后没有可渲染元素"}],
            upstream_debug=upstream_debug,
        )
    return sanitized
