from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, File, UploadFile
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from app.schemas.request_models import AnalyzeRequest, RecolorRequest, SegmentRequest
from app.schemas.response_models import AnalyzeResponse, HealthResponse, RecolorResponse, SegmentResponse
from app.services.analyze_service import AnalyzeService
from app.services.recolor_service import RecolorService
from app.services.segment_service import SegmentService

app = FastAPI(title="Color Agent Plugins API", version="0.1.0")

ALLOWED_UPLOAD_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}
UPLOAD_DIR = Path("static/uploads")
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


@app.get("/health", response_model=HealthResponse)
def health() -> dict:
    return {"status": "ok", "message": "service is running"}


@app.post("/segment", response_model=SegmentResponse)
def segment(payload: SegmentRequest) -> dict:
    return SegmentService.segment_colors(payload)


@app.post("/recolor", response_model=RecolorResponse)
def recolor(payload: RecolorRequest) -> dict:
    return RecolorService.recolor(payload)


@app.post("/analyze", response_model=AnalyzeResponse)
def analyze(payload: AnalyzeRequest) -> dict:
    return AnalyzeService.analyze(payload)


@app.get("/experiment", response_class=HTMLResponse)
def experiment() -> HTMLResponse:
    html = Path("app/templates/experiment.html").read_text(encoding="utf-8")
    return HTMLResponse(content=html)


@app.post("/upload-image")
async def upload_image(file: UploadFile = File(...)) -> dict:
    if not file.filename:
        return {"status": "error", "message": "文件为空"}

    ext = Path(file.filename).suffix.lower()
    if ext not in ALLOWED_UPLOAD_EXTENSIONS:
        return {"status": "error", "message": "文件格式不支持，仅支持 png/jpg/jpeg/webp"}

    content = await file.read()
    if not content:
        return {"status": "error", "message": "文件为空"}

    save_name = f"{uuid4().hex}{ext}"
    save_path = UPLOAD_DIR / save_name

    try:
        save_path.write_bytes(content)
    except OSError:
        return {"status": "error", "message": "保存失败"}

    display_url = f"/static/uploads/{save_name}"
    return {
        "status": "success",
        "message": "图片上传成功",
        "image_url": str(save_path),
        "display_url": display_url,
    }


app.mount("/static", StaticFiles(directory="static"), name="static")
