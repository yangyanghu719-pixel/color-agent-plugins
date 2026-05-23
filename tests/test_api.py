from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image, ImageDraw

from app.main import app

client = TestClient(app)


def _create_test_image(path: Path) -> None:
    img = Image.new("RGB", (320, 240), "blue")
    img.save(path)


def _create_white_abstract_image(path: Path) -> None:
    img = Image.new("RGB", (400, 300), "white")
    draw = ImageDraw.Draw(img)
    draw.ellipse([40, 40, 150, 150], fill="black")
    draw.rectangle([220, 70, 360, 180], fill="red")
    draw.line([60, 240, 350, 250], fill="black", width=10)
    img.save(path)


def test_health():
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"


def test_composition_page():
    resp = client.get("/composition")
    assert resp.status_code == 200
    for keyword in [
        "构图测试实验台",
        "使用说明",
        "实验导师",
        "上传原图",
        "调整后整图实时预览 / 当前实验图",
    ]:
        assert keyword in resp.text


def test_composition_layer_test_page():
    resp = client.get("/composition-layer-test")
    assert resp.status_code == 200
    assert "图元提取测试页" in resp.text


def test_upload_image_success(tmp_path):
    image_path = tmp_path / "upload-test.png"
    _create_test_image(image_path)

    with image_path.open("rb") as f:
        resp = client.post("/upload-image", files={"file": ("upload-test.png", f, "image/png")})

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "success"
    assert body["original_image_display_url"]
    assert body["current_image_display_url"]

    saved_path = Path(body["image_url"])
    assert saved_path.exists()


def test_extract_elements_success(tmp_path):
    image_path = tmp_path / "white-abstract.png"
    _create_white_abstract_image(image_path)

    with image_path.open("rb") as f:
        up_resp = client.post("/upload-image", files={"file": ("white-abstract.png", f, "image/png")})
    up_body = up_resp.json()
    assert up_body["status"] == "success"

    resp = client.post(
        "/composition/extract-elements",
        json={"image_url": up_body["display_url"], "max_layers": 24, "min_area": 80},
    )
    assert resp.status_code == 200
    body = resp.json()

    assert body["status"] == "success"
    assert body["layer_count"] >= 2
    assert body["layers"]

    for layer in body["layers"]:
        assert layer["image_url"]
        assert layer["mask_url"]
        assert layer["bbox"]
        assert layer["type"]

        layer_file = Path(layer["image_url"].lstrip("/"))
        mask_file = Path(layer["mask_url"].lstrip("/"))
        assert layer_file.exists()
        assert mask_file.exists()

    debug_mask_file = Path(body["debug"]["debug_mask_url"].lstrip("/"))
    assert debug_mask_file.exists()
