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
    assert 'id="prompt"' not in resp.text
    assert 'name="prompt"' not in resp.text
    assert "Prompt" not in resp.text
    assert 'type="file"' in resp.text
    assert 'name="image"' in resp.text
    assert "色彩与构成学习平台" in resp.text
    assert "每个页面会使用独立任务记录" in resp.text
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


def test_aliyun_app_chat_test_page_hides_backend_storage_panel():
    resp = client.get("/aliyun-app-chat-test")

    assert resp.status_code == 200
    assert "后台保存状态" not in resp.text
    assert "只保存上传原图、JSON 渲染 PNG/JSON 文件夹" not in resp.text
    assert "完成构图或色彩 A/B 分析后的三份结果文件" not in resp.text
    assert 'id="operationLogStatus"' not in resp.text
    assert 'id="downloadOperationCsvBtn"' not in resp.text
    assert "/aliyun-app-chat-test/operation-log" not in resp.text
    assert "/aliyun-app-chat-test/operation-log.csv" not in resp.text


def test_operation_artifact_uses_upload_folder_structure(monkeypatch):
    monkeypatch.delenv("GITHUB_OPERATION_TOKEN", raising=False)

    result = main.write_operation_text_artifact("pytest-folder-001", "JSON_2026-06-05T00-00-00Z/构图分析_2026-06-05T00-01-00Z_分析结果.md", "分析文本", "test commit")

    assert "upload_pytest-folder-001" in result["local_path"]
    assert result["repo_path"] == "backend_data_storage/upload_pytest-folder-001/JSON_2026-06-05T00-00-00Z/构图分析_2026-06-05T00-01-00Z_分析结果.md"
    assert result["github"]["enabled"] is False


def test_github_put_file_uses_contents_api_with_branch_and_base64(monkeypatch):
    monkeypatch.setenv("GITHUB_OPERATION_TOKEN", "token-test")
    monkeypatch.setenv("GITHUB_OPERATION_REPO", "owner/repo")
    monkeypatch.setenv("GITHUB_OPERATION_BRANCH", "composition-lab-data")
    calls = {}

    class FakeResponse:
        def __init__(self, status_code, text="{}"):
            self.status_code = status_code
            self.text = text

        def json(self):
            return {"sha": "sha-existing"}

    def fake_get(url, headers, params, timeout):
        calls["get"] = {"url": url, "headers": headers, "params": params, "timeout": timeout}
        return FakeResponse(404)

    def fake_put(url, headers, json, timeout):
        calls["put"] = {"url": url, "headers": headers, "json": json, "timeout": timeout}
        return FakeResponse(201, '{"content": {}}')

    monkeypatch.setattr(main.requests, "get", fake_get)
    monkeypatch.setattr(main.requests, "put", fake_put)

    result = main.github_put_file("backend_data_storage/upload_t1/JSON_2026-06-05T00-00-00Z/JSON_2026-06-05T00-00-00Z.json", b"{}", "save data")

    assert result["ok"] is True
    assert calls["get"]["params"] == {"ref": "composition-lab-data"}
    assert calls["put"]["json"]["branch"] == "composition-lab-data"
    assert calls["put"]["json"]["content"] == "e30="
    assert calls["put"]["headers"]["Authorization"] == "Bearer token-test"
    assert "upload_t1" in calls["put"]["url"]


def test_save_rendered_json_canvas_creates_json_named_artifacts(monkeypatch):
    monkeypatch.delenv("GITHUB_OPERATION_TOKEN", raising=False)
    data_url = "data:image/png;base64," + __import__("base64").b64encode(_png_bytes()).decode("ascii")

    resp = client.post(
        "/aliyun-app-chat-test/save-rendered-json-canvas",
        json={
            "task_id": "pytest-json-001",
            "json_save_id": "JSON_2026-06-05T00-00-00Z",
            "data_url": data_url,
            "textarea_json": "{\"version\": \"1.0\"}",
        },
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["json_save_id"] == "JSON_2026-06-05T00-00-00Z"
    assert body["artifact_path"] == "backend_data_storage/upload_pytest-json-001/JSON_2026-06-05T00-00-00Z.png"
    assert body["json_artifact_path"] == "backend_data_storage/upload_pytest-json-001/JSON_2026-06-05T00-00-00Z/JSON_2026-06-05T00-00-00Z.json"


def test_completed_ab_analysis_artifacts_use_single_timestamp_folder(monkeypatch, tmp_path):
    monkeypatch.delenv("GITHUB_OPERATION_TOKEN", raising=False)
    image_a_path = main.WORKFLOW_INPUT_DIR / "pytest-a.png"
    image_b_path = main.WORKFLOW_INPUT_DIR / "pytest-b.png"
    image_a_path.write_bytes(_png_bytes())
    image_b_path.write_bytes(_png_bytes())

    saved = main.write_completed_ab_analysis_artifacts(
        task_id="pytest-ab-001",
        image_a_url="https://composition-lab.onrender.com/static/uploads/workflow_inputs/pytest-a.png",
        image_b_url="https://composition-lab.onrender.com/static/uploads/workflow_inputs/pytest-b.png",
        analysis_text="分析结果",
        json_save_id="JSON_2026-06-05T00-00-00Z",
        analysis_save_id="构图分析_2026-06-05T00-01-00Z",
    )

    assert saved["json_save_id"] == "JSON_2026-06-05T00-00-00Z"
    assert saved["analysis_save_id"] == "构图分析_2026-06-05T00-01-00Z"
    repo_paths = [artifact["repo_path"] for artifact in saved["artifacts"]]
    assert repo_paths == [
        "backend_data_storage/upload_pytest-ab-001/JSON_2026-06-05T00-00-00Z/构图分析_2026-06-05T00-01-00Z_图片A.png",
        "backend_data_storage/upload_pytest-ab-001/JSON_2026-06-05T00-00-00Z/构图分析_2026-06-05T00-01-00Z_图片B.png",
        "backend_data_storage/upload_pytest-ab-001/JSON_2026-06-05T00-00-00Z/构图分析_2026-06-05T00-01-00Z_分析结果.md",
    ]


def test_completed_ab_color_analysis_artifacts_use_color_prefix(monkeypatch):
    monkeypatch.delenv("GITHUB_OPERATION_TOKEN", raising=False)
    image_a_path = main.WORKFLOW_INPUT_DIR / "pytest-color-a.png"
    image_b_path = main.WORKFLOW_INPUT_DIR / "pytest-color-b.png"
    image_a_path.write_bytes(_png_bytes())
    image_b_path.write_bytes(_png_bytes())

    saved = main.write_completed_ab_analysis_artifacts(
        task_id="pytest-color-ab-001",
        image_a_url="https://composition-lab.onrender.com/static/uploads/workflow_inputs/pytest-color-a.png",
        image_b_url="https://composition-lab.onrender.com/static/uploads/workflow_inputs/pytest-color-b.png",
        analysis_text="色彩分析结果",
        json_save_id="JSON_2026-06-05T00-00-00Z",
        analysis_save_id="色彩分析_2026-06-05T00-02-00Z",
        kind="color",
    )

    assert saved["json_save_id"] == "JSON_2026-06-05T00-00-00Z"
    assert saved["analysis_save_id"] == "色彩分析_2026-06-05T00-02-00Z"
    repo_paths = [artifact["repo_path"] for artifact in saved["artifacts"]]
    assert repo_paths == [
        "backend_data_storage/upload_pytest-color-ab-001/JSON_2026-06-05T00-00-00Z/色彩分析_2026-06-05T00-02-00Z_图片A.png",
        "backend_data_storage/upload_pytest-color-ab-001/JSON_2026-06-05T00-00-00Z/色彩分析_2026-06-05T00-02-00Z_图片B.png",
        "backend_data_storage/upload_pytest-color-ab-001/JSON_2026-06-05T00-00-00Z/色彩分析_2026-06-05T00-02-00Z_分析结果.md",
    ]
