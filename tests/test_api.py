from pathlib import Path
import json

from fastapi.testclient import TestClient
from PIL import Image, ImageDraw

from app.main import app, param_generation_service
from app.services.composition_param_generation_service import QwenRequestError

client = TestClient(app)


def _create_test_image(path: Path) -> None:
    img = Image.new("RGB", (320, 240), "blue")
    img.save(path)


def _create_color_element_image(path: Path) -> None:
    img = Image.new("RGB", (520, 420), "white")
    draw = ImageDraw.Draw(img)
    draw.ellipse([40, 40, 160, 160], fill=(220, 20, 60))
    draw.ellipse([210, 60, 330, 180], fill=(40, 90, 230))
    draw.rectangle([360, 70, 490, 180], fill=(25, 160, 70))
    draw.rectangle([80, 220, 210, 340], fill=(20, 20, 20))
    draw.line([260, 250, 500, 370], fill=(20, 20, 20), width=8)
    img.save(path)


def test_health():
    resp = client.get("/health")
    assert resp.status_code == 200


def test_composition_page():
    resp = client.get("/composition")
    assert resp.status_code == 200


def test_composition_param_test_page():
    resp = client.get("/composition-param-test")
    assert resp.status_code == 200
    assert "点线面参数化渲染测试页" in resp.text
    for token in ["加载示例 JSON", "渲染 JSON", "清空画布", "删除对象", "复制对象", "上移一层", "下移一层", "新增对象"]:
        assert token in resp.text


def test_upload_image_success(tmp_path):
    image_path = tmp_path / "upload-test.png"
    _create_test_image(image_path)
    with image_path.open("rb") as f:
        resp = client.post("/upload-image", files={"file": ("upload-test.png", f, "image/png")})
    assert resp.status_code == 200
    assert resp.json()["status"] == "success"


def test_extract_elements_success(tmp_path):
    image_path = tmp_path / "color-elements.png"
    _create_color_element_image(image_path)
    with image_path.open("rb") as f:
        up_resp = client.post("/upload-image", files={"file": ("white-abstract.png", f, "image/png")})
    up_body = up_resp.json()
    resp = client.post("/composition/extract-elements", json={"image_url": up_body["display_url"], "max_layers": 24, "min_area": 80})
    assert resp.status_code == 200
    assert resp.json()["status"] == "success"


def _sample_json() -> dict:
    path = Path("static/examples/composition_param_sample.json")
    return json.loads(path.read_text(encoding="utf-8"))


def test_validate_param_json_valid_sample():
    resp = client.post("/composition/validate-param-json", json=_sample_json())
    assert resp.status_code == 200
    body = resp.json()
    assert body["valid"] is True
    assert body["element_count"] >= 10


def test_validate_param_json_invalid_type():
    payload = _sample_json()
    payload["elements"][0]["type"] = "bad_type"
    resp = client.post("/composition/validate-param-json", json=payload)
    assert resp.status_code == 200
    assert resp.json()["valid"] is False


def test_validate_param_json_out_of_range():
    payload = _sample_json()
    payload["elements"][0]["x"] = 1.5
    resp = client.post("/composition/validate-param-json", json=payload)
    assert resp.status_code == 200
    assert resp.json()["valid"] is False



def test_static_sample_json_served():
    resp = client.get("/static/examples/composition_param_sample.json")
    assert resp.status_code == 200


def test_sample_json_exists_and_has_required_fields():
    path = Path("static/examples/composition_param_sample.json")
    assert path.exists()
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert "version" in payload
    assert "canvas" in payload
    assert "source_summary" in payload
    assert "elements" in payload
    assert len(payload["elements"]) >= 10
    for element in payload["elements"]:
        assert "id" in element
        assert "type" in element
        assert "role" in element
        assert "z_index" in element



def test_param_test_page_render_flow_regression_controls():
    resp = client.get("/composition-param-test")
    assert resp.status_code == 200
    text = resp.text
    assert "setMeta(" not in text
    assert 'id="render"' in text
    assert 'id="apply"' in text
    assert 'id="errors"' in text
    assert 'id="success"' in text
    assert "解析失败" in text
    assert "渲染失败" in text


def test_param_test_page_has_validation_controls_for_valid_payload():
    validate_resp = client.post("/composition/validate-param-json", json=_sample_json())
    assert validate_resp.status_code == 200
    assert validate_resp.json()["valid"] is True

    page_resp = client.get("/composition-param-test")
    assert page_resp.status_code == 200
    assert "渲染 JSON" in page_resp.text
    assert "校验/渲染信息" in page_resp.text
    assert "fetch('/composition/validate-param-json'" in page_resp.text

def test_param_test_page_has_add_object_controls():
    resp = client.get("/composition-param-test")
    assert resp.status_code == 200
    assert "新增对象" in resp.text
    for t in ["circle", "rectangle", "triangle", "line", "dot"]:
        assert t in resp.text


def test_sample_json_contains_required_pattern_types():
    payload = _sample_json()
    types = {e["type"] for e in payload["elements"]}
    for t in ["dot_grid", "line_group", "grid_pattern", "triangle_pattern"]:
        assert t in types


def test_param_test_page_has_group_render_and_transform_logic():
    resp = client.get("/composition-param-test")
    assert resp.status_code == 200
    text = resp.text
    assert "dot_grid" in text and "dot_cluster" in text and "line_group" in text
    assert "dataset.handle='resize'" in text
    assert "dataset.handle='rotate'" in text
    assert "const { known, makeShapeNode } = window.CompositionParamRenderer" in text
    assert "closest?.('[data-id]')" in text
    assert '/static/js/composition_param_renderer.js' in text
    renderer = Path('static/js/composition_param_renderer.js').read_text(encoding='utf-8')
    assert "line_group'){ node=groupWrap" in renderer
    assert "type==='dot_grid'){ node=groupWrap" in renderer
    assert "type==='dot_cluster'){ node=groupWrap" in renderer
    assert "type==='grid_pattern'){ node=groupWrap" in renderer
    assert "type==='triangle_pattern'){ node=groupWrap" in renderer


def test_param_test_page_has_bbox_and_svg_coordinate_resize_logic():
    resp = client.get('/composition-param-test')
    assert resp.status_code == 200
    text = resp.text
    assert 'function getElementBBox' in text
    assert 'createSVGPoint()' in text
    assert 'getScreenCTM()' in text
    assert "corner==='tl'" in text
    assert "corner==='tr'" in text
    assert "corner==='bl'" in text
    assert "corner==='br'" in text
    assert "newWidth = oldRight - mouse.x" not in text  # doc string not embedded
    assert "const signX=transformState.corner.includes('l')?-1:1;" not in text


def test_composition_reference_test_page():
    resp = client.get("/composition-reference-test")
    assert resp.status_code == 200
    assert "上传参考图" in resp.text
    assert "生成参数 JSON" in resp.text
    assert "/static/js/composition_param_renderer.js" in resp.text
    assert "normalized_payload" in resp.text
    assert "normalization_warnings" in resp.text
    assert "后端返回了非 JSON 响应" in resp.text
    assert "parseBackendResponse" in resp.text
    assert "error_type" in resp.text
    assert "upstream_status" in resp.text
    assert "upstream_body_preview" in resp.text
    assert "source_summary.main_subject" in resp.text
    assert "source_summary.subject_region" in resp.text
    assert "复杂动漫人物、写实照片属于压力测试" in resp.text


def test_generate_param_json_requires_image():
    resp = client.post("/composition/generate-param-json")
    assert resp.status_code == 400
    body = resp.json()
    assert body["error_type"] == "missing_image"
    assert body["message"] == "未上传图片"


def test_generate_param_json_reports_missing_qwen_api_key(tmp_path, monkeypatch):
    monkeypatch.delenv("QWEN_API_KEY", raising=False)
    image_path = tmp_path / "reference.png"
    _create_test_image(image_path)
    with image_path.open("rb") as f:
        resp = client.post("/composition/generate-param-json", files={"image": ("reference.png", f, "image/png")})
    assert resp.status_code == 503
    body = resp.json()
    assert body["status"] == "error"
    assert body["valid"] is False
    assert body["error_type"] == "qwen_api_error"
    assert body["message"] == "Qwen API 调用失败"
    assert "QWEN_API_KEY" in body["errors"][0]["message"]
    assert body["normalized_payload"] is None
    assert body["normalization_warnings"] == []


def test_shared_composition_renderer_served():
    resp = client.get("/static/js/composition_param_renderer.js")
    assert resp.status_code == 200
    assert "CompositionParamRenderer" in resp.text
    assert "renderDocument" in resp.text


def test_reference_test_page_displays_source_image_info():
    resp = client.get("/composition-reference-test")
    assert resp.status_code == 200
    assert "source_image" in resp.text


def test_shared_renderer_preserves_document_canvas_ratio():
    renderer = Path("static/js/composition_param_renderer.js").read_text(encoding="utf-8")
    assert "doc.canvas.width" in renderer
    assert "doc.canvas.height" in renderer
    assert "preserveAspectRatio" in renderer
    assert "svg.style.aspectRatio" in renderer


def test_generate_param_json_normalizes_curve_line_bezier_fields(tmp_path, monkeypatch):
    image_path = tmp_path / "reference.png"
    _create_test_image(image_path)
    payload = _sample_json()
    payload["elements"] = [{
        "type": "curve_line", "x1": -0.1, "y1": 0.2, "cp1x": 0.3, "cp1y": 1.2,
        "cp2x": 0.7, "cp2y": 0.8, "x2": 1.1, "y2": 0.9,
    }]
    monkeypatch.setattr(param_generation_service, "generate_text", lambda image, hint: json.dumps(payload))

    with image_path.open("rb") as f:
        resp = client.post("/composition/generate-param-json", files={"image": ("reference.png", f, "image/png")})

    assert resp.status_code == 200
    body = resp.json()
    assert body["valid"] is True
    assert body["normalized_payload"]["elements"][0]["points"] == [[0, 0.2], [0.3, 1], [0.7, 0.8], [1, 0.9]]
    assert "elements[0]: converted curve_line bezier fields to points" in body["normalization_warnings"]


def test_generate_param_json_returns_source_ratio_and_forces_canvas(tmp_path, monkeypatch):
    image_path = tmp_path / "reference-16-9.png"
    Image.new("RGB", (1600, 900), "white").save(image_path)
    payload = _sample_json()
    payload["canvas"] = {"width": 1000, "height": 1000, "background": "#FFFFFF"}
    monkeypatch.setattr(param_generation_service, "generate_text", lambda image, hint: json.dumps(payload))

    with image_path.open("rb") as f:
        resp = client.post("/composition/generate-param-json", files={"image": ("reference-16-9.png", f, "image/png")})

    assert resp.status_code == 200
    body = resp.json()
    assert body["source_image"] == {"width": 1600, "height": 900, "aspect_ratio": 1.777778}
    assert body["document"]["canvas"] == {"width": 1000, "height": 562, "background": "#FFFFFF"}


def test_generate_param_json_reports_qwen_500_body_preview(tmp_path, monkeypatch):
    image_path = tmp_path / "reference.png"
    _create_test_image(image_path)

    def fail_generate(image, hint):
        raise QwenRequestError("Qwen API 调用失败", upstream_status=500, upstream_body_preview="Internal Server Error")

    monkeypatch.setattr(param_generation_service, "generate_text", fail_generate)
    with image_path.open("rb") as f:
        resp = client.post("/composition/generate-param-json", files={"image": ("reference.png", f, "image/png")})

    assert resp.status_code == 502
    body = resp.json()
    assert body["error_type"] == "qwen_api_error"
    assert body["message"] == "Qwen API 调用失败"
    assert body["upstream_status"] == 500
    assert body["upstream_body_preview"] == "Internal Server Error"
    assert body["valid"] is False


def test_generate_param_json_rejects_unsupported_file_type(tmp_path):
    image_path = tmp_path / "reference.gif"
    image_path.write_bytes(b"GIF89a")
    with image_path.open("rb") as f:
        resp = client.post("/composition/generate-param-json", files={"image": ("reference.gif", f, "image/gif")})
    assert resp.status_code == 400
    assert resp.json()["error_type"] == "unsupported_file_type"
    assert resp.json()["message"] == "不支持的图片格式"
