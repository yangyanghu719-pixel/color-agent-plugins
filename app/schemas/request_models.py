from __future__ import annotations

from typing import Any, List, Optional

from pydantic import BaseModel, Field, HttpUrl, model_validator


class HSLModel(BaseModel):
    h: int = Field(..., ge=0, le=360)
    s: int = Field(..., ge=0, le=100)
    l: int = Field(..., ge=0, le=100)


class RGBModel(BaseModel):
    r: int = Field(..., ge=0, le=255)
    g: int = Field(..., ge=0, le=255)
    b: int = Field(..., ge=0, le=255)


class ColorRegionModel(BaseModel):
    id: str
    name: str
    hex: str
    rgb: RGBModel
    hsl: HSLModel
    percentage: float = Field(..., ge=0, le=100)
    role: str
    mask_url: str
    soft_mask_url: str
    description: str


class SegmentRequest(BaseModel):
    image_url: Optional[str] = None
    color_count: int = Field(4, ge=1, le=12)


class RecolorRequest(BaseModel):
    image_id: str
    original_image_url: HttpUrl
    region_id: Optional[str] = None
    target_region_id: Optional[str] = None
    original_hsl: HSLModel
    new_hsl: HSLModel

    @model_validator(mode="after")
    def normalize_region_id(self):
        rid = self.region_id or self.target_region_id
        if not rid:
            raise ValueError("region_id is required")
        self.region_id = rid
        self.target_region_id = rid
        return self


class AnalyzeRequest(BaseModel):
    original_color_regions: List[ColorRegionModel]
    adjusted_color_regions: List[ColorRegionModel]
    before_image_url: HttpUrl
    after_image_url: HttpUrl
    user_goal: Optional[str] = None
