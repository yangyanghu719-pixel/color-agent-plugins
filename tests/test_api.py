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


def _region(region_id: str, h: int, s: int, l: int, percentage: float, role: str, hex_value: str) -> dict:
    return {
        "id": region_id,
        "name": region_id,
        "hex": hex_value,
        "rgb": {"r": 120, "g": 120, "b": 120},
        "hsl": {"h": h, "s": s, "l": l},
        "percentage": percentage,
        "role": role,
        "mask_url": "https://example.com/masks/mask.png",
        "soft_mask_url": "https://example.com/masks/mask-soft.png",
        "description": "desc",
    }


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


def test_analyze_full_fields_and_ai_explanation():
    original = [
        _region("region-main", 10, 52, 48, 45.0, "主体", "#C35A50"),
        _region("region-sub", 190, 34, 62, 35.0, "辅助", "#66A9BC"),
        _region("region-bg", 40, 22, 78, 20.0, "背景", "#D6CCB2"),
    ]
    adjusted = [
        _region("region-main", 8, 72, 56, 45.0, "主体", "#D95A4E"),
        _region("region-sub", 188, 46, 50, 35.0, "辅助", "#4E90B5"),
        _region("region-bg", 38, 18, 76, 20.0, "背景", "#D0C8B2"),
    ]

    payload = {
        "original_color_regions": original,
        "adjusted_color_regions": adjusted,
        "before_image_url": "https://example.com/before.png",
        "after_image_url": "https://example.com/after.png",
        "user_goal": "让主体更突出",
    }
    resp = client.post("/analyze", json=payload)
    assert resp.status_code == 200
    body = resp.json()

    required_fields = {
        "status", "message", "tags", "color_relation", "visual_feeling", "suitable_scenario",
        "summary", "ai_explanation", "risk", "next_step"
    }
    assert required_fields.issubset(set(body.keys()))
    assert body["ai_explanation"]
    assert any(tag in body["tags"] for tag in ["饱和度提升", "对比增强", "主体更突出"])


def test_analyze_complementary_relation_and_contrast():
    original = [
        _region("main", 10, 40, 45, 50.0, "主色", "#AA5544"),
        _region("sub", 170, 35, 45, 40.0, "辅助", "#55AA99"),
    ]
    adjusted = [
        _region("main", 5, 68, 62, 50.0, "主色", "#D95D55"),
        _region("sub", 185, 40, 38, 40.0, "辅助", "#4F9CA9"),
    ]
    payload = {
        "original_color_regions": original,
        "adjusted_color_regions": adjusted,
        "before_image_url": "https://example.com/before.png",
        "after_image_url": "https://example.com/after.png",
    }
    resp = client.post("/analyze", json=payload)
    body = resp.json()

    assert resp.status_code == 200
    assert "近互补/互补色" in body["color_relation"]
    assert any(tag in body["tags"] for tag in ["对比增强", "主体更突出"])


def test_experiment_page():
    resp = client.get("/experiment")
    assert resp.status_code == 200
    for keyword in [
        "色彩构成实验台",
        "实验导师",
        "上传原图",
        "调整后整图实时预览",
        "主色区域选择",
        "H/S/L 调色面板",
        "H 色相",
        "S 饱和度",
        "L 明度",
        "保存该色块调整",
        "已保存调整区域",
        "生成实验反馈",
        "请先选择一个主色区域",
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
    assert body["image_url"]
    assert body["display_url"]

    saved_path = Path(body["image_url"])
    assert saved_path.exists()


def test_recolor_uses_working_image_and_static_path(tmp_path):
    image_path = tmp_path / "recolor-seq.png"
    _create_test_image(image_path)
    seg = client.post("/segment", json={"image_url": str(image_path), "color_count": 4}).json()
    r1 = seg["color_regions"][0]
    p1 = {"image_id": seg["image_id"], "original_image_url": "https://example.com/unreachable.jpg", "target_region_id": r1["id"], "original_hsl": r1["hsl"], "new_hsl": {"h": (r1["hsl"]["h"] + 30) % 360, "s": r1["hsl"]["s"], "l": r1["hsl"]["l"]}}
    b1 = client.post("/recolor", json=p1).json()
    assert b1["status"] == "success"

    segment_result_path = Path("static/outputs") / seg["image_id"] / "segment_result.json"
    segment_result = __import__("json").loads(segment_result_path.read_text(encoding="utf-8"))
    segment_result["working_image_path"] = f"static/outputs/{seg['image_id']}/{Path(b1['preview_image_url']).name}"
    segment_result_path.write_text(__import__("json").dumps(segment_result, ensure_ascii=False, indent=2), encoding="utf-8")

    p2 = {"image_id": seg["image_id"], "original_image_url": "https://example.com/unreachable.jpg", "target_region_id": r1["id"], "original_hsl": p1["new_hsl"], "new_hsl": {"h": (p1["new_hsl"]["h"] + 15) % 360, "s": p1["new_hsl"]["s"], "l": p1["new_hsl"]["l"]}}
    b2 = client.post("/recolor", json=p2).json()
    assert b2["status"] == "success"

    payload = __import__("json").loads(segment_result_path.read_text(encoding="utf-8"))
    assert payload["working_image_path"].endswith(Path(b2["preview_image_url"]).name)
    assert len(payload["adjustment_history"]) >= 2


def test_recolor_accepts_full_static_url(tmp_path):
    image_path = tmp_path / "recolor-full-url.png"
    _create_test_image(image_path)
    seg = client.post("/segment", json={"image_url": str(image_path), "color_count": 4}).json()
    region = seg["color_regions"][0]
    full_url = f"https://color-agent-plugins.onrender.com{seg['original_image_url']}"
    payload = {
        "image_id": seg["image_id"],
        "original_image_url": full_url,
        "target_region_id": region["id"],
        "original_hsl": region["hsl"],
        "new_hsl": {"h": (region["hsl"]["h"] + 20) % 360, "s": region["hsl"]["s"], "l": region["hsl"]["l"]},
    }
    resp = client.post("/recolor", json=payload)
    assert resp.status_code == 200
    assert resp.json()["status"] == "success"
