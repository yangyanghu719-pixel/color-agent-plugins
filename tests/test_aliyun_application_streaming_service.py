import json
import time
import urllib.error
from pathlib import Path

import pytest

from app.services.aliyun_workflow_param_generation_service import (
    AliyunWorkflowParamGenerationService,
    WorkflowParseError,
    WorkflowRequestError,
    _vision_call_mode,
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

class FakeJsonResponse:
    status = 200
    headers = {"X-Request-Id": "req-json"}

    def __init__(self, payload: dict):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return json.dumps(self.payload, ensure_ascii=False).encode("utf-8")


def _set_app_env(monkeypatch):
    monkeypatch.setenv("ALIYUN_WORKFLOW_API_KEY", "key")
    monkeypatch.setenv("ALIYUN_WORKFLOW_APP_ID", "app-1234567890")
    monkeypatch.setenv("ALIYUN_WORKFLOW_BASE_URL", "https://dashscope.example.com/apps")


def _set_application_mode(monkeypatch):
    monkeypatch.setenv("ALIYUN_VISION_CALL_MODE", "application")


def test_application_payload_contains_prompt_and_biz_params(monkeypatch):
    import app.services.aliyun_workflow_param_generation_service as aliyun_service

    service = AliyunWorkflowParamGenerationService()
    _set_app_env(monkeypatch)
    monkeypatch.setattr(
        aliyun_service,
        "check_public_image_url",
        lambda image_url: {"image_url_reachable": True, "image_url_status": 200, "image_url_content_type": "image/png", "image_url_content_length": 12},
    )
    captured = {}

    def fake_urlopen(request, timeout):
        captured["payload"] = json.loads(request.data.decode("utf-8"))
        captured["url"] = request.full_url
        return FakeJsonResponse({"output": {"text": json.dumps(_sample_json(), ensure_ascii=False)}, "usage": {"total_tokens": 12}})

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    result = service.call_application(
        "https://public.example.com/static/uploads/workflow_inputs/a.png",
        user_hint="保留主体",
        stream=False,
        image_debug={"image_size_bytes": 12, "image_mime_type": "image/png", "source_width": 10, "source_height": 20},
    )

    payload = captured["payload"]
    assert payload["input"]["prompt"] == "保留主体"
    assert "biz_params" in payload["input"]
    assert payload["input"]["biz_params"]["imageUrl"].startswith("https://public.example.com/")
    assert payload["input"]["biz_params"]["imageList"] == [payload["input"]["biz_params"]["imageUrl"]]
    assert "image_list" not in payload["input"]
    assert payload["parameters"]["incremental_output"] is False
    assert result.upstream_debug["prompt_present"] is True
    assert result.upstream_debug["biz_params_keys"]
    assert result.upstream_debug["image_input_debug"]["value_type"] == "URL"
    assert result.upstream_debug["token_usage"] == {"total_tokens": 12}
    assert result.upstream_debug["actual_model_input_mode"] == "application_biz_params"
    assert result.upstream_debug["image_part_included"] is False
    assert result.upstream_debug["model_input_warning"] == "图片仅作为 biz_params 传入，可能不会进入模型 multimodal context。"
    assert result.upstream_debug["model_input_preview"]["input"]["biz_params"]["imageUrl"] == "<image-url>"


def test_image_url_unreachable_blocks_application_call(monkeypatch):
    import app.services.aliyun_workflow_param_generation_service as aliyun_service

    service = AliyunWorkflowParamGenerationService()
    _set_app_env(monkeypatch)
    monkeypatch.setattr(
        aliyun_service,
        "check_public_image_url",
        lambda image_url: {"image_url_reachable": False, "image_url_status": 404, "image_url_error": "not found"},
    )
    called = {"count": 0}

    def fake_urlopen(*args, **kwargs):
        called["count"] += 1
        return FakeJsonResponse({})

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    with pytest.raises(WorkflowRequestError) as exc_info:
        service.call_application("https://public.example.com/missing.png", stream=False, image_debug={"image_size_bytes": 1})

    assert called["count"] == 0
    assert "图片 URL 不是公网可访问地址" in str(exc_info.value)
    assert exc_info.value.upstream_debug["image_url_reachable"] is False
    assert exc_info.value.upstream_debug["image_url_status"] == 404



def test_same_host_local_file_check_continues_application_call(monkeypatch, tmp_path):
    import app.services.aliyun_workflow_param_generation_service as aliyun_service

    service = AliyunWorkflowParamGenerationService()
    _set_app_env(monkeypatch)
    image_path = tmp_path / "a.png"
    image_path.write_bytes(b"png-bytes")
    image_debug = {
        "image_size_bytes": image_path.stat().st_size,
        "image_mime_type": "image/png",
        "source_width": 10,
        "source_height": 20,
        **aliyun_service.build_local_file_image_url_check("https://composition-lab.onrender.com/static/uploads/workflow_inputs/a.png", image_path),
    }
    monkeypatch.setattr(aliyun_service, "check_public_image_url", lambda image_url: (_ for _ in ()).throw(AssertionError("same-host URL must not use HTTP self-check")))
    called = {"count": 0}

    def fake_urlopen(request, timeout):
        called["count"] += 1
        return FakeJsonResponse({"output": {"text": json.dumps(_sample_json(), ensure_ascii=False)}})

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    result = service.call_application(
        "https://composition-lab.onrender.com/static/uploads/workflow_inputs/a.png",
        stream=False,
        image_debug=image_debug,
    )

    assert called["count"] == 1
    assert result.upstream_debug["image_url_check_mode"] == "local_file_check"
    assert result.upstream_debug["local_file_exists"] is True
    assert result.upstream_debug["image_url_reachable"] == "skipped_same_host"
    assert result.upstream_debug["application_call_attempted"] is True


def test_local_file_missing_blocks_with_clear_error(monkeypatch, tmp_path):
    import app.services.aliyun_workflow_param_generation_service as aliyun_service

    service = AliyunWorkflowParamGenerationService()
    _set_app_env(monkeypatch)
    missing_path = tmp_path / "missing.png"
    image_debug = {
        "image_size_bytes": 0,
        "image_mime_type": "image/png",
        **aliyun_service.build_local_file_image_url_check(
            "https://composition-lab.onrender.com/static/uploads/workflow_inputs/missing.png",
            missing_path,
        ),
    }
    called = {"count": 0}

    def fake_urlopen(*args, **kwargs):
        called["count"] += 1
        return FakeJsonResponse({})

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    with pytest.raises(WorkflowRequestError) as exc_info:
        service.call_application(
            "https://composition-lab.onrender.com/static/uploads/workflow_inputs/missing.png",
            stream=False,
            image_debug=image_debug,
        )

    assert called["count"] == 0
    assert "图片本地文件不存在" in str(exc_info.value)
    assert exc_info.value.upstream_debug["local_file_exists"] is False
    assert exc_info.value.upstream_debug["application_call_attempted"] is False

def test_fallback_disabled_makes_single_upstream_attempt(monkeypatch):
    import app.services.aliyun_workflow_param_generation_service as aliyun_service

    service = AliyunWorkflowParamGenerationService()
    _set_app_env(monkeypatch)
    _set_application_mode(monkeypatch)
    monkeypatch.delenv("ALIYUN_APPLICATION_ENABLE_FALLBACK", raising=False)
    monkeypatch.setattr(
        aliyun_service,
        "check_public_image_url",
        lambda image_url: {"image_url_reachable": True, "image_url_status": 200, "image_url_content_type": "image/png", "image_url_content_length": 1},
    )
    calls = {"count": 0}

    def fake_urlopen(*args, **kwargs):
        calls["count"] += 1
        raise urllib.error.URLError("stream failed")

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    with pytest.raises(WorkflowRequestError) as exc_info:
        service.call_workflow("https://public.example.com/a.png", image_debug={"image_size_bytes": 1})

    assert calls["count"] == 1
    assert exc_info.value.upstream_debug["attempt_count"] == 1
    assert exc_info.value.upstream_debug["attempt_mode"] == "stream"


def test_empty_raw_text_error_includes_payload_debug():
    import app.services.aliyun_workflow_param_generation_service as aliyun_service

    service = AliyunWorkflowParamGenerationService()
    service.call_workflow = lambda image_url, user_hint=None, **kwargs: aliyun_service.StreamAggregationResult(  # type: ignore[name-defined]
        "",
        [],
        {
            "request_id": "req-empty",
            "prompt_present": True,
            "prompt_length": 8,
            "biz_params_keys": ["imageUrl"],
            "image_url_present": True,
            "image_url_reachable": True,
            "image_url_status": 200,
            "image_input_field_name": "imageUrl",
        },
    )

    with pytest.raises(WorkflowParseError) as exc_info:
        service.generate("https://public.example.com/a.png", image_debug={"image_size_bytes": 1})

    assert "疑似应用未收到有效 prompt 或图片变量" in str(exc_info.value)
    assert exc_info.value.upstream_debug["prompt_present"] is True
    assert exc_info.value.upstream_debug["biz_params_keys"] == ["imageUrl"]


def test_public_image_url_generation_is_absolute():
    service = AliyunWorkflowParamGenerationService()

    image_url = service.public_image_url("https://composition-lab.onrender.com/", "/static/uploads/workflow_inputs/a.png")

    assert image_url == "https://composition-lab.onrender.com/static/uploads/workflow_inputs/a.png"
    assert not image_url.startswith("/static/")


def _set_direct_vl_env(monkeypatch):
    monkeypatch.setenv("DASHSCOPE_API_KEY", "key")
    monkeypatch.setenv("ALIYUN_DASHSCOPE_BASE_URL", "https://dashscope.example.com/compatible-mode/v1")
    monkeypatch.setenv("ALIYUN_VISION_MODEL", "qwen-vl-plus")


def test_default_vision_call_mode_is_direct_vl(monkeypatch):
    monkeypatch.delenv("ALIYUN_VISION_CALL_MODE", raising=False)

    assert _vision_call_mode() == "direct_vl"


def test_application_mode_only_used_when_explicitly_configured(monkeypatch):
    monkeypatch.setenv("ALIYUN_VISION_CALL_MODE", "application")

    assert _vision_call_mode() == "application"

def test_direct_vl_payload_contains_image_url_part(monkeypatch):
    import app.services.aliyun_workflow_param_generation_service as aliyun_service

    service = AliyunWorkflowParamGenerationService()
    _set_direct_vl_env(monkeypatch)
    monkeypatch.setattr(
        aliyun_service,
        "check_public_image_url",
        lambda image_url: {"image_url_reachable": True, "image_url_status": 200, "image_url_content_type": "image/png", "image_url_content_length": 12},
    )
    captured = {}

    def fake_urlopen(request, timeout):
        captured["payload"] = json.loads(request.data.decode("utf-8"))
        return FakeJsonResponse({"choices": [{"message": {"content": json.dumps(_sample_json(), ensure_ascii=False)}, "finish_reason": "stop"}], "usage": {"total_tokens": 21}})

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    result = service.call_workflow("https://public.example.com/a.png", user_hint="转译图像", image_debug={"image_size_bytes": 12})

    content = captured["payload"]["messages"][0]["content"]
    assert content[0] == {"type": "image_url", "image_url": {"url": "https://public.example.com/a.png"}}
    assert result.upstream_debug["actual_model_input_mode"] == "direct_vl_messages"
    assert result.upstream_debug["image_part_included"] is True
    assert result.upstream_debug["image_part_field_name"] == "messages[].content[].image_url.url"
    assert result.upstream_debug["public_image_url"] == "https://public.example.com/a.png"
    assert result.upstream_debug["model_input_preview"]["messages"][0]["content"][0]["image_url"]["url"] == "https://public.example.com/a.png"


def test_direct_vl_payload_contains_text_prompt_and_image_url(monkeypatch):
    import app.services.aliyun_workflow_param_generation_service as aliyun_service

    service = AliyunWorkflowParamGenerationService()
    _set_direct_vl_env(monkeypatch)
    monkeypatch.setattr(aliyun_service, "check_public_image_url", lambda image_url: {"image_url_reachable": True, "image_url_status": 200, "image_url_content_type": "image/png", "image_url_content_length": 12})
    captured = {}

    def fake_urlopen(request, timeout):
        captured["payload"] = json.loads(request.data.decode("utf-8"))
        return FakeJsonResponse({"choices": [{"message": {"content": json.dumps(_sample_json(), ensure_ascii=False)}}]})

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    service.call_workflow("https://public.example.com/a.png", user_hint="保留蓝色主体", image_debug={"image_size_bytes": 12})

    content = captured["payload"]["messages"][0]["content"]
    assert content[0]["image_url"]["url"] == "https://public.example.com/a.png"
    assert content[1] == {"type": "text", "text": "保留蓝色主体"}


def test_text_only_model_input_returns_clear_error():
    import app.services.aliyun_workflow_param_generation_service as aliyun_service

    service = AliyunWorkflowParamGenerationService()
    service.call_workflow = lambda image_url, user_hint=None, **kwargs: aliyun_service.StreamAggregationResult(  # type: ignore[name-defined]
        json.dumps(_sample_json(), ensure_ascii=False),
        [],
        {"actual_model_input_mode": "text_only", "image_part_included": False},
    )

    with pytest.raises(WorkflowRequestError) as exc_info:
        service.generate("https://public.example.com/a.png", image_debug={"image_size_bytes": 1})

    assert "模型实际输入中没有图片 part" in str(exc_info.value)


def test_direct_vl_output_json_still_passes_through_sanitizer(monkeypatch):
    import app.services.aliyun_workflow_param_generation_service as aliyun_service

    service = AliyunWorkflowParamGenerationService()
    _set_direct_vl_env(monkeypatch)
    monkeypatch.setattr(aliyun_service, "check_public_image_url", lambda image_url: {"image_url_reachable": True, "image_url_status": 200, "image_url_content_type": "image/png", "image_url_content_length": 12})
    payload = _sample_json()
    payload["elements"] = [{"id": "bad", "type": "bad_type"}, payload["elements"][0]]

    def fake_urlopen(request, timeout):
        return FakeJsonResponse({"choices": [{"message": {"content": json.dumps(payload, ensure_ascii=False)}}]})

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    result = service.generate("https://public.example.com/a.png", image_debug={"image_size_bytes": 12})

    assert len(result.document["elements"]) == 1
    assert result.dropped_elements[0]["index"] == 0
    assert result.upstream_debug["actual_model_input_mode"] == "direct_vl_messages"
