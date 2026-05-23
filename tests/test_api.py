from pathlib import Path
import json

from fastapi.testclient import TestClient
from PIL import Image, ImageDraw

from app.main import app

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
    path = Path("app/static/examples/composition_param_sample.json")
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


def test_sample_json_exists_and_has_required_fields():
    path = Path("app/static/examples/composition_param_sample.json")
    assert path.exists()
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert len(payload["elements"]) >= 10
    for element in payload["elements"]:
        assert "id" in element
        assert "type" in element
        assert "role" in element
        assert "z_index" in element
