import io
import json

from fastapi.testclient import TestClient

from app.main import app
import app.main as main

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
    assert 'id="colorPanel"' in resp.text
    assert "校验/渲染几何信息" in resp.text
    assert "HSL 可调色" in resp.text
    assert "updateHslSliderBackgrounds" in resp.text
    assert "--hsl-track" in resp.text
    assert "linear-gradient(90deg, #000000" in resp.text
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


def test_aliyun_app_chat_test_page_has_ab_comparison_controls():
    resp = client.get("/aliyun-app-chat-test")

    assert resp.status_code == 200
    assert "将构图保存为图 A" in resp.text
    assert "将构图保存为图 B" in resp.text
    assert "分析 A/B 构图差异" in resp.text
    assert "A/B 色彩比较" in resp.text
    assert "将色彩保存为图 A" in resp.text
    assert "将色彩保存为图 B" in resp.text
    assert "分析 A/B 色彩差异" in resp.text
    assert 'id="thumbA"' in resp.text
    assert 'id="thumbB"' in resp.text
    assert 'id="colorThumbA"' in resp.text
    assert 'id="colorThumbB"' in resp.text
    assert "/aliyun-app-chat-test/save-composition-image" in resp.text
    assert "/aliyun-app-chat-test/analyze-ab" in resp.text
    assert "/aliyun-app-chat-test/analyze-ab-color" in resp.text
    assert "async function currentCanvasDataUrl()" in resp.text
    assert "currentCanvasSvgBlobUrl" in resp.text


def test_aliyun_app_chat_test_save_composition_image_returns_public_url():
    data_url = "data:image/png;base64," + __import__("base64").b64encode(_png_bytes()).decode("ascii")

    resp = client.post("/aliyun-app-chat-test/save-composition-image", json={"slot": "A", "data_url": data_url})

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["slot"] == "A"
    assert body["public_image_url"].startswith("https://composition-lab.onrender.com/static/uploads/workflow_inputs/composition-ab-a-")
    assert body["static_path"].startswith("/static/uploads/workflow_inputs/composition-ab-a-")
    assert client.get(body["static_path"]).content == _png_bytes()


def test_aliyun_app_chat_test_analyze_ab_calls_dashscope_compatible_api(monkeypatch):
    monkeypatch.setenv("ALIYUN_API_KEY", "test-key")
    captured = {}

    class FakeVisionResponse:
        status_code = 200
        headers = {"X-Request-Id": "req-vision"}

        def json(self):
            return {"choices": [{"message": {"content": "A/B 构图分析结果"}}]}

    def fake_post(url, headers, json, timeout):
        captured.update({"url": url, "headers": headers, "json": json, "timeout": timeout})
        return FakeVisionResponse()

    monkeypatch.setattr("app.services.aliyun_app_chat_test_service.requests.post", fake_post)
    image_a = "https://composition-lab.onrender.com/static/uploads/workflow_inputs/a.png"
    image_b = "https://composition-lab.onrender.com/static/uploads/workflow_inputs/b.png"

    resp = client.post("/aliyun-app-chat-test/analyze-ab", json={"image_a_url": image_a, "image_b_url": image_b})

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["analysis"] == "A/B 构图分析结果"
    assert captured["url"] == "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
    assert captured["headers"]["Authorization"] == "Bearer test-key"
    assert captured["json"]["model"] == "qwen3.6-plus"
    assert captured["json"]["messages"][0]["content"][0] == {"type": "image_url", "image_url": {"url": image_a}}
    assert captured["json"]["messages"][0]["content"][1] == {"type": "image_url", "image_url": {"url": image_b}}
    assert "图像构成课" in captured["json"]["messages"][0]["content"][2]["text"]


def test_aliyun_app_chat_test_analyze_ab_color_uses_color_teacher_prompt(monkeypatch):
    monkeypatch.setenv("ALIYUN_API_KEY", "test-key")
    captured = {}

    class FakeVisionResponse:
        status_code = 200
        headers = {"X-Request-Id": "req-color"}

        def json(self):
            return {"choices": [{"message": {"content": "A/B 色彩分析结果"}}]}

    def fake_post(url, headers, json, timeout):
        captured.update({"url": url, "headers": headers, "json": json, "timeout": timeout})
        return FakeVisionResponse()

    monkeypatch.setattr("app.services.aliyun_app_chat_test_service.requests.post", fake_post)
    image_a = "https://composition-lab.onrender.com/static/uploads/workflow_inputs/a.png"
    image_b = "https://composition-lab.onrender.com/static/uploads/workflow_inputs/b.png"

    resp = client.post("/aliyun-app-chat-test/analyze-ab-color", json={"image_a_url": image_a, "image_b_url": image_b})

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["analysis"] == "A/B 色彩分析结果"
    assert captured["url"] == "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
    assert captured["headers"]["Authorization"] == "Bearer test-key"
    assert captured["json"]["model"] == "qwen3.6-plus"
    assert captured["json"]["messages"][0]["content"][0] == {"type": "image_url", "image_url": {"url": image_a}}
    assert captured["json"]["messages"][0]["content"][1] == {"type": "image_url", "image_url": {"url": image_b}}
    color_prompt = captured["json"]["messages"][0]["content"][2]["text"]
    assert "图像色彩课程" in color_prompt
    assert "色彩关系" in color_prompt
    assert "构图而不是" not in color_prompt
    assert body["request_debug"]["analysis_type"] == "color"


def test_aliyun_app_chat_test_page_has_operation_log_controls():
    resp = client.get("/aliyun-app-chat-test")

    assert resp.status_code == 200
    assert "操作数据收集" in resp.text
    assert 'id="downloadOperationCsvBtn"' in resp.text
    assert "/aliyun-app-chat-test/operation-log" in resp.text
    assert "/aliyun-app-chat-test/operation-log.csv" in resp.text
    assert "backend_data_storage" in resp.text
    assert "task_id" in resp.text


def test_aliyun_app_chat_test_operation_log_records_csv_row():
    task_id = "pytest-task-001"

    resp = client.post(
        "/aliyun-app-chat-test/operation-log",
        json={"task_id": task_id, "event_type": "button_click", "event_label": "生成 JSON"},
    )
    csv_resp = client.get("/aliyun-app-chat-test/operation-log.csv")

    assert resp.status_code == 200
    assert resp.json() == {"ok": True, "task_id": task_id}
    assert csv_resp.status_code == 200
    assert "text/csv" in csv_resp.headers["content-type"]
    csv_text = csv_resp.content.decode("utf-8-sig")
    assert "task_id,created_at,updated_at,prompt,manual_uploaded_image,ai_raw_image" in csv_text
    assert task_id in csv_text
    assert "button_click" in csv_text
    assert "生成 JSON" in csv_text


def test_operation_artifact_uses_reference_folder_structure(monkeypatch):
    monkeypatch.delenv("GITHUB_OPERATION_TOKEN", raising=False)

    result = main.write_operation_text_artifact("pytest-folder-001", "任务1_构图比较/构图对比分析文本.txt", "分析文本", "test commit")

    assert "上传照片_pytest-folder-001" in result["local_path"]
    assert result["repo_path"] == "backend_data_storage/上传照片_pytest-folder-001/任务1_构图比较/构图对比分析文本.txt"
    assert result["github"]["enabled"] is False


def test_github_put_file_uses_contents_api_with_branch_and_base64(monkeypatch):
    monkeypatch.setenv("GITHUB_OPERATION_TOKEN", "token-test")
    monkeypatch.setenv("GITHUB_OPERATION_REPO", "owner/repo")
    monkeypatch.setenv("GITHUB_OPERATION_BRANCH", "composition-lab-data")
    calls = {"gets": []}

    class FakeResponse:
        def __init__(self, status_code, text="{}", payload=None):
            self.status_code = status_code
            self.text = text
            self._payload = payload or {"sha": "sha-existing", "object": {"sha": "branch-sha"}}

        def json(self):
            return self._payload

    def fake_get(url, headers, params=None, timeout=20):
        calls["gets"].append({"url": url, "headers": headers, "params": params, "timeout": timeout})
        if "/git/ref/heads/composition-lab-data" in url:
            return FakeResponse(200, payload={"object": {"sha": "branch-sha"}})
        return FakeResponse(404)

    def fake_put(url, headers, json, timeout):
        calls["put"] = {"url": url, "headers": headers, "json": json, "timeout": timeout}
        return FakeResponse(201, '{"content": {}}')

    monkeypatch.setattr(main.requests, "get", fake_get)
    monkeypatch.setattr(main.requests, "put", fake_put)

    result = main.github_put_file("backend_data_storage/上传照片_t1/当前任务汇总.json", b"{}", "save data")

    assert result["ok"] is True
    assert result["branch_result"] == {"ok": True, "created": False, "branch": "composition-lab-data"}
    assert calls["gets"][-1]["params"] == {"ref": "composition-lab-data"}
    assert calls["put"]["json"]["branch"] == "composition-lab-data"
    assert calls["put"]["json"]["content"] == "e30="
    assert calls["put"]["headers"]["Authorization"] == "Bearer token-test"
    assert "%E4%B8%8A%E4%BC%A0%E7%85%A7%E7%89%87_t1" in calls["put"]["url"]


def test_github_put_file_creates_missing_data_branch(monkeypatch):
    monkeypatch.setenv("GITHUB_OPERATION_TOKEN", "token-test")
    monkeypatch.setenv("GITHUB_OPERATION_REPO", "owner/repo")
    monkeypatch.setenv("GITHUB_OPERATION_BRANCH", "composition-lab-data")
    calls = {"gets": []}

    class FakeResponse:
        def __init__(self, status_code, text="{}", payload=None):
            self.status_code = status_code
            self.text = text
            self._payload = payload or {}

        def json(self):
            return self._payload

    def fake_get(url, headers, params=None, timeout=20):
        calls["gets"].append(url)
        if "/git/ref/heads/composition-lab-data" in url:
            return FakeResponse(404)
        if url == "https://api.github.com/repos/owner/repo":
            return FakeResponse(200, payload={"default_branch": "composition-lab"})
        if "/git/ref/heads/composition-lab" in url:
            return FakeResponse(200, payload={"object": {"sha": "source-sha"}})
        if "/contents/" in url:
            return FakeResponse(404)
        return FakeResponse(404)

    def fake_post(url, headers, json, timeout):
        calls["post"] = {"url": url, "headers": headers, "json": json, "timeout": timeout}
        return FakeResponse(201, '{"ref": "refs/heads/composition-lab-data"}')

    def fake_put(url, headers, json, timeout):
        calls["put"] = {"url": url, "headers": headers, "json": json, "timeout": timeout}
        return FakeResponse(201, '{"content": {}}')

    monkeypatch.setattr(main.requests, "get", fake_get)
    monkeypatch.setattr(main.requests, "post", fake_post)
    monkeypatch.setattr(main.requests, "put", fake_put)

    result = main.github_put_file("backend_data_storage/上传照片_t1/当前任务汇总.json", b"{}", "save data")

    assert result["ok"] is True
    assert result["branch_result"]["created"] is True
    assert calls["post"]["json"] == {"ref": "refs/heads/composition-lab-data", "sha": "source-sha"}
    assert calls["put"]["json"]["branch"] == "composition-lab-data"
