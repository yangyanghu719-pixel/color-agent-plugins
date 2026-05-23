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
    image_path = tmp_path / "color-elements.png"
    _create_color_element_image(image_path)

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
    assert body["layer_count"] >= 4
    assert body["layers"]
    assert sum(1 for x in body["layers"] if x["type"] == "solid_shape") >= 2

    for layer in body["layers"]:
        assert layer["image_url"]
        assert layer["mask_url"]
        assert layer["bbox"]
        assert layer["type"]

        layer_file = Path(layer["image_url"].lstrip("/"))
        mask_file = Path(layer["mask_url"].lstrip("/"))
        assert layer_file.exists()
        assert mask_file.exists()
        if layer["type"] == "unknown":
            x, y, bw, bh = layer["bbox"]
            assert (bw * bh) / (body["canvas_width"] * body["canvas_height"]) < 0.85

    if any(x["type"] == "large_group" for x in body["layers"]):
        assert body["debug"]["warnings"]

    debug_mask_file = Path(body["debug"]["debug_mask_url"].lstrip("/"))
    debug_overlay_file = Path(body["debug"]["debug_overlay_url"].lstrip("/"))
    assert debug_mask_file.exists()
    assert debug_overlay_file.exists()
