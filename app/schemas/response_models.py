from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field

from app.schemas.request_models import ColorRegionModel, HSLModel


class HealthResponse(BaseModel):
    status: str
    message: str


class SegmentResponse(BaseModel):
    status: str
    message: str
    image_id: str
    original_image_url: str
    processed_image_url: Optional[str] = None
    annotated_image_url: str
    color_regions: List[ColorRegionModel]


class RecolorChangeModel(BaseModel):
    hue_change: int
    saturation_change: int
    lightness_change: int


class RecolorResponse(BaseModel):
    status: str
    message: str
    target_region_id: str
    preview_image_url: str
    before_hsl: HSLModel
    after_hsl: HSLModel
    change: RecolorChangeModel


class AnalyzeResponse(BaseModel):
    status: str
    message: str
    tags: List[str] = Field(default_factory=list)
    color_relation: str
    visual_feeling: str
    suitable_scenario: str
    summary: str
    ai_explanation: str
    risk: str
    next_step: str
