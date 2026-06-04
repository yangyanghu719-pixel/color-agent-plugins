import io
import json

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


class FakeRequestsResponse:
    def __init__(self, lines, status_code=200):
        self._lines = lines
        self.status_code = status_code
        self.headers = {"X-Request-Id": "req-test"}

    def iter_lines(self, decode_unicode=False):
        for line in self._lines:
            if decode_unicode:
                yield line
            else:
                yield line.encode("utf-8")


def _png_bytes() -> bytes:
    return (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
        b"\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00"
        b"\x00\x00\x0cIDATx\x9cc``\x00\x00\x00\x04\x00\x01"
        b"\xf6\x178U\x00\x00\x00\x00IEND\xaeB`\x82"
    )


def _post_image(filename="test.png"):
    return {"image": (filename, io.BytesIO(_png_bytes()), "image/png")}


def _mock_env(monkeypatch):
    monkeypatch.setenv("ALIYUN_API_KEY", "test-key")
    monkeypatch.setenv("ALIYUN_APPLICATION_ID", "app-test")


def test_aliyun_app_chat_test_page_has_controls():
    resp = client.get("/aliyun-app-chat-test")

    assert resp.status_code == 200
    assert 'id="prompt"' in resp.text
    assert 'name="prompt"' in resp.text
    assert 'type="file"' in resp.text
    assert 'name="image"' in resp.text
    assert "生成 JSON" in resp.text
    assert 'id="jsonOutput"' in resp.text
    assert 'id="canvas"' in resp.text
    assert 'id="propertyPanel"' in resp.text
    assert "应用当前文本 JSON" in resp.text
    assert "textarea_json" in resp.text


def test_aliyun_app_chat_test_page_hides_debug_response_fields():
    resp = client.get("/aliyun-app-chat-test")

    assert resp.status_code == 200
    hidden_labels = [
        "public_image_url",
        "upstream_status",
        "sse_event_count",
        "text_mode",
        "raw_text_preview",
        "parsed_json",
        "recent_data_previews",
        "request_debug",
        "upstream_debug",
    ]
    for label in hidden_labels:
        assert label not in resp.text


def test_aliyun_app_chat_test_send_missing_image_returns_clear_error():
    resp = client.post("/aliyun-app-chat-test/send", data={"prompt": "go"})

    assert resp.status_code == 400
    body = resp.json()
    assert body["ok"] is False
    assert "上传图片" in body["message"]
    assert body["public_image_url"] == ""
    assert "upstream_debug" in body


def test_aliyun_app_chat_test_send_rejects_invalid_extension():
    resp = client.post(
        "/aliyun-app-chat-test/send",
        data={"prompt": "go"},
        files={"image": ("bad.gif", io.BytesIO(b"gif"), "image/gif")},
    )

    assert resp.status_code == 400
    body = resp.json()
    assert body["ok"] is False
    assert "文件类型不支持" in body["message"]


def test_aliyun_app_chat_test_send_parses_single_sse_chunk(monkeypatch):
    _mock_env(monkeypatch)
    captured = {}

    def fake_post(url, headers, json, stream, timeout):
        captured.update({"url": url, "headers": headers, "json": json, "stream": stream, "timeout": timeout})
        return FakeRequestsResponse(['event: result', '', 'data: {"output":{"text":"{\\"version\\":\\"1.0\\"}"}}', 'data: HTTP_STATUS/200'])

    monkeypatch.setattr("app.services.aliyun_app_chat_test_service.requests.post", fake_post)
    resp = client.post("/aliyun-app-chat-test/send", data={"prompt": "go"}, files=_post_image())

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["final_text"] == '{"version":"1.0"}'
    assert body["parsed_json"] == {"version": "1.0"}
    assert body["textarea_json"] == json.dumps({"version": "1.0"}, ensure_ascii=False, indent=2)
    assert body["sse_event_count"] == 1
    assert body["text_mode"] == "snapshot_latest_text"
    assert body["upstream_status"] == 200
    assert captured["url"] == "https://dashscope.aliyuncs.com/api/v1/apps/app-test/completion"
    assert captured["stream"] is True
    assert captured["timeout"] == 300
    assert captured["headers"]["X-DashScope-SSE"] == "enable"
    assert captured["headers"]["Content-Type"] == "application/json"
    assert captured["headers"]["Authorization"] == "Bearer test-key"
    assert captured["json"] == {"input": {"prompt": "go", "image_list": [body["public_image_url"]]}, "parameters": {}}


def test_aliyun_app_chat_test_send_uses_latest_snapshot_not_append(monkeypatch):
    _mock_env(monkeypatch)
    captured = {}

    def fake_post(url, headers, json, stream, timeout):
        captured["json"] = json
        return FakeRequestsResponse([
            'data: {"output":{"text":"{"}}',
            'data: {"output":{"text":"{\\"version\\""}}',
            'data: {"output":{"text":"{\\"version\\":\\"1.0\\"}"}}',
        ])

    monkeypatch.setattr("app.services.aliyun_app_chat_test_service.requests.post", fake_post)
    resp = client.post("/aliyun-app-chat-test/send", data={"prompt": "go"}, files=_post_image())

    assert resp.status_code == 200
    body = resp.json()
    assert body["final_text"] == '{"version":"1.0"}'
    assert body["final_text"] != '{{"version"{"version":"1.0"}'
    assert body["parsed_json"] == {"version": "1.0"}
    assert body["text_mode"] == "snapshot_latest_text"
    assert captured["json"] == {"input": {"prompt": "go", "image_list": [body["public_image_url"]]}, "parameters": {}}


def test_aliyun_app_chat_test_public_image_url_prefix(monkeypatch):
    _mock_env(monkeypatch)

    def fake_post(*args, **kwargs):
        return FakeRequestsResponse(['data: {"output":{"text":"{\\"version\\":\\"1.0\\"}"}}'])

    monkeypatch.setattr("app.services.aliyun_app_chat_test_service.requests.post", fake_post)
    resp = client.post("/aliyun-app-chat-test/send", data={"prompt": "go"}, files=_post_image())

    assert resp.status_code == 200
    assert resp.json()["public_image_url"].startswith(
        "https://composition-lab.onrender.com/static/uploads/workflow_inputs/"
    )


def test_aliyun_app_chat_test_page_does_not_expose_secret_headers():
    resp = client.get("/aliyun-app-chat-test")

    assert resp.status_code == 200
    assert "API key" not in resp.text
    assert "api_key" not in resp.text
    assert "Authorization" not in resp.text
