from app.services.replicate_segment_service import ReplicateSegmentService
from app.services.layer_service import LayerService
from app.main import app
from fastapi.testclient import TestClient
from PIL import Image

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
