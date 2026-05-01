from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health():
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"


def test_segment_structure():
    resp = client.post("/segment", json={"image_url": "https://example.com/demo.jpg", "color_count": 4})
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "success"
    assert len(body["color_regions"]) == 4
    assert set(body["color_regions"][0].keys()) >= {
        "id", "name", "hex", "rgb", "hsl", "percentage", "role", "mask_url", "soft_mask_url", "description"
    }


def test_recolor_hsl_change():
    payload = {
        "image_id": "img-mock-001",
        "original_image_url": "https://example.com/demo.jpg",
        "target_region_id": "region-1",
        "original_hsl": {"h": 10, "s": 50, "l": 40},
        "new_hsl": {"h": 20, "s": 55, "l": 35},
    }
    resp = client.post("/recolor", json=payload)
    assert resp.status_code == 200
    change = resp.json()["change"]
    assert change == {"delta_h": 10, "delta_s": 5, "delta_l": -5}


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
