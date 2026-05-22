from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image

from app.main import app

client = TestClient(app)


def _create_test_image(path: Path) -> None:
    img = Image.new("RGB", (320, 240), "blue")
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
