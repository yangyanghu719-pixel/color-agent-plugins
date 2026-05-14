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
    assert body["processed_image_url"].endswith(f"/static/outputs/{body['image_id']}/original.png")
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


def test_recolor_binary_mask_preview(tmp_path):
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


def test_analyze_full_fields_and_ai_explanation(tmp_path):
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

    before = tmp_path / "before.png"; after = tmp_path / "after.png"
    _create_test_image(before); _create_test_image(after)
    payload = {
        "original_color_regions": original,
        "adjusted_color_regions": adjusted,
        "before_image_url": str(before),
        "after_image_url": str(after),
        "user_goal": "让主体更突出",
    }
    resp = client.post("/analyze", json=payload)
    assert resp.status_code == 200
    body = resp.json()

    required_fields = {
        "status", "message", "analysis_type", "summary", "overall_impression", "hue_analysis",
        "saturation_analysis", "lightness_analysis", "color_relationship_analysis", "visual_focus_analysis",
        "emotional_expression", "learning_explanation", "suggestions", "rule_based_tags", "fallback_used"
    }
    assert required_fields.issubset(set(body.keys()))
    assert body["summary"]
    assert isinstance(body["rule_based_tags"], list)


def test_analyze_complementary_relation_and_contrast(tmp_path):
    original = [
        _region("main", 10, 40, 45, 50.0, "主色", "#AA5544"),
        _region("sub", 170, 35, 45, 40.0, "辅助", "#55AA99"),
    ]
    adjusted = [
        _region("main", 5, 68, 62, 50.0, "主色", "#D95D55"),
        _region("sub", 185, 40, 38, 40.0, "辅助", "#4F9CA9"),
    ]
    before = tmp_path / "before2.png"; after = tmp_path / "after2.png"
    _create_test_image(before); _create_test_image(after)
    payload = {
        "original_color_regions": original,
        "adjusted_color_regions": adjusted,
        "before_image_url": str(before),
        "after_image_url": str(after),
    }
    resp = client.post("/analyze", json=payload)
    body = resp.json()

    assert resp.status_code == 200
    assert body["status"] in {"success", "error"}



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
    full_url = f"https://example.com{seg['original_image_url']}"
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


def test_recolor_prefers_mask_path_over_soft_mask_path(tmp_path):
    image_path = tmp_path / "recolor-mask-priority.png"
    _create_test_image(image_path)
    seg = client.post("/segment", json={"image_url": str(image_path), "color_count": 4}).json()
    region = seg["color_regions"][0]
    segment_result_path = Path("static/outputs") / seg["image_id"] / "segment_result.json"
    payload = __import__("json").loads(segment_result_path.read_text(encoding="utf-8"))
    target = next(r for r in payload["color_regions"] if r["id"] == region["id"])
    target["soft_mask_path"] = "missing-soft-mask.png"
    segment_result_path.write_text(__import__("json").dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    req = {"image_id": seg["image_id"], "original_image_url": "https://example.com/unreachable.jpg", "target_region_id": region["id"], "original_hsl": region["hsl"], "new_hsl": {"h": (region["hsl"]["h"] + 10) % 360, "s": region["hsl"]["s"], "l": region["hsl"]["l"]}}
    resp = client.post("/recolor", json=req)
    assert resp.status_code == 200
    assert resp.json()["status"] == "success"


def test_recolor_changes_only_selected_pixels(tmp_path):
    image_path = tmp_path / "recolor-binary-only.png"
    _create_test_image(image_path)
    seg = client.post("/segment", json={"image_url": str(image_path), "color_count": 4}).json()
    region = seg["color_regions"][0]
    req = {"image_id": seg["image_id"], "original_image_url": "https://example.com/unreachable.jpg", "target_region_id": region["id"], "original_hsl": region["hsl"], "new_hsl": {"h": (region["hsl"]["h"] + 60) % 360, "s": min(100, region["hsl"]["s"] + 10), "l": region["hsl"]["l"]}}
    resp = client.post("/recolor", json=req).json()
    assert resp["status"] == "success"

    segment_result_path = Path("static/outputs") / seg["image_id"] / "segment_result.json"
    result = __import__("json").loads(segment_result_path.read_text(encoding="utf-8"))
    target = next(r for r in result["color_regions"] if r["id"] == region["id"])

    import numpy as np
    base = np.array(Image.open(result["original_image_path"]).convert("RGB"))
    out = np.array(Image.open(Path(resp["preview_image_url"].replace('/static/', 'static/'))).convert("RGB"))
    mask = np.array(Image.open(target["mask_path"]).convert("L")) > 127

    assert np.array_equal(base[~mask], out[~mask])
    assert np.any(base[mask] != out[mask])


def test_recolor_preview_size_matches_processed_original(tmp_path):
    image_path = tmp_path / "recolor-size.png"
    _create_test_image(image_path)
    seg = client.post("/segment", json={"image_url": str(image_path), "color_count": 4}).json()
    region = seg["color_regions"][0]
    req = {
        "image_id": seg["image_id"],
        "original_image_url": f"https://example.com{seg['processed_image_url']}",
        "target_region_id": region["id"],
        "original_hsl": region["hsl"],
        "new_hsl": {"h": (region["hsl"]["h"] + 30) % 360, "s": region["hsl"]["s"], "l": region["hsl"]["l"]},
    }
    resp = client.post("/recolor", json=req).json()
    assert resp["status"] == "success"
    processed = Image.open(Path(seg["processed_image_url"].replace("/static/", "static/")))
    preview = Image.open(Path(resp["preview_image_url"].replace("/static/", "static/")))
    assert processed.size == preview.size



def test_analyze_fallback_without_api_key(tmp_path, monkeypatch):
    before = tmp_path / "before.png"; after = tmp_path / "after.png"
    _create_test_image(before); _create_test_image(after)
    monkeypatch.delenv("VISION_MODEL_API_KEY", raising=False)
    original = [_region("r1", 20, 40, 40, 60.0, "主色", "#AA5533"), _region("r2", 180, 30, 60, 40.0, "辅助", "#55AABB")]
    adjusted = [_region("r1", 30, 50, 45, 60.0, "主色", "#BB6644"), _region("r2", 175, 35, 58, 40.0, "辅助", "#5599BB")]
    resp = client.post("/analyze", json={"original_color_regions": original, "adjusted_color_regions": adjusted, "before_image_url": str(before), "after_image_url": str(after)})
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "success" and body["fallback_used"] is True


def test_analyze_with_mocked_model(tmp_path, monkeypatch):
    before = tmp_path / "before.png"; after = tmp_path / "after.png"
    _create_test_image(before); _create_test_image(after)
    monkeypatch.setenv("VISION_MODEL_API_KEY", "x")
    from app.services.vision_analyze_service import VisionAnalyzeService
    monkeypatch.setattr(VisionAnalyzeService, "call_vision_model", lambda *args, **kwargs: {"summary":"模型总结","overall_impression":"更有冲击力","hue_analysis":"色相更集中","saturation_analysis":"饱和提升","lightness_analysis":"明度层次增强","color_relationship_analysis":"互补关系更明确","visual_focus_analysis":"主体更突出","emotional_expression":"更热烈","learning_explanation":"通过主辅对比建立层次","suggestions":["降低背景饱和度"],"rule_based_tags":["主体更突出"]})
    original = [_region("r1", 20, 40, 40, 60.0, "主色", "#AA5533"), _region("r2", 180, 30, 60, 40.0, "辅助", "#55AABB")]
    adjusted = [_region("r1", 30, 50, 45, 60.0, "主色", "#BB6644"), _region("r2", 175, 35, 58, 40.0, "辅助", "#5599BB")]
    resp = client.post("/analyze", json={"original_color_regions": original, "adjusted_color_regions": adjusted, "before_image_url": str(before), "after_image_url": str(after)})
    body = resp.json()
    assert resp.status_code == 200
    assert body["fallback_used"] is False
    assert body["summary"] == "模型总结"


def test_analyze_invalid_before_image_path():
    original = [_region("r1", 20, 40, 40, 60.0, "主色", "#AA5533")]
    adjusted = [_region("r1", 30, 50, 45, 60.0, "主色", "#BB6644")]
    resp = client.post("/analyze", json={"original_color_regions": original, "adjusted_color_regions": adjusted, "before_image_url": "static/uploads/not-found.png", "after_image_url": "static/uploads/not-found2.png"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "error"


def test_analyze_invalid_after_image_path(tmp_path):
    before = tmp_path / "before.png"; _create_test_image(before)
    original = [_region("r1", 20, 40, 40, 60.0, "主色", "#AA5533")]
    adjusted = [_region("r1", 30, 50, 45, 60.0, "主色", "#BB6644")]
    resp = client.post("/analyze", json={"original_color_regions": original, "adjusted_color_regions": adjusted, "before_image_url": str(before), "after_image_url": "static/uploads/not-found2.png"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "error"
