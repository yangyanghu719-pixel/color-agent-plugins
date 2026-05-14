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
    analysis_type: Optional[str] = None
    summary: Optional[str] = ""
    overall_impression: Optional[str] = ""
    hue_analysis: Optional[str] = ""
    saturation_analysis: Optional[str] = ""
    lightness_analysis: Optional[str] = ""
    color_relationship_analysis: Optional[str] = ""
    visual_focus_analysis: Optional[str] = ""
    emotional_expression: Optional[str] = ""
    learning_explanation: Optional[str] = ""
    suggestions: List[str] = Field(default_factory=list)
    rule_based_tags: List[str] = Field(default_factory=list)
    fallback_used: bool = False
