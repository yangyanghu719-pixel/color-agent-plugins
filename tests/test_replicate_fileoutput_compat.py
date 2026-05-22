from pathlib import Path

from PIL import Image

from app.services.replicate_segment_service import ReplicateSegmentService


def _png_bytes() -> bytes:
    buf = __import__("io").BytesIO()
    Image.new("L", (4, 4), 255).save(buf, format="PNG")
    return buf.getvalue()


def test_requirements_include_replicate_dependency():
    requirements_text = Path("requirements.txt").read_text(encoding="utf-8")
    assert "replicate>=1.0,<2.0" in requirements_text


def test_parse_grounded_sam_output_supports_fileoutput_read_only():
    class FileOutputLike:
        def read(self):
            return _png_bytes()

    parsed = ReplicateSegmentService.parse_grounded_sam_output(FileOutputLike())
    assert "mask_image" in parsed
    assert parsed["mask_image"].mode == "L"


def test_parse_grounded_sam_output_prefers_read_over_url_when_both_present():
    class FileOutputLike:
        url = "https://example.com/mask.jpg"

        def read(self):
            return _png_bytes()

    parsed = ReplicateSegmentService.parse_grounded_sam_output(FileOutputLike())
    assert "mask_image" in parsed
    assert "mask_url" not in parsed
    assert parsed["mask_image"].mode == "L"


def test_grounded_sam_list_third_item_fileoutput_like_returns_mask_image():
    class FileOutputLike:
        def read(self):
            return _png_bytes()

    output = [
        "https://example.com/annotated_picture_mask.jpg",
        "https://example.com/neg_annotated_picture_mask.jpg",
        FileOutputLike(),
        "https://example.com/inverted_mask.jpg",
    ]
    parsed = ReplicateSegmentService.parse_grounded_sam_output(output)
    assert "mask_image" in parsed
    assert parsed["mask_image"].mode == "L"
