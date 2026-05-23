from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

import numpy as np
from PIL import Image, ImageDraw, ImageFilter


@dataclass
class ExtractConfig:
    max_layers: int = 24
    min_area: int = 80


class ExtractError(ValueError):
    pass


class ElementExtractService:
    def __init__(self, static_dir: Path = Path("static")) -> None:
        self.static_dir = static_dir

    def _resolve_image_path(self, image_url: str) -> tuple[Path, str]:
        normalized = image_url.strip()
        if normalized.startswith("/static/"):
            rel = normalized[1:]
        elif normalized.startswith("static/"):
            rel = normalized
        else:
            raise ExtractError("image_url 必须是 static/... 或 /static/... 路径")

        rel_path = Path(rel)
        if any(part == ".." for part in rel_path.parts):
            raise ExtractError("image_url 包含非法路径")

        full_path = Path(rel)
        if not full_path.exists():
            raise ExtractError("图片不存在")

        return full_path, "/" + rel.replace("\\", "/")

    def _estimate_background(self, rgb: np.ndarray) -> np.ndarray:
        h, w, _ = rgb.shape
        edges = np.concatenate(
            [
                rgb[: max(1, h // 20), :, :].reshape(-1, 3),
                rgb[h - max(1, h // 20) :, :, :].reshape(-1, 3),
                rgb[:, : max(1, w // 20), :].reshape(-1, 3),
                rgb[:, w - max(1, w // 20) :, :].reshape(-1, 3),
            ],
            axis=0,
        )
        return np.median(edges, axis=0)

    def _rgb_to_hsv(self, rgb: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        x = rgb.astype(np.float32) / 255.0
        cmax = x.max(axis=-1)
        cmin = x.min(axis=-1)
        delta = cmax - cmin
        sat = np.where(cmax == 0, 0, delta / np.clip(cmax, 1e-6, None))
        val = cmax
        return cmax, sat, val

    def extract(self, image_url: str, cfg: ExtractConfig) -> dict:
        image_path, display_image_url = self._resolve_image_path(image_url)
        image_id = uuid4().hex[:12]
        out_dir = self.static_dir / "outputs" / image_id
        layers_dir = out_dir / "layers"
        layers_dir.mkdir(parents=True, exist_ok=True)

        rgb_img = Image.open(image_path).convert("RGB")
        rgb = np.array(rgb_img)
        h, w, _ = rgb.shape

        bg = self._estimate_background(rgb)
        diff = np.sqrt(((rgb.astype(np.float32) - bg.reshape(1, 1, 3)) ** 2).sum(axis=-1))
        _, sat, val = self._rgb_to_hsv(rgb)
        bg_sat = float(np.median(sat[: max(1, h // 20), :]))
        bg_val = float(np.median(val[: max(1, h // 20), :]))

        fg = (diff > 28) | (val < max(0.90, bg_val - 0.06)) | (sat > max(0.18, bg_sat + 0.08))
        fg_mask = (fg.astype(np.uint8)) * 255

        mask_img = Image.fromarray(fg_mask, mode="L")
        mask_img = mask_img.filter(ImageFilter.MedianFilter(size=3))
        arr = np.array(mask_img) > 0
        # tiny component suppression + neighborhood smooth
        kernel = np.ones((3, 3), dtype=np.uint8)
        padded = np.pad(arr.astype(np.uint8), 1)
        conv = sum(padded[i : i + h, j : j + w] for i in range(3) for j in range(3))
        arr = conv >= 2

        visited = np.zeros((h, w), dtype=bool)
        components: list[dict] = []

        for y in range(h):
            for x in range(w):
                if not arr[y, x] or visited[y, x]:
                    continue
                stack = [(y, x)]
                visited[y, x] = True
                pts = []
                while stack:
                    cy, cx = stack.pop()
                    pts.append((cy, cx))
                    for ny in range(max(0, cy - 1), min(h, cy + 2)):
                        for nx in range(max(0, cx - 1), min(w, cx + 2)):
                            if arr[ny, nx] and not visited[ny, nx]:
                                visited[ny, nx] = True
                                stack.append((ny, nx))
                area = len(pts)
                ys = [p[0] for p in pts]
                xs = [p[1] for p in pts]
                y0, y1 = min(ys), max(ys)
                x0, x1 = min(xs), max(xs)
                bw, bh = x1 - x0 + 1, y1 - y0 + 1
                components.append({"pts": pts, "area": area, "bbox": (x0, y0, bw, bh)})

        components.sort(key=lambda c: c["area"], reverse=True)
        large = [c for c in components if c["area"] >= cfg.min_area]
        small = [c for c in components if c["area"] < cfg.min_area]

        selected = large[: cfg.max_layers]
        leftover = small + large[cfg.max_layers :]

        layers = []
        full_rgba = np.dstack([rgb, np.full((h, w), 255, dtype=np.uint8)])

        def add_layer(mask: np.ndarray, name: str, layer_type: str):
            nonlocal layers
            ys, xs = np.where(mask)
            if len(xs) == 0:
                return
            x0, x1 = xs.min(), xs.max()
            y0, y1 = ys.min(), ys.max()
            bw, bh = x1 - x0 + 1, y1 - y0 + 1
            area = int(mask.sum())
            layer_id = f"layer_{len(layers)+1:03d}"

            alpha = (mask * 255).astype(np.uint8)
            rgba = full_rgba.copy()
            rgba[:, :, 3] = alpha
            crop = rgba[y0 : y1 + 1, x0 : x1 + 1, :]
            crop_mask = alpha[y0 : y1 + 1, x0 : x1 + 1]

            layer_img_name = f"{layer_id}.png"
            layer_mask_name = f"{layer_id}_mask.png"
            Image.fromarray(crop, mode="RGBA").save(layers_dir / layer_img_name)
            Image.fromarray(crop_mask, mode="L").save(layers_dir / layer_mask_name)

            coverage = area / float(w * h)
            layers.append(
                {
                    "id": layer_id,
                    "name": f"图元 {len(layers)+1}",
                    "type": layer_type,
                    "bbox": [int(x0), int(y0), int(bw), int(bh)],
                    "center": [round(float(x0 + bw / 2), 2), round(float(y0 + bh / 2), 2)],
                    "area": int(area),
                    "coverage": round(float(coverage), 6),
                    "image_url": f"/static/outputs/{image_id}/layers/{layer_img_name}",
                    "mask_url": f"/static/outputs/{image_id}/layers/{layer_mask_name}",
                    "z_index": len(layers) + 1,
                }
            )

        for comp in selected:
            x0, y0, bw, bh = comp["bbox"]
            density = comp["area"] / max(1, bw * bh)
            aspect = max(bw, bh) / max(1, min(bw, bh))
            if density < 0.2 and aspect > 3:
                ctype = "line_group"
            elif density > 0.65:
                ctype = "solid_shape"
            elif density > 0.35:
                ctype = "soft_texture"
            else:
                ctype = "unknown"
            m = np.zeros((h, w), dtype=np.uint8)
            for py, px in comp["pts"]:
                m[py, px] = 1
            add_layer(m.astype(bool), f"图元 {len(layers)+1}", ctype)

        if leftover:
            group_mask = np.zeros((h, w), dtype=np.uint8)
            line_mask = np.zeros((h, w), dtype=np.uint8)
            for comp in leftover:
                x0, y0, bw, bh = comp["bbox"]
                density = comp["area"] / max(1, bw * bh)
                aspect = max(bw, bh) / max(1, min(bw, bh))
                target = line_mask if (density < 0.22 and aspect > 3) else group_mask
                for py, px in comp["pts"]:
                    target[py, px] = 1
            if line_mask.any():
                add_layer(line_mask.astype(bool), "线条组", "line_group")
            if group_mask.any():
                add_layer(group_mask.astype(bool), "碎片组", "small_group")

        fg_cov = float(arr.sum() / max(1, w * h))

        debug_mask = (arr.astype(np.uint8) * 255)
        debug_mask_name = "debug_foreground_mask.png"
        Image.fromarray(debug_mask, mode="L").save(out_dir / debug_mask_name)

        overlay = rgb_img.copy().convert("RGBA")
        draw = ImageDraw.Draw(overlay)
        for idx, layer in enumerate(layers, start=1):
            x, y, bw, bh = layer["bbox"]
            color = (255, 0, 0, 180) if idx % 2 else (0, 120, 255, 180)
            draw.rectangle([x, y, x + bw, y + bh], outline=color, width=2)
            draw.text((x + 3, max(0, y - 14)), str(idx), fill=color)
        debug_overlay_name = "debug_overlay.png"
        overlay.save(out_dir / debug_overlay_name)

        return {
            "status": "success",
            "message": "元素提取完成",
            "image_url": display_image_url,
            "canvas_width": w,
            "canvas_height": h,
            "layer_count": len(layers),
            "layers": layers,
            "debug": {
                "background_rgb": [int(round(x)) for x in bg.tolist()],
                "foreground_coverage": round(fg_cov, 6),
                "debug_mask_url": f"/static/outputs/{image_id}/{debug_mask_name}",
                "debug_overlay_url": f"/static/outputs/{image_id}/{debug_overlay_name}",
                "warnings": [],
            },
        }
