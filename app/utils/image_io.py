from __future__ import annotations

from io import BytesIO
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import urlopen

from PIL import Image


OUTPUT_DIR = Path("static/outputs")


def is_remote_url(path_or_url: str) -> bool:
    parsed = urlparse(path_or_url)
    return parsed.scheme in {"http", "https"}


def load_image(path_or_url: str) -> Image.Image:
    if is_remote_url(path_or_url):
        with urlopen(path_or_url, timeout=10) as resp:
            data = resp.read()
        image = Image.open(BytesIO(data))
    else:
        image = Image.open(Path(path_or_url).expanduser())
    return image.convert("RGBA")


def resize_for_processing(image: Image.Image, max_side: int = 512) -> Image.Image:
    width, height = image.size
    longest = max(width, height)
    if longest <= max_side:
        return image
    scale = max_side / longest
    new_size = (max(1, int(width * scale)), max(1, int(height * scale)))
    return image.resize(new_size, Image.Resampling.LANCZOS)


def ensure_output_dir() -> Path:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    return OUTPUT_DIR


def save_image(image: Image.Image, filename: str) -> str:
    out_dir = ensure_output_dir()
    path = out_dir / filename
    image.save(path)
    return f"/static/outputs/{filename}"
