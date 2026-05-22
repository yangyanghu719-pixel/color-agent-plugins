from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, File, UploadFile
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from app.schemas.request_models import AnalyzeRequest, CompositionAnalyzeRequest, LayerComposeRequest, LayerDecomposeRequest, ManualExtractRequest, RecolorRequest, SegmentRequest
from app.schemas.response_models import AnalyzeResponse, CompositionAnalyzeResponse, HealthResponse, LayerComposeResponse, LayerDecomposeResponse, RecolorResponse, SegmentResponse
from app.services.analyze_service import AnalyzeService
from app.services.composition_analyze_service import CompositionAnalyzeService
from app.services.layer_service import LayerService
from app.services.recolor_service import RecolorService
from app.services.segment_service import SegmentService

app = FastAPI(title="Color Agent Web App API", version="0.3.0")
ALLOWED_UPLOAD_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}
UPLOAD_DIR = Path("static/uploads"); UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

@app.get('/health', response_model=HealthResponse)
def health(): return {"status":"ok","message":"service is running"}
@app.post('/segment', response_model=SegmentResponse)
def segment(payload: SegmentRequest): return SegmentService.segment_colors(payload)
@app.post('/recolor', response_model=RecolorResponse)
def recolor(payload: RecolorRequest): return RecolorService.recolor(payload)
@app.post('/analyze', response_model=AnalyzeResponse)
def analyze(payload: AnalyzeRequest): return AnalyzeService.analyze(payload)
@app.post('/layers/decompose', response_model=LayerDecomposeResponse)
def layer_decompose(payload: LayerDecomposeRequest): return LayerService.decompose(payload.image_url, payload.max_layers)
@app.post('/layers/manual-extract', response_model=LayerDecomposeResponse)
def layer_manual_extract(payload: ManualExtractRequest): return LayerService.manual_extract(payload.image_url, payload.bbox)
@app.post('/layers/compose', response_model=LayerComposeResponse)
def layer_compose(payload: LayerComposeRequest): return LayerService.compose(payload.model_dump())
@app.post('/composition/analyze', response_model=CompositionAnalyzeResponse)
def composition_analyze(payload: CompositionAnalyzeRequest): return CompositionAnalyzeService.analyze(payload.model_dump())

@app.get('/experiment', response_class=HTMLResponse)
def experiment(): return HTMLResponse(Path('app/templates/experiment.html').read_text(encoding='utf-8'))
@app.get('/layered', response_class=HTMLResponse)
def layered(): return HTMLResponse(Path('app/templates/experiment.html').read_text(encoding='utf-8'))

@app.post('/upload-image')
async def upload_image(file: UploadFile = File(...)):
    if not file.filename: return {"status":"error","message":"文件为空"}
    ext = Path(file.filename).suffix.lower()
    if ext not in ALLOWED_UPLOAD_EXTENSIONS: return {"status":"error","message":"文件格式不支持，仅支持 png/jpg/jpeg/webp"}
    content = await file.read()
    if not content: return {"status":"error","message":"文件为空"}
    save_name = f"{uuid4().hex}{ext}"; save_path = UPLOAD_DIR / save_name
    try: save_path.write_bytes(content)
    except OSError: return {"status":"error","message":"保存失败"}
    display_url = f"/static/uploads/{save_name}"
    return {"status":"success","message":"图片上传成功","original_image_url":str(save_path),"original_image_display_url":display_url,"image_url":str(save_path),"display_url":display_url}

app.mount('/static', StaticFiles(directory='static'), name='static')
