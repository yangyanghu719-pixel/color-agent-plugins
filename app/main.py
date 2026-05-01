from fastapi import FastAPI

from app.schemas.request_models import AnalyzeRequest, RecolorRequest, SegmentRequest
from app.schemas.response_models import AnalyzeResponse, HealthResponse, RecolorResponse, SegmentResponse
from app.services.analyze_service import AnalyzeService
from app.services.recolor_service import RecolorService
from app.services.segment_service import SegmentService

app = FastAPI(title="Color Agent Plugins API", version="0.1.0")


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
