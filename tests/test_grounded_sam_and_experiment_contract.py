from app.services.replicate_segment_service import ReplicateSegmentService
from app.services.layer_service import LayerService
from app.main import app
from fastapi.testclient import TestClient
from PIL import Image
import pytest
import sys
import types

client = TestClient(app)


def test_grounded_sam_list_output_prefers_third_mask():
    output = [
        "https://example.com/annotated_picture_mask.jpg",
        "https://example.com/neg_annotated_picture_mask.jpg",
        "https://example.com/mask.jpg",
        "https://example.com/inverted_mask.jpg",
    ]
    parsed = ReplicateSegmentService.parse_grounded_sam_output(output)
    assert parsed["mask_url"].endswith("/mask.jpg")


def test_mask_coverage_invalid_thresholds():
    small = Image.new("L", (100, 100), 0)
    small.putpixel((0, 0), 255)
    cov_small = LayerService._mask_coverage(small)
    assert cov_small < 0.005

    large = Image.new("L", (100, 100), 255)
    cov_large = LayerService._mask_coverage(large)
    assert cov_large > 0.85


def test_experiment_template_has_error_gate_and_empty_layers_gate():
    html = client.get('/experiment').text
    assert "b.status!=='success'||!b.layers||b.layers.length===0" in html
    assert "showExtractDebug(b)" in html


def test_build_replicate_model_ref_rules(monkeypatch):
    full_version = "a" * 64
    monkeypatch.setenv("REPLICATE_GROUNDED_SAM_MODEL", "schananas/grounded_sam")
    monkeypatch.setenv("REPLICATE_GROUNDED_SAM_VERSION", full_version)
    model_ref, model, version = ReplicateSegmentService.build_replicate_model_ref()
    assert model_ref == f"schananas/grounded_sam:{full_version}"
    assert model == "schananas/grounded_sam"
    assert version == full_version

    monkeypatch.setenv("REPLICATE_GROUNDED_SAM_MODEL", f"schananas/grounded_sam:{full_version}")
    monkeypatch.delenv("REPLICATE_GROUNDED_SAM_VERSION", raising=False)
    model_ref, model, version = ReplicateSegmentService.build_replicate_model_ref()
    assert model_ref == f"schananas/grounded_sam:{full_version}"
    assert model == "schananas/grounded_sam"
    assert version == full_version

    monkeypatch.setenv("REPLICATE_GROUNDED_SAM_MODEL", "https://replicate.com/schananas/grounded_sam")
    with pytest.raises(ValueError, match="owner/model"):
        ReplicateSegmentService.build_replicate_model_ref()

    monkeypatch.setenv("REPLICATE_GROUNDED_SAM_MODEL", "schananas/grounded_sam")
    monkeypatch.setenv("REPLICATE_GROUNDED_SAM_VERSION", "ee871c19")
    with pytest.raises(ValueError, match="64-character"):
        ReplicateSegmentService.build_replicate_model_ref()

    monkeypatch.delenv("REPLICATE_GROUNDED_SAM_VERSION", raising=False)
    with pytest.raises(ValueError, match="requires REPLICATE_GROUNDED_SAM_VERSION"):
        ReplicateSegmentService.build_replicate_model_ref()


def test_grounded_sam_input_uses_mask_prompt(monkeypatch, tmp_path):
    image_path = tmp_path / "img.png"
    Image.new("RGBA", (8, 8), (255, 255, 255, 255)).save(image_path)
    monkeypatch.setenv("REPLICATE_GROUNDED_SAM_MODEL", "acme/model:1" + "a" * 63)
    monkeypatch.setenv("REPLICATE_API_TOKEN", "secret-token")

    captured = {}

    class FakeClient:
        def __init__(self, api_token=None):
            captured["api_token"] = api_token
        def run(self, model_ref, input):
            captured["model_ref"] = model_ref
            captured["input"] = input
            return ["https://example.com/annotated_picture_mask.jpg", "https://example.com/neg_annotated_picture_mask.jpg", "https://example.com/mask.jpg"]

    monkeypatch.setitem(sys.modules, "replicate", types.SimpleNamespace(Client=FakeClient))
    buf = __import__("io").BytesIO()
    Image.new("L", (8, 8), 255).save(buf, format="PNG")
    png_bytes = buf.getvalue()
    monkeypatch.setattr(
        "app.services.replicate_segment_service.httpx.get",
        lambda *args, **kwargs: type("Resp", (), {"content": png_bytes, "raise_for_status": lambda self: None})(),
    )

    masks = ReplicateSegmentService.segment_objects(str(image_path), [{"name": "cat", "label_en": "cat"}])
    assert len(masks) == 1

    assert "mask_prompt" in captured["input"]
    assert "text_prompt" not in captured["input"]


def test_extract_error_exposes_detail_without_token(tmp_path, monkeypatch):
    image_path = tmp_path / "extract-error.png"
    Image.new("RGBA", (12, 12), (255, 255, 255, 255)).save(image_path)
    monkeypatch.setenv("OBJECT_SEGMENT_PROVIDER", "replicate_grounded_sam")
    monkeypatch.setenv("REPLICATE_API_TOKEN", "very-secret-token")
    monkeypatch.setenv("REPLICATE_GROUNDED_SAM_MODEL", "schananas/grounded_sam")
    monkeypatch.setenv("REPLICATE_GROUNDED_SAM_VERSION", "b" * 64)

    def _raise(*args, **kwargs):
        raise RuntimeError("ReplicateError status: 404 detail: The requested resource could not be found.")

    monkeypatch.setattr("app.services.layer_service.ReplicateSegmentService.segment_objects", _raise)
    body = client.post("/layers/extract-by-objects", json={"image_url": str(image_path), "objects": [{"id": "object-1", "name": "猫", "label_en": "cat"}], "need_inpainting": False}).json()
    assert body["status"] == "error"
    assert "404" in body["message"]
    assert "404" in body["segmentation_debug"]["error_message"]
    assert "very-secret-token" not in str(body)
