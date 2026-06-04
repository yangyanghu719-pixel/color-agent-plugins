import json
import time
import urllib.error
from pathlib import Path

import pytest

from app.services.aliyun_workflow_param_generation_service import (
    AliyunWorkflowParamGenerationService,
    WorkflowParseError,
    WorkflowRequestError,
    aggregate_application_stream,
    extract_workflow_document,
    parse_json_from_text,
)


def _sample_json() -> dict:
    return json.loads(Path("static/examples/composition_param_sample.json").read_text(encoding="utf-8"))


class FakeStreamResponse:
    status = 200

    def __init__(self, lines):
        self.lines = [line.encode("utf-8") for line in lines]
        self.index = 0
        self.headers = {"X-Request-Id": "req-stream"}

    def readline(self):
        if self.index >= len(self.lines):
            return b""
        line = self.lines[self.index]
        self.index += 1
        return line


def _sse_event(payload: dict) -> list[str]:
    return [f"data: {json.dumps(payload, ensure_ascii=False)}\n", "\n"]


def test_streaming_response_chunks_are_aggregated_into_json():
    payload = json.dumps(_sample_json(), ensure_ascii=False)
    lines = []
    lines += _sse_event({"request_id": "req-1", "output": {"text": payload[:40]}})
    lines += _sse_event({"output": {"text": payload[40:], "finish_reason": "stop"}})

    result = aggregate_application_stream(FakeStreamResponse(lines), started=time.monotonic(), status_code=200)

    assert json.loads(result.raw_text)["version"] == _sample_json()["version"]
    assert result.upstream_debug["request_id"] == "req-1"
    assert result.upstream_debug["chunk_count"] == 2
    assert result.upstream_debug["finish_reason"] == "stop"


def test_streaming_response_ignores_empty_and_heartbeat_chunks_before_content():
    payload = json.dumps(_sample_json(), ensure_ascii=False)
    lines = ["\n", ": keep-alive\n", "data: \n", "\n"]
    lines += _sse_event({"request_id": "req-late", "output": {"text": payload}})

    result = aggregate_application_stream(FakeStreamResponse(lines), started=time.monotonic(), status_code=200)

    assert json.loads(result.raw_text)["elements"]
    assert result.upstream_debug["request_id"] == "req-late"
    assert result.upstream_debug["chunk_count"] == 1


def test_application_http_500_internal_error_exposes_request_id(monkeypatch):
    service = AliyunWorkflowParamGenerationService()
    monkeypatch.setenv("ALIYUN_WORKFLOW_API_KEY", "key")
    monkeypatch.setenv("ALIYUN_WORKFLOW_APP_ID", "app")
    monkeypatch.setenv("ALIYUN_WORKFLOW_BASE_URL", "https://dashscope.example.com/apps")
    body = json.dumps({"request_id": "req-500", "code": "InternalError", "message": "InternalError"}).encode()

    def raise_http_error(*args, **kwargs):
        raise urllib.error.HTTPError(
            url="https://dashscope.example.com/apps/app/completion",
            code=500,
            msg="Internal Server Error",
            hdrs={"X-Request-Id": "req-500"},
            fp=type("Body", (), {"read": lambda self: body, "close": lambda self: None})(),
        )

    monkeypatch.setattr("urllib.request.urlopen", raise_http_error)

    with pytest.raises(WorkflowRequestError) as exc_info:
        service.call_application("https://public.example.com/a.png", stream=True)

    exc = exc_info.value
    assert exc.upstream_status == 500
    assert exc.upstream_debug["request_id"] == "req-500"
    assert exc.upstream_debug["status_code"] == 500
    assert exc.upstream_debug["error_message"] == "InternalError"


def test_parse_json_from_text_extracts_object_between_explanatory_text():
    text = "下面是结果：\n" + json.dumps(_sample_json(), ensure_ascii=False) + "\n以上供参考。"

    parsed = parse_json_from_text(text)

    assert parsed["version"] == _sample_json()["version"]
    assert parsed["elements"]


def test_application_sanitizer_drops_bad_elements_but_keeps_document_valid():
    payload = _sample_json()
    payload["elements"] = [
        {"id": "bad", "type": "bad_type"},
        payload["elements"][0],
    ]

    sanitized = extract_workflow_document([], json.dumps(payload, ensure_ascii=False))

    assert sanitized["valid"] is True
    assert len(sanitized["document"]["elements"]) == 1
    assert sanitized["dropped_elements"][0]["index"] == 0


def test_application_sanitizer_invalid_when_all_elements_dropped():
    payload = _sample_json()
    payload["elements"] = [{"id": "bad", "type": "bad_type"}]

    with pytest.raises(WorkflowParseError) as exc_info:
        extract_workflow_document([], json.dumps(payload, ensure_ascii=False))

    assert "清洗后没有可渲染元素" in str(exc_info.value)
    assert exc_info.value.errors
