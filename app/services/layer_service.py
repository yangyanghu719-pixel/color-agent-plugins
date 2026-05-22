from __future__ import annotations
import base64
import json
import os
from io import BytesIO
from pathlib import Path
from uuid import uuid4

import httpx
from PIL import Image, ImageOps

from app.services.qwen_client import detect_objects_with_qwen
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
    def _prepare_image(image_url: str) -> tuple[Image.Image, str, Path, str]:
        src = Image.open(LayerService._path_from_static(image_url)).convert('RGBA')
        img = resize_for_processing(src, max_side=1024)
        image_id = f"img-{uuid4().hex[:12]}"
        out = Path('static/outputs') / image_id / 'layers'
        out.mkdir(parents=True, exist_ok=True)
        processed_original_url = f"/static/outputs/{image_id}/layers/processed_original.png"
        img.save(out / 'processed_original.png')
        return img, image_id, out, processed_original_url

    @staticmethod
    def detect_composition_objects(image_url: str) -> dict:
        img, image_id, _, _ = LayerService._prepare_image(image_url)
        if not os.getenv("DASHSCOPE_API_KEY"):
            return {"status":"success","message":"对象识别模型未配置","image_id":image_id,"objects":[],"model_used":None,"fallback_used":True,"model_error":"DASHSCOPE_API_KEY is not configured"}
        try:
            path = LayerService._path_from_static(image_url)
            rows = detect_objects_with_qwen(str(path))
            objects = []
            for i, r in enumerate(rows, start=1):
                objects.append({"id":f"object-{i}","name":r.get("name") or f"对象{i}","label_en":r.get("label_en"),"description":r.get("description"),"confidence":r.get("confidence"),"selected":True})
            return {"status":"success","message":"已识别画面主要对象","image_id":image_id,"objects":objects,"model_used":"qwen-vl","fallback_used":False,"model_error":None}
        except Exception as e:
            return {"status":"success","message":"对象识别模型未配置","image_id":image_id,"objects":[],"model_used":"qwen-vl","fallback_used":True,"model_error":str(e)}

    @staticmethod
    def _image_to_base64(img: Image.Image) -> str:
        buf = BytesIO(); img.save(buf, format="PNG")
        return base64.b64encode(buf.getvalue()).decode()

    @staticmethod
    def _decode_base64_image(data: str) -> Image.Image:
        return Image.open(BytesIO(base64.b64decode(data))).convert("RGBA")

    @staticmethod
    def extract_by_objects(image_url: str, objects: list[dict], need_inpainting: bool = True) -> dict:
        img, image_id, out, processed_original_url = LayerService._prepare_image(image_url)
        provider = os.getenv("OBJECT_SEGMENT_PROVIDER", "none").strip().lower()
        if provider != "external":
            msg = "物体级图层拆解模型未配置。物体分割 / 背景修补 API 未配置。构图实验需要接入 SAM / Qwen-Image-Layered / Inpainting 服务。"
            return {"status":"needs_model_config","message":msg,"image_id":image_id,"fallback_used":True,"segmentation_method":"none","inpainting_used":False,"inpainting_fallback_used":True,"model_required":True,"original_image_url":image_url,"processed_original_url":processed_original_url,"clean_background_url":processed_original_url,"background_url":processed_original_url,"canvas":{"width":img.width,"height":img.height},"layers":[]}

        seg_url = os.getenv("OBJECT_SEGMENT_API_URL", "")
        seg_key = os.getenv("OBJECT_SEGMENT_API_KEY", "")
        payload = {"image_base64": LayerService._image_to_base64(img), "objects": objects, "return_mask": True, "return_bbox": True, "return_layer": False}
        headers = {"Content-Type": "application/json", "Authorization": f"Bearer {seg_key}"}
        with httpx.Client(timeout=60) as client:
            resp = client.post(seg_url, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()

        raw_layers = data.get("layers") or data.get("objects") or []
        layers = []
        combined = Image.new("L", img.size, 0)
        for i, item in enumerate(raw_layers, start=1):
            lid = f"layer-{i}"
            bbox = item.get("bbox") or {"x":0,"y":0,"width":img.width,"height":img.height}
            m = LayerService._decode_base64_image(item.get("mask_base64")).convert("L")
            if m.size != img.size:
                m = m.resize(img.size)
            combined = Image.composite(Image.new("L", img.size, 255), combined, m)
            mask_path = out / f"{lid}-mask.png"; m.save(mask_path)
            if item.get("layer_base64"):
                l_img = LayerService._decode_base64_image(item["layer_base64"])
            else:
                rgba = img.copy(); rgba.putalpha(m)
                x,y,w,h = int(bbox['x']), int(bbox['y']), int(bbox['width']), int(bbox['height'])
                l_img = rgba.crop((x,y,x+w,y+h))
            layer_path = out / f"{lid}.png"; l_img.save(layer_path)
            layers.append({"id":lid,"object_id":item.get("object_id") or item.get("id"),"name":item.get("name", f"对象{i}"),"label_en":item.get("label_en"),"layer_url":f"/static/outputs/{image_id}/layers/{lid}.png","mask_url":f"/static/outputs/{image_id}/layers/{lid}-mask.png","bbox":bbox,"confidence":item.get("confidence",0.9),"z_index":i,"visible":True,"opacity":1,"transform":{"x":bbox['x'],"y":bbox['y'],"scale_x":1,"scale_y":1,"rotation":0,"flip_x":False,"flip_y":False}})

        inpaint_used = False; inpaint_fb = True
        clean_background_url = processed_original_url
        warning = None
        if need_inpainting:
            ip_provider = os.getenv("INPAINT_PROVIDER", "none").strip().lower()
            if ip_provider == "external":
                with httpx.Client(timeout=60) as client:
                    r = client.post(os.getenv("INPAINT_API_URL",""), json={"image_base64": LayerService._image_to_base64(img), "combined_mask_base64": LayerService._image_to_base64(combined.convert("RGBA"))}, headers={"Content-Type":"application/json","Authorization":f"Bearer {os.getenv('INPAINT_API_KEY','')}"})
                    r.raise_for_status(); d=r.json()
                clean = LayerService._decode_base64_image(d.get("clean_background_base64"))
                clean.save(out / "clean_background.png")
                clean_background_url = f"/static/outputs/{image_id}/layers/clean_background.png"
                inpaint_used = True; inpaint_fb = False
            else:
                warning = "当前未进行背景修补，移动元素后原位置可能仍保留原图内容。"

        return {"status":"success","message":"对象图层提取完成","image_id":image_id,"fallback_used":False,"segmentation_method":"external","inpainting_used":inpaint_used,"inpainting_fallback_used":inpaint_fb,"original_image_url":image_url,"processed_original_url":processed_original_url,"clean_background_url":clean_background_url,"background_url":clean_background_url,"canvas":{"width":img.width,"height":img.height},"layers":layers,"warning":warning}

    @staticmethod
    def decompose(image_url: str, max_layers: int = 8) -> dict:
        return LayerService.extract_by_objects(image_url, [], True)

    @staticmethod
    def manual_extract(image_url: str, bbox: dict) -> dict:
        img, image_id, out, processed_original_url = LayerService._prepare_image(image_url)
        x = max(0, int(bbox.get('x', 0))); y = max(0, int(bbox.get('y', 0)))
        w = max(1, int(bbox.get('width', 1))); h = max(1, int(bbox.get('height', 1)))
        x1 = min(img.width, x + w); y1 = min(img.height, y + h)
        crop = img.crop((x, y, x1, y1)); lid='layer-1'; crop.save(out / f'{lid}.png')
        mask = Image.new('L', (x1-x, y1-y), 255); mask.save(out / f'{lid}-mask.png')
        layer={'id': lid,'name':'手动框选元素 1','layer_url': f'/static/outputs/{image_id}/layers/{lid}.png','mask_url': f'/static/outputs/{image_id}/layers/{lid}-mask.png','bbox': {'x':x,'y':y,'width':x1-x,'height':y1-y},'confidence': 1.0,'z_index':1,'visible':True,'opacity':1,'transform': {'x':x,'y':y,'scale_x':1,'scale_y':1,'rotation':0,'flip_x':False,'flip_y':False}}
        return {'status':'success','message':'当前为手动框选临时模式，未进行自动物体分割和背景修补','image_id':image_id,'fallback_used':True,'segmentation_method':'manual','inpainting_used':False,'inpainting_fallback_used':True,'model_required':False,'original_image_url':image_url,'processed_original_url':processed_original_url,'clean_background_url':processed_original_url,'canvas':{'width':img.width,'height':img.height},'background_url':processed_original_url,'layers':[layer]}

    @staticmethod
    def compose(payload: dict) -> dict:
        bg_url = payload.get('background_url'); bg = Image.open(LayerService._path_from_static(bg_url)).convert('RGBA'); image_id = payload['image_id']
        for l in sorted(payload['layers'], key=lambda x: x.get('z_index', 0)):
            if not l.get('visible', True): continue
            im = Image.open(LayerService._path_from_static(l['layer_url'])).convert('RGBA')
            sx = max(0.01, abs(float(l.get('scale_x', l.get('transform', {}).get('scale_x', 1))))); sy = max(0.01, abs(float(l.get('scale_y', l.get('transform', {}).get('scale_y', 1)))))
            if l.get('flip_x', l.get('transform', {}).get('flip_x', False)): im = ImageOps.mirror(im)
            if l.get('flip_y', l.get('transform', {}).get('flip_y', False)): im = ImageOps.flip(im)
            im = im.resize((max(1, int(im.width * sx)), max(1, int(im.height * sy))))
            rotation = float(l.get('rotation', l.get('transform', {}).get('rotation', 0)))
            if rotation: im = im.rotate(rotation, expand=True)
            opacity = float(l.get('opacity', 1))
            if opacity < 1: a = im.split()[-1].point(lambda p: int(p * opacity)); im.putalpha(a)
            x = int(l.get('x', l.get('transform', {}).get('x', 0))); y = int(l.get('y', l.get('transform', {}).get('y', 0))); bg.alpha_composite(im, (x, y))
        outdir = Path('static/outputs') / image_id; outdir.mkdir(parents=True, exist_ok=True)
        name = f"composition_{uuid4().hex[:8]}.png"; out = outdir / name; bg.save(out)
        return {'status':'success','message':'构图实验图已生成','after_image_url':f'/static/outputs/{image_id}/{name}','composition_result_url':f'/static/outputs/{image_id}/composition_result.json','operations_summary':[op.get('description', '') for op in payload.get('operations', []) if op.get('description')],'inpainting_used':payload.get('inpainting_used',False),'warning': None if payload.get('inpainting_used',False) else '当前未进行背景修补，移动元素后原位置可能仍保留原图内容。'}
