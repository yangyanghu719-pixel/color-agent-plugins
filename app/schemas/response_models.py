from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: str
    message: str


class LayerItem(BaseModel):
    id: str
    name: str
    type: str
    bbox: list[int]
    center: list[float]
    area: int
    coverage: float
    image_url: str
    mask_url: str
    z_index: int


class ExtractDebug(BaseModel):
    background_rgb: list[int]
    foreground_coverage: float
    debug_mask_url: str
    debug_overlay_url: str
    warnings: list[str]
    extraction_stats: dict


class ExtractElementsResponse(BaseModel):
    status: str
    message: str
    image_url: str
    canvas_width: int
    canvas_height: int
    layer_count: int
    layers: list[LayerItem]
    debug: ExtractDebug
