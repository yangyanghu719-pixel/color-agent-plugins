from __future__ import annotations
import json
from pathlib import Path
from uuid import uuid4
from PIL import Image, ImageOps


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
    def decompose(image_url: str, max_layers: int = 8) -> dict:
        img = Image.open(LayerService._path_from_static(image_url)).convert('RGBA')
        w,h = img.size
        image_id=f"img-{uuid4().hex[:12]}"
        out = Path('static/outputs')/image_id/'layers'; out.mkdir(parents=True, exist_ok=True)
        bg = Image.new('RGBA',(w,h),(255,255,255,255)); bg.save(out/'background.png')
        cols = min(max_layers,4)
        slice_w=max(1,w//cols)
        layers=[]
        for i in range(cols):
            x0=i*slice_w; x1=w if i==cols-1 else (i+1)*slice_w
            layer=Image.new('RGBA',(w,h),(0,0,0,0)); crop=img.crop((x0,0,x1,h)); layer.paste(crop,(x0,0));
            mask=Image.new('L',(w,h),0); mask.paste(255,(x0,0,x1,h))
            lid=f'layer-{i+1}'
            layer.save(out/f'{lid}.png'); mask.save(out/f'{lid}-mask.png')
            layers.append({"id":lid,"name":f"元素 {i+1}","layer_url":f"/static/outputs/{image_id}/layers/{lid}.png","mask_url":f"/static/outputs/{image_id}/layers/{lid}-mask.png","bbox":{"x":x0,"y":0,"width":x1-x0,"height":h},"z_index":i+1,"visible":True,"opacity":1,"transform":{"x":x0,"y":0,"scale_x":1,"scale_y":1,"rotation":0,"flip_x":False,"flip_y":False}})
        resp={"status":"success","message":"fallback 图层拆解完成","image_id":image_id,"fallback_used":True,"original_image_url":image_url,"canvas":{"width":w,"height":h},"background_url":f"/static/outputs/{image_id}/layers/background.png","layers":layers}
        (Path('static/outputs')/image_id/'layer_decompose_result.json').write_text(json.dumps(resp,ensure_ascii=False,indent=2),encoding='utf-8')
        return resp

    @staticmethod
    def compose(payload: dict) -> dict:
        bg = Image.open(LayerService._path_from_static(payload['background_url'])).convert('RGBA')
        image_id=payload['image_id']
        for l in sorted(payload['layers'], key=lambda x:x.get('z_index',0)):
            if not l.get('visible',True): continue
            im=Image.open(LayerService._path_from_static(l['layer_url'])).convert('RGBA')
            if l.get('flip_x'): im=ImageOps.mirror(im)
            if l.get('flip_y'): im=ImageOps.flip(im)
            sx=max(0.01,float(l.get('scale_x',1))); sy=max(0.01,float(l.get('scale_y',1)))
            im=im.resize((max(1,int(im.width*sx)),max(1,int(im.height*sy))))
            if l.get('rotation'): im=im.rotate(float(l['rotation']),expand=True)
            if l.get('opacity',1)<1:
                a=im.split()[-1].point(lambda p:int(p*float(l['opacity']))); im.putalpha(a)
            bg.alpha_composite(im,(int(l.get('x',0)),int(l.get('y',0))))
        outdir=Path('static/outputs')/image_id; outdir.mkdir(parents=True,exist_ok=True)
        name=f"composition_{uuid4().hex[:8]}.png"; out=outdir/name; bg.save(out)
        summary=[op.get('description','') for op in payload.get('operations',[]) if op.get('description')]
        result={"layers":payload.get('layers',[]),"operations":payload.get('operations',[]),"after_image_url":f"/static/outputs/{image_id}/{name}"}
        (outdir/'composition_result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
        return {"status":"success","message":"构图实验图已生成","after_image_url":f"/static/outputs/{image_id}/{name}","composition_result_url":f"/static/outputs/{image_id}/composition_result.json","operations_summary":summary}
