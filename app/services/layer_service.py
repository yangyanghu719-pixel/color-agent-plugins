from __future__ import annotations
import json
from pathlib import Path
from uuid import uuid4

import numpy as np
from PIL import Image, ImageOps

from app.utils.image_io import resize_for_processing


class LayerService:
    @staticmethod
    def _path_from_static(url: str) -> Path:
        if ".." in url:
            raise ValueError("invalid path")
        if url.startswith("http"):
            idx = url.find('/static/')
            if idx < 0:
                raise ValueError('only static path allowed')
            url = url[idx:]
        if url.startswith('/static/'):
            return Path('static') / url[len('/static/'):]
        if url.startswith('static/'):
            return Path(url)
        return Path(url)

    @staticmethod
    def _kmeans_masks(img: Image.Image, clusters: int) -> list[np.ndarray]:
        arr = np.array(img.convert('RGB'), dtype=np.float32)
        h, w, _ = arr.shape
        flat = arr.reshape(-1, 3)
        rng = np.random.default_rng(42)
        k = max(2, min(clusters, 8))
        centers = flat[rng.choice(flat.shape[0], size=k, replace=False)]
        for _ in range(12):
            dist = ((flat[:, None, :] - centers[None, :, :]) ** 2).sum(axis=2)
            labels = dist.argmin(axis=1)
            new_centers = centers.copy()
            for i in range(k):
                pts = flat[labels == i]
                if len(pts) > 0:
                    new_centers[i] = pts.mean(axis=0)
            if np.allclose(new_centers, centers, atol=1.0):
                break
            centers = new_centers
        masks = []
        for i in range(k):
            mask = (labels == i).reshape(h, w)
            if mask.sum() > (h * w * 0.01):
                masks.append(mask)
        return masks

    @staticmethod
    def _connected_components(mask: np.ndarray) -> list[dict]:
        h, w = mask.shape
        visited = np.zeros_like(mask, dtype=bool)
        comps: list[dict] = []
        neighbors = [(-1, 0), (1, 0), (0, -1), (0, 1)]
        for y in range(h):
            for x in range(w):
                if not mask[y, x] or visited[y, x]:
                    continue
                stack = [(x, y)]
                visited[y, x] = True
                xs, ys = [], []
                while stack:
                    cx, cy = stack.pop()
                    xs.append(cx)
                    ys.append(cy)
                    for dx, dy in neighbors:
                        nx, ny = cx + dx, cy + dy
                        if 0 <= nx < w and 0 <= ny < h and mask[ny, nx] and not visited[ny, nx]:
                            visited[ny, nx] = True
                            stack.append((nx, ny))
                x0, x1 = min(xs), max(xs)
                y0, y1 = min(ys), max(ys)
                area = len(xs)
                comps.append({"bbox": (x0, y0, x1 + 1, y1 + 1), "area": area})
        return comps

    @staticmethod
    def decompose(image_url: str, max_layers: int = 8) -> dict:
        src = Image.open(LayerService._path_from_static(image_url)).convert('RGBA')
        max_side = 1024
        max_pixels = 1024 * 1024
        img = resize_for_processing(src, max_side=max_side)
        if img.width * img.height > max_pixels:
            pixel_side = int(max_pixels ** 0.5)
            img = resize_for_processing(img, max_side=pixel_side)
        w, h = img.size
        image_id = f"img-{uuid4().hex[:12]}"
        out = Path('static/outputs') / image_id / 'layers'
        out.mkdir(parents=True, exist_ok=True)
        processed_original_path = out / 'processed_original.png'
        img.save(processed_original_path)
        bg = Image.new('RGBA', (w, h), (255, 255, 255, 255))
        bg.save(out / 'background.png')

        masks = LayerService._kmeans_masks(img, max_layers)
        layers = []
        lid = 1
        min_area = max(48, int(w * h * 0.004))
        rgba = np.array(img)
        for m in masks:
            for comp in LayerService._connected_components(m):
                if comp["area"] < min_area:
                    continue
                if comp["area"] > int(w * h * 0.95):
                    continue
                x0, y0, x1, y1 = comp["bbox"]
                local_mask = m[y0:y1, x0:x1]
                crop = rgba[y0:y1, x0:x1].copy()
                crop[:, :, 3] = np.where(local_mask, crop[:, :, 3], 0)
                layer_im = Image.fromarray(crop, mode='RGBA')
                mask_im = Image.fromarray((local_mask * 255).astype(np.uint8), mode='L')
                layer_id = f'layer-{lid}'
                lid += 1
                layer_im.save(out / f'{layer_id}.png')
                mask_im.save(out / f'{layer_id}-mask.png')
                layers.append({
                    "id": layer_id,
                    "name": f"元素 {len(layers)+1}",
                    "layer_url": f"/static/outputs/{image_id}/layers/{layer_id}.png",
                    "mask_url": f"/static/outputs/{image_id}/layers/{layer_id}-mask.png",
                    "mask_size": "cropped",
                    "bbox": {"x": x0, "y": y0, "width": x1 - x0, "height": y1 - y0},
                    "z_index": len(layers) + 1,
                    "visible": True,
                    "opacity": 1,
                    "transform": {"x": x0, "y": y0, "scale_x": 1, "scale_y": 1, "rotation": 0, "flip_x": False, "flip_y": False},
                })
                if len(layers) >= max_layers:
                    break
            if len(layers) >= max_layers:
                break

        resized_notice = "（图片过大，系统已自动压缩）" if (src.size != img.size) else ""
        resp = {"status": "success", "message": f"当前为近似图层拆解（轻量 fallback）{resized_notice}", "image_id": image_id, "fallback_used": True, "original_image_url": image_url, "processed_original_url": f"/static/outputs/{image_id}/layers/processed_original.png", "canvas": {"width": w, "height": h}, "background_url": f"/static/outputs/{image_id}/layers/background.png", "layers": layers}
        (Path('static/outputs') / image_id / 'layer_decompose_result.json').write_text(json.dumps(resp, ensure_ascii=False, indent=2), encoding='utf-8')
        return resp

    @staticmethod
    def compose(payload: dict) -> dict:
        bg = Image.open(LayerService._path_from_static(payload['background_url'])).convert('RGBA')
        image_id = payload['image_id']
        for l in sorted(payload['layers'], key=lambda x: x.get('z_index', 0)):
            if not l.get('visible', True):
                continue
            im = Image.open(LayerService._path_from_static(l['layer_url'])).convert('RGBA')
            sx = max(0.01, abs(float(l.get('scale_x', l.get('transform', {}).get('scale_x', 1)))))
            sy = max(0.01, abs(float(l.get('scale_y', l.get('transform', {}).get('scale_y', 1)))))
            if l.get('flip_x', l.get('transform', {}).get('flip_x', False)):
                im = ImageOps.mirror(im)
            if l.get('flip_y', l.get('transform', {}).get('flip_y', False)):
                im = ImageOps.flip(im)
            im = im.resize((max(1, int(im.width * sx)), max(1, int(im.height * sy))))
            rotation = float(l.get('rotation', l.get('transform', {}).get('rotation', 0)))
            if rotation:
                im = im.rotate(rotation, expand=True)
            opacity = float(l.get('opacity', 1))
            if opacity < 1:
                a = im.split()[-1].point(lambda p: int(p * opacity))
                im.putalpha(a)
            x = int(l.get('x', l.get('transform', {}).get('x', 0)))
            y = int(l.get('y', l.get('transform', {}).get('y', 0)))
            bg.alpha_composite(im, (x, y))
        outdir = Path('static/outputs') / image_id
        outdir.mkdir(parents=True, exist_ok=True)
        name = f"composition_{uuid4().hex[:8]}.png"
        out = outdir / name
        bg.save(out)
        summary = [op.get('description', '') for op in payload.get('operations', []) if op.get('description')]
        result = {"layers": payload.get('layers', []), "operations": payload.get('operations', []), "after_image_url": f"/static/outputs/{image_id}/{name}"}
        (outdir / 'composition_result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        return {"status": "success", "message": "构图实验图已生成", "after_image_url": f"/static/outputs/{image_id}/{name}", "composition_result_url": f"/static/outputs/{image_id}/composition_result.json", "operations_summary": summary}
