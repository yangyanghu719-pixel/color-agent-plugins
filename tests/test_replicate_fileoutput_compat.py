from io import BytesIO

from PIL import Image

from app.services.replicate_segment_service import ReplicateSegmentService


def _png_bytes() -> bytes:
    buf = BytesIO()
    Image.new("L", (2, 2), 255).save(buf, format="PNG")
    return buf.getvalue()


def test_fileoutput_like_read_bytes_preferred_over_url():
    class FileOutputLike:
        url = "https://example.com/mask.png"

        def read(self):
            return _png_bytes()

    parsed = ReplicateSegmentService.parse_grounded_sam_output(FileOutputLike())
    assert parsed.get("mask_image") is not None
    assert parsed.get("mask_url") is None


def test_fileoutput_like_read_failure_falls_back_to_url():
    class FileOutputLike:
        url = "https://example.com/mask.png"

        def read(self):
            raise RuntimeError("stream consumed")

    parsed = ReplicateSegmentService.parse_grounded_sam_output(FileOutputLike())
    assert parsed == {"mask_url": "https://example.com/mask.png"}


def test_load_mask_from_parsed_prefers_mask_image(monkeypatch):
    img = Image.new("L", (1, 1), 255)

    def _boom(*args, **kwargs):
        raise AssertionError("httpx.get should not be called when mask_image exists")

    monkeypatch.setattr("app.services.replicate_segment_service.httpx.get", _boom)
    loaded = ReplicateSegmentService._load_mask_from_parsed(
        {"mask_image": img, "mask_url": "https://example.com/mask.png"}
    )
    assert loaded.mode == "L"
    assert loaded.size == (1, 1)
