from __future__ import annotations
import json
import os
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
    def debug_color_region_layers(img: Image.Image, clusters: int) -> list[np.ndarray]:
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
    def _prepare_image(image_url: str) -> tuple[Image.Image, str, Path, str]:
        src = Image.open(LayerService._path_from_static(image_url)).convert('RGBA')
        img = resize_for_processing(src, max_side=1024)
        if img.width * img.height > 1024 * 1024:
            img = resize_for_processing(img, max_side=int((1024 * 1024) ** 0.5))
        image_id = f"img-{uuid4().hex[:12]}"
        out = Path('static/outputs') / image_id / 'layers'
        out.mkdir(parents=True, exist_ok=True)
        processed_original_url = f"/static/outputs/{image_id}/layers/processed_original.png"
        img.save(out / 'processed_original.png')
        return img, image_id, out, processed_original_url

    @staticmethod
    def decompose(image_url: str, max_layers: int = 8) -> dict:
        img, image_id, out, processed_original_url = LayerService._prepare_image(image_url)
        provider = os.getenv('LAYER_DECOMPOSE_PROVIDER', 'none').strip().lower()

        if provider == 'manual':
            msg = '当前为手动框选模式入口，请使用 /layers/manual-extract 进行临时图层提取。'
            resp = {
                'status': 'needs_model_config',
                'message': msg,
                'user_message': msg,
                'image_id': image_id,
                'fallback_used': True,
                'segmentation_method': 'manual',
                'inpainting_used': False,
                'inpainting_fallback_used': True,
                'model_required': True,
                'original_image_url': image_url,
                'processed_original_url': processed_original_url,
                'clean_background_url': processed_original_url,
                'canvas': {'width': img.width, 'height': img.height},
                'background_url': processed_original_url,
                'layers': [],
            }
        elif provider in {'external', 'sam'}:
            msg = '已配置 provider，但当前版本未实现外部分割服务调用，请接入 masks/layers API。'
            resp = {
                'status': 'needs_model_config', 'message': msg, 'user_message': msg,
                'image_id': image_id, 'fallback_used': True, 'segmentation_method': provider,
                'inpainting_used': False, 'inpainting_fallback_used': True, 'model_required': True,
                'original_image_url': image_url, 'processed_original_url': processed_original_url,
                'clean_background_url': processed_original_url, 'canvas': {'width': img.width, 'height': img.height},
                'background_url': processed_original_url, 'layers': [],
            }
        else:
            msg = '当前未配置物体级图层拆解模型。构图实验需要 SAM / Qwen-Image-Layered / inpainting 服务支持。'
            resp = {
                'status': 'needs_model_config', 'message': msg, 'user_message': msg,
                'image_id': image_id, 'fallback_used': True, 'segmentation_method': 'none',
                'inpainting_used': False, 'inpainting_fallback_used': True, 'model_required': True,
                'original_image_url': image_url, 'processed_original_url': processed_original_url,
                'clean_background_url': None, 'canvas': {'width': img.width, 'height': img.height},
                'background_url': processed_original_url, 'layers': [],
            }
        (Path('static/outputs') / image_id / 'layer_decompose_result.json').write_text(json.dumps(resp, ensure_ascii=False, indent=2), encoding='utf-8')
        return resp

    @staticmethod
    def manual_extract(image_url: str, bbox: dict) -> dict:
        img, image_id, out, processed_original_url = LayerService._prepare_image(image_url)
        x = max(0, int(bbox.get('x', 0))); y = max(0, int(bbox.get('y', 0)))
        w = max(1, int(bbox.get('width', 1))); h = max(1, int(bbox.get('height', 1)))
        x1 = min(img.width, x + w); y1 = min(img.height, y + h)
        crop = img.crop((x, y, x1, y1))
        lid='layer-1'
        crop.save(out / f'{lid}.png')
        mask = Image.new('L', (x1-x, y1-y), 255); mask.save(out / f'{lid}-mask.png')
        layer={
            'id': lid,'name':'手动框选元素 1','layer_url': f'/static/outputs/{image_id}/layers/{lid}.png','mask_url': f'/static/outputs/{image_id}/layers/{lid}-mask.png',
            'bbox': {'x':x,'y':y,'width':x1-x,'height':y1-y},'confidence': 1.0,'z_index':1,'visible':True,'opacity':1,
            'transform': {'x':x,'y':y,'scale_x':1,'scale_y':1,'rotation':0,'flip_x':False,'flip_y':False}
        }
        return {'status':'success','message':'当前为手动框选临时模式，未进行自动物体分割和背景修补','user_message':'当前为手动框选元素。','image_id':image_id,
                'fallback_used':True,'segmentation_method':'manual','inpainting_used':False,'inpainting_fallback_used':True,'model_required':False,
                'original_image_url':image_url,'processed_original_url':processed_original_url,'clean_background_url':processed_original_url,
                'canvas':{'width':img.width,'height':img.height},'background_url':processed_original_url,'layers':[layer]}

    @staticmethod
    def compose(payload: dict) -> dict:
        bg_url = payload.get('background_url')
        bg = Image.open(LayerService._path_from_static(bg_url)).convert('RGBA')
        image_id = payload['image_id']
        for l in sorted(payload['layers'], key=lambda x: x.get('z_index', 0)):
            if not l.get('visible', True):
                continue
            im = Image.open(LayerService._path_from_static(l['layer_url'])).convert('RGBA')
            sx = max(0.01, abs(float(l.get('scale_x', l.get('transform', {}).get('scale_x', 1))))); sy = max(0.01, abs(float(l.get('scale_y', l.get('transform', {}).get('scale_y', 1)))))
            if l.get('flip_x', l.get('transform', {}).get('flip_x', False)): im = ImageOps.mirror(im)
            if l.get('flip_y', l.get('transform', {}).get('flip_y', False)): im = ImageOps.flip(im)
            im = im.resize((max(1, int(im.width * sx)), max(1, int(im.height * sy))))
            rotation = float(l.get('rotation', l.get('transform', {}).get('rotation', 0)))
            if rotation: im = im.rotate(rotation, expand=True)
            opacity = float(l.get('opacity', 1))
            if opacity < 1:
                a = im.split()[-1].point(lambda p: int(p * opacity)); im.putalpha(a)
            x = int(l.get('x', l.get('transform', {}).get('x', 0))); y = int(l.get('y', l.get('transform', {}).get('y', 0)))
            bg.alpha_composite(im, (x, y))
        outdir = Path('static/outputs') / image_id; outdir.mkdir(parents=True, exist_ok=True)
        name = f"composition_{uuid4().hex[:8]}.png"; out = outdir / name; bg.save(out)
        summary = [op.get('description', '') for op in payload.get('operations', []) if op.get('description')]
        inferred_inpaint = payload.get('inpainting_used', True)
        if str(bg_url).endswith('/layers/processed_original.png'):
            inferred_inpaint = False
        warning = None
        if inferred_inpaint is False:
            warning = '当前未进行背景修补，移动元素后原位置可能仍保留原图内容。'
        return {'status':'success','message':'构图实验图已生成','after_image_url':f'/static/outputs/{image_id}/{name}','composition_result_url':f'/static/outputs/{image_id}/composition_result.json','operations_summary':summary,'inpainting_used':inferred_inpaint,'warning':warning}
