from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image, ImageDraw

from app.main import app
from app.utils.color_analysis import compare_color_regions

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
        "emotional_expression", "learning_explanation", "model_markdown", "suggestions", "rule_based_tags", "fallback_used", "model_error"
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
        "色彩与形式构成实验台",
        "上传成功",
        "请选择本次实验方向",
        "色彩实验",
        "构图实验",
        "开始色彩实验",
        "开始构图实验",
        "生成构图反馈",
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
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    original = [_region("r1", 20, 40, 40, 60.0, "主色", "#AA5533"), _region("r2", 180, 30, 60, 40.0, "辅助", "#55AABB")]
    adjusted = [_region("r1", 30, 50, 45, 60.0, "主色", "#BB6644"), _region("r2", 175, 35, 58, 40.0, "辅助", "#5599BB")]
    resp = client.post("/analyze", json={"original_color_regions": original, "adjusted_color_regions": adjusted, "before_image_url": str(before), "after_image_url": str(after)})
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "success" and body["fallback_used"] is True


def test_analyze_with_mocked_model(tmp_path, monkeypatch):
    before = tmp_path / "before.png"; after = tmp_path / "after.png"
    _create_test_image(before); _create_test_image(after)
    monkeypatch.setenv("DASHSCOPE_API_KEY", "x")
    captured = {}
    def _mock_qwen(*args, **kwargs):
        captured.update(kwargs)
        return "模型总结"
    monkeypatch.setattr("app.services.analyze_service.analyze_color_with_qwen", _mock_qwen)
    original = [_region("r1", 20, 40, 40, 60.0, "主色", "#AA5533"), _region("r2", 180, 30, 60, 40.0, "辅助", "#55AABB")]
    adjusted = [_region("r1", 30, 50, 45, 60.0, "主色", "#BB6644"), _region("r2", 175, 35, 58, 40.0, "辅助", "#5599BB")]
    resp = client.post("/analyze", json={"original_color_regions": original, "adjusted_color_regions": adjusted, "before_image_url": str(before), "after_image_url": str(after)})
    body = resp.json()
    assert resp.status_code == 200
    assert body["fallback_used"] is False
    assert body["learning_explanation"] == "模型总结"
    assert body["model_markdown"] == "模型总结"
    assert captured["before_image_path"] == str(before.resolve())
    assert captured["after_image_path"] == str(after.resolve())


def test_analyze_invalid_before_image_path():
    original = [_region("r1", 20, 40, 40, 60.0, "主色", "#AA5533")]
    adjusted = [_region("r1", 30, 50, 45, 60.0, "主色", "#BB6644")]
    resp = client.post("/analyze", json={"original_color_regions": original, "adjusted_color_regions": adjusted, "before_image_url": "static/uploads/not-found.png", "after_image_url": "static/uploads/not-found2.png"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "error"


def test_analyze_rejects_path_traversal(tmp_path):
    before = tmp_path / "before.png"; _create_test_image(before)
    original = [_region("r1", 20, 40, 40, 60.0, "主色", "#AA5533")]
    adjusted = [_region("r1", 30, 50, 45, 60.0, "主色", "#BB6644")]
    resp = client.post("/analyze", json={"original_color_regions": original, "adjusted_color_regions": adjusted, "before_image_url": "../secret.png", "after_image_url": str(before)})
    assert resp.status_code == 200
    assert "path traversal" in resp.json()["message"]


def test_analyze_missing_static_path_returns_error(tmp_path):
    before = tmp_path / "before.png"; _create_test_image(before)
    original = [_region("r1", 20, 40, 40, 60.0, "主色", "#AA5533")]
    adjusted = [_region("r1", 30, 50, 45, 60.0, "主色", "#BB6644")]
    resp = client.post("/analyze", json={"original_color_regions": original, "adjusted_color_regions": adjusted, "before_image_url": str(before), "after_image_url": "/static/uploads/not-found.png"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "error"


def test_analyze_invalid_after_image_path(tmp_path):
    before = tmp_path / "before.png"; _create_test_image(before)
    original = [_region("r1", 20, 40, 40, 60.0, "主色", "#AA5533")]
    adjusted = [_region("r1", 30, 50, 45, 60.0, "主色", "#BB6644")]
    resp = client.post("/analyze", json={"original_color_regions": original, "adjusted_color_regions": adjusted, "before_image_url": str(before), "after_image_url": "static/uploads/not-found2.png"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "error"


def test_analyze_rejects_remote_http_image_url(tmp_path):
    before = tmp_path / "before.png"; _create_test_image(before)
    original = [_region("r1", 20, 40, 40, 60.0, "主色", "#AA5533")]
    adjusted = [_region("r1", 30, 50, 45, 60.0, "主色", "#BB6644")]
    resp = client.post("/analyze", json={"original_color_regions": original, "adjusted_color_regions": adjusted, "before_image_url": "https://example.com/assets/before.png", "after_image_url": str(before)})
    assert resp.status_code == 200
    assert "only this service static URL path" in resp.json()["message"]


def test_experiment_not_use_legacy_analysis_fields():
    resp = client.get('/experiment')
    assert resp.status_code == 200
    assert 'visual_feeling' not in resp.text
    assert 'ai_explanation' not in resp.text
    assert 'next_step' not in resp.text


def test_analyze_accepts_static_path_and_fallback(monkeypatch):
    test_dir = Path("static/outputs/test-analyze-runtime")
    test_dir.mkdir(parents=True, exist_ok=True)
    before = test_dir / "before.png"
    after = test_dir / "after.png"
    _create_test_image(before)
    _create_test_image(after)
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    original = [_region("r1", 20, 40, 40, 60.0, "主色", "#AA5533"), _region("r2", 180, 30, 60, 40.0, "辅助", "#55AABB")]
    adjusted = [_region("r1", 30, 50, 45, 60.0, "主色", "#BB6644"), _region("r2", 175, 35, 58, 40.0, "辅助", "#5599BB")]
    try:
        resp = client.post(
            "/analyze",
            json={
                "original_color_regions": original,
                "adjusted_color_regions": adjusted,
                "before_image_url": "/static/outputs/test-analyze-runtime/before.png",
                "after_image_url": "/static/outputs/test-analyze-runtime/after.png",
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "success"
        assert body["fallback_used"] is True
    finally:
        if before.exists():
            before.unlink()
        if after.exists():
            after.unlink()
        if test_dir.exists():
            test_dir.rmdir()


def test_analyze_without_dashscope_key_fallback(tmp_path, monkeypatch):
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    original = [_region("main", 10, 40, 45, 50.0, "主色", "#AA5544")]
    adjusted = [_region("main", 14, 55, 52, 50.0, "主色", "#CC6655")]
    before = tmp_path / "before3.png"
    after = tmp_path / "after3.png"
    _create_test_image(before)
    _create_test_image(after)
    payload = {"original_color_regions": original, "adjusted_color_regions": adjusted, "before_image_url": str(before), "after_image_url": str(after)}
    resp = client.post("/analyze", json=payload)
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "success"
    assert body["fallback_used"] is True
    assert body["learning_explanation"]


def test_analyze_qwen_error_graceful_fallback(tmp_path, monkeypatch):
    monkeypatch.setenv("DASHSCOPE_API_KEY", "fake-key")

    def _boom(*args, **kwargs):
        raise RuntimeError("upstream failed")

    monkeypatch.setattr("app.services.analyze_service.analyze_color_with_qwen", _boom)

    original = [_region("main", 10, 40, 45, 50.0, "主色", "#AA5544")]
    adjusted = [_region("main", 12, 60, 57, 50.0, "主色", "#CC6655")]
    before = tmp_path / "before4.png"
    after = tmp_path / "after4.png"
    _create_test_image(before)
    _create_test_image(after)

    payload = {"original_color_regions": original, "adjusted_color_regions": adjusted, "before_image_url": str(before), "after_image_url": str(after)}
    resp = client.post("/analyze", json=payload)
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "success"
    assert body["fallback_used"] is True
    assert body["model_markdown"] is None
    assert body["model_error"] == "upstream failed"


def test_compare_color_regions_hsl_is_dict():
    original = [_region("r1", 20, 40, 40, 60.0, "主色", "#AA5533")]
    adjusted = [_region("r1", 30, 50, 45, 60.0, "主色", "#BB6644")]
    from app.schemas.request_models import ColorRegionModel
    o = [ColorRegionModel(**x) for x in original]
    a = [ColorRegionModel(**x) for x in adjusted]
    changes, _ = compare_color_regions(o, a)
    assert isinstance(changes[0]["before_hsl"], dict)
    assert isinstance(changes[0]["after_hsl"], dict)

def test_layers_decompose_and_compose(tmp_path):
    image_path = tmp_path / 'layer-test.png'
    _create_test_image(image_path)
    d = client.post('/layers/decompose', json={'image_url': str(image_path), 'max_layers': 4})
    assert d.status_code == 200
    db = d.json()
    assert db['status'] == 'success' and db['image_id'] and isinstance(db['layers'], list) and db['canvas']
    assert 'fallback_used' in db
    layers = db['layers']
    c = client.post('/layers/compose', json={'image_id': db['image_id'], 'background_url': db['background_url'], 'layers': [{
        'id': l['id'], 'layer_url': l['layer_url'], 'x': l['transform']['x'], 'y': l['transform']['y'], 'scale_x': 1, 'scale_y': 1,
        'rotation': 0, 'flip_x': False, 'flip_y': False, 'visible': True, 'opacity': 1, 'z_index': i
    } for i,l in enumerate(reversed(layers),1)], 'operations':[{'type':'bring_to_front','layer_id':layers[0]['id'],'description':'置于顶层'}]})
    assert c.status_code == 200
    cb = c.json()
    assert cb['after_image_url'].startswith('/static/outputs/')


def test_composition_analyze_fallback():
    r = client.post('/composition/analyze', json={
        'before_image_url': '/static/uploads/a.png',
        'after_image_url': '/static/uploads/b.png',
        'layers_before': [], 'layers_after': [],
        'operations': [{'type':'send_to_back','layer_id':'layer-1','description':'下移'}],
        'user_goal': '用于形式构成课程实验'
    })
    assert r.status_code == 200
    b = r.json()
    assert b['fallback_used'] is True

def test_experiment_color_full_ui_keywords():
    resp = client.get('/experiment')
    txt = resp.text
    for kw in ['原图 canvas', '预览 canvas', 'H:', '保存该色块调整 /recolor', '生成色彩反馈 /analyze']:
        assert kw in txt


def test_decompose_layer_is_cropped_not_vertical_strip(tmp_path):
    image_path = tmp_path / 'decompose.png'
    _create_test_image(image_path)
    body = client.post('/layers/decompose', json={'image_url': str(image_path), 'max_layers': 6}).json()
    assert body['status'] == 'success'
    assert body['layers']
    for layer in body['layers']:
        lp = Path(layer['layer_url'].replace('/static/', 'static/'))
        im = Image.open(lp)
        bw, bh = layer['bbox']['width'], layer['bbox']['height']
        assert abs(im.width - bw) <= 2 and abs(im.height - bh) <= 2


def test_compose_respects_z_index(tmp_path):
    img = Image.new('RGBA', (60, 60), (255, 255, 255, 255))
    bg_path = tmp_path / 'bg.png'; img.save(bg_path)
    red = Image.new('RGBA', (30, 30), (255, 0, 0, 255)); redp = tmp_path / 'r.png'; red.save(redp)
    blue = Image.new('RGBA', (30, 30), (0, 0, 255, 255)); bluep = tmp_path / 'b.png'; blue.save(bluep)
    payload = {'image_id': 'ztest', 'background_url': str(bg_path), 'layers': [
        {'id': 'a', 'layer_url': str(redp), 'x': 10, 'y': 10, 'scale_x': 1, 'scale_y': 1, 'rotation': 0, 'flip_x': False, 'flip_y': False, 'visible': True, 'opacity': 1, 'z_index': 1},
        {'id': 'b', 'layer_url': str(bluep), 'x': 10, 'y': 10, 'scale_x': 1, 'scale_y': 1, 'rotation': 0, 'flip_x': False, 'flip_y': False, 'visible': True, 'opacity': 1, 'z_index': 2},
    ], 'operations': []}
    out = client.post('/layers/compose', json=payload).json()
    im = Image.open(Path(out['after_image_url'].replace('/static/', 'static/')))
    assert im.getpixel((20, 20))[2] > 200


def test_experiment_has_context_menu_and_transform_ops_keywords():
    txt = client.get('/experiment').text
    for kw in ['置于顶层', '置于底层', '上移一层', '下移一层', '水平镜像', '垂直镜像', '隐藏图层', '删除图层', '重置该元素', 'transformend', "'scale'", "'rotate'"]:
        assert kw in txt


def test_composition_analyze_fallback_without_api_key(tmp_path, monkeypatch):
    before = tmp_path / 'before.png'; after = tmp_path / 'after.png'
    _create_test_image(before); _create_test_image(after)
    monkeypatch.delenv('DASHSCOPE_API_KEY', raising=False)
    payload = {'before_image_url': str(before), 'after_image_url': str(after), 'layers_before': [], 'layers_after': [], 'operations': [], 'user_goal': 'x'}
    body = client.post('/composition/analyze', json=payload).json()
    assert body['status'] == 'success' and body['fallback_used'] is True


def test_composition_analyze_qwen_uses_image_url_message(tmp_path, monkeypatch):
    before = tmp_path / 'before.png'; after = tmp_path / 'after.png'
    _create_test_image(before); _create_test_image(after)
    monkeypatch.setenv('DASHSCOPE_API_KEY', 'x')
    called = {}
    def _mock(**kwargs):
        called.update(kwargs)
        return '### 总体判断\nok'
    monkeypatch.setattr('app.services.composition_analyze_service.analyze_composition_with_qwen', _mock)
    payload = {'before_image_url': str(before), 'after_image_url': str(after), 'layers_before': [], 'layers_after': [], 'operations': [{'type':'move','layer_id':'l1','description':'move'}], 'user_goal': 'x'}
    body = client.post('/composition/analyze', json=payload).json()
    assert body.get('status') == 'success'
    assert called.get('before_image_url') == str(before)


def test_layers_decompose_resizes_and_generates_cropped_layers(tmp_path):
    image_path = tmp_path / "large-layer-test.png"
    img = Image.new("RGB", (2400, 1800), "white")
    draw = ImageDraw.Draw(img)
    draw.rectangle((0, 0, 700, 900), fill=(220, 30, 30))
    draw.rectangle((900, 300, 1600, 1200), fill=(30, 160, 220))
    draw.rectangle((1700, 1000, 2300, 1700), fill=(50, 190, 80))
    img.save(image_path)

    resp = client.post("/layers/decompose", json={"image_url": str(image_path), "max_layers": 6})
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "success"
    assert body["fallback_used"] is True
    assert "近似图层拆解" in body["message"]

    canvas_w = body["canvas"]["width"]
    canvas_h = body["canvas"]["height"]
    assert max(canvas_w, canvas_h) <= 1024
    assert canvas_w * canvas_h <= 1024 * 1024

    processed = Path(body["processed_original_url"].replace("/static/", "static/"))
    assert processed.exists()

    has_cropped_layer = False
    for layer in body["layers"]:
        layer_path = Path(layer["layer_url"].replace("/static/", "static/"))
        assert layer_path.exists()
        lw, lh = Image.open(layer_path).size
        bbox = layer["bbox"]
        assert lw <= bbox["width"]
        assert lh <= bbox["height"]
        if lw < canvas_w or lh < canvas_h:
            has_cropped_layer = True
    assert has_cropped_layer


def test_layers_compose_with_cropped_layers(tmp_path):
    image_path = tmp_path / "compose-layer-test.png"
    _create_test_image(image_path)

    decomp = client.post("/layers/decompose", json={"image_url": str(image_path), "max_layers": 4}).json()
    assert decomp["status"] == "success"
    assert decomp["layers"]

    layer = decomp["layers"][0]
    compose_payload = {
        "image_id": decomp["image_id"],
        "background_url": decomp["background_url"],
        "layers": [{
            "id": layer["id"],
            "layer_url": layer["layer_url"],
            "x": layer["bbox"]["x"],
            "y": layer["bbox"]["y"],
            "scale_x": 1.0,
            "scale_y": 1.0,
            "rotation": 0,
            "flip_x": False,
            "flip_y": False,
            "visible": True,
            "opacity": 1.0,
            "z_index": 1,
        }],
        "operations": [{"type": "place", "layer_id": layer["id"], "description": "place test layer"}],
    }
    composed = client.post("/layers/compose", json=compose_payload)
    assert composed.status_code == 200
    data = composed.json()
    assert data["status"] == "success"
    out = Path(data["after_image_url"].replace("/static/", "static/"))
    assert out.exists()
    assert Image.open(out).size == (decomp["canvas"]["width"], decomp["canvas"]["height"])
