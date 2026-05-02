from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from app.experiment_page import EXPERIMENT_HTML
from app.schemas.request_models import AnalyzeRequest, RecolorRequest, SegmentRequest
from app.schemas.response_models import AnalyzeResponse, HealthResponse, RecolorResponse, SegmentResponse
from app.services.analyze_service import AnalyzeService
from app.services.recolor_service import RecolorService
from app.services.segment_service import SegmentService

app = FastAPI(title="Color Agent Plugins API", version="0.1.0")

UPLOAD_DIR = Path("static/uploads")
ALLOWED_UPLOAD_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}


@app.get("/health", response_model=HealthResponse)
def health() -> dict:
    return {"status": "ok", "message": "service is running"}


@app.get("/experiment", response_class=HTMLResponse)
def experiment() -> str:
    return EXPERIMENT_HTML


@app.post("/upload-image")
async def upload_image(file: UploadFile = File(...)) -> dict:
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in ALLOWED_UPLOAD_SUFFIXES:
        raise HTTPException(status_code=400, detail="Only png, jpg, jpeg, and webp images are supported")

    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    filename = f"{uuid4().hex}{suffix}"
    path = UPLOAD_DIR / filename

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")

    path.write_bytes(content)
    return {
        "image_url": f"static/uploads/{filename}",
        "display_url": f"/static/uploads/{filename}",
    }


@app.post("/segment", response_model=SegmentResponse)
def segment(payload: SegmentRequest) -> dict:
    return SegmentService.segment_colors(payload)


@app.post("/recolor", response_model=RecolorResponse)
def recolor(payload: RecolorRequest) -> dict:
    return RecolorService.recolor(payload)


@app.post("/analyze", response_model=AnalyzeResponse)
def analyze(payload: AnalyzeRequest) -> dict:
    return AnalyzeService.analyze(payload)


app.mount("/static", StaticFiles(directory="static"), name="static")
