from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image, ImageDraw

from app.main import app

client = TestClient(app)


def _create_test_image(path: Path) -> None:
    img = Image.new("RGB", (320, 240), "blue")
    draw = ImageDraw.Draw(img)
    draw.rectangle((0, 0, 160, 240), fill=(220, 40, 40))
    draw.rectangle((0, 160, 320, 240), fill=(40, 190, 70))
    draw.rectangle((250, 20, 305, 75), fill=(245, 220, 30))
    img.save(path)


def test_health():
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"


def test_segment_structure(tmp_path):
    image_path = tmp_path / "segment-test.png"
    _create_test_image(image_path)

    resp = client.post("/segment", json={"image_url": str(image_path), "color_count": 4})
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "success"
    assert 2 <= len(body["color_regions"]) <= 4
    assert body["annotated_image_url"]

    image_id = body["image_id"]
    segment_result = Path("static/outputs") / image_id / "segment_result.json"
    assert segment_result.exists()

    for region in body["color_regions"]:
        assert set(region.keys()) >= {
            "id", "name", "hex", "rgb", "hsl", "percentage", "role", "mask_url", "soft_mask_url", "description"
        }
        assert region["mask_url"]
        assert region["soft_mask_url"]


def test_recolor_mask_based_preview(tmp_path):
    image_path = tmp_path / "recolor-test.png"
    _create_test_image(image_path)

    segment_resp = client.post("/segment", json={"image_url": str(image_path), "color_count": 4})
    assert segment_resp.status_code == 200
    segment_body = segment_resp.json()

    target_region = segment_body["color_regions"][0]
    payload = {
        "image_id": segment_body["image_id"],
        "original_image_url": "https://example.com/unreachable-demo.jpg",
        "target_region_id": target_region["id"],
        "original_hsl": target_region["hsl"],
        "new_hsl": {
            "h": (target_region["hsl"]["h"] + 20) % 360,
            "s": min(100, target_region["hsl"]["s"] + 5),
            "l": max(0, target_region["hsl"]["l"] - 5),
        },
    }
    resp = client.post("/recolor", json=payload)
    assert resp.status_code == 200

    body = resp.json()
    assert body["status"] == "success"
    assert body["preview_image_url"]
    assert body["change"] == {"hue_change": 20, "saturation_change": 5, "lightness_change": -5}

    preview_path = Path(body["preview_image_url"].replace("/static/", "static/"))
    assert preview_path.exists()


def test_analyze_returns_explanation():
    region = {
        "id": "region-1",
        "name": "主体暖红",
        "hex": "#D9534F",
        "rgb": {"r": 217, "g": 83, "b": 79},
        "hsl": {"h": 2, "s": 64, "l": 58},
        "percentage": 34.0,
        "role": "主体",
        "mask_url": "https://example.com/masks/region-1.png",
        "soft_mask_url": "https://example.com/masks/region-1-soft.png",
        "description": "desc",
    }
    adjusted = {**region, "hsl": {"h": 2, "s": 70, "l": 50}}
    payload = {
        "original_color_regions": [region],
        "adjusted_color_regions": [adjusted],
        "before_image_url": "https://example.com/before.png",
        "after_image_url": "https://example.com/after.png",
        "user_goal": "更有冲击力",
    }
    resp = client.post("/analyze", json=payload)
    assert resp.status_code == 200
    assert resp.json()["ai_explanation"]
