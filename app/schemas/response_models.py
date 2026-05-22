from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field

from app.schemas.request_models import ColorRegionModel, HSLModel, LayerTransformModel


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
    model_markdown: Optional[str] = None
    suggestions: List[str] = Field(default_factory=list)
    rule_based_tags: List[str] = Field(default_factory=list)
    fallback_used: bool = False
    model_error: Optional[str] = None


class LayerModel(BaseModel):
    id: str
    name: str
    layer_url: str
    mask_url: str
    bbox: dict
    z_index: int
    visible: bool = True
    opacity: float = 1
    transform: LayerTransformModel


class LayerDecomposeResponse(BaseModel):
    status: str
    message: str
    image_id: str
    fallback_used: bool
    original_image_url: str
    processed_original_url: Optional[str] = None
    canvas: dict
    background_url: str
    layers: List[LayerModel]


class LayerComposeResponse(BaseModel):
    status: str
    message: str
    after_image_url: str
    composition_result_url: str
    operations_summary: List[str] = Field(default_factory=list)


class CompositionAnalyzeResponse(BaseModel):
    status: str
    message: str
    summary: str = ""
    composition_change: str = ""
    visual_focus_analysis: str = ""
    balance_analysis: str = ""
    proportion_analysis: str = ""
    direction_analysis: str = ""
    blank_space_analysis: str = ""
    layer_order_analysis: str = ""
    spatial_relationship_analysis: str = ""
    learning_explanation: str = ""
    suggestions: List[str] = Field(default_factory=list)
    fallback_used: bool = False
    model_error: Optional[str] = None
