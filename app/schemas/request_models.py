from pydantic import BaseModel, Field


class ExtractElementsRequest(BaseModel):
    image_url: str = Field(..., description="/static/uploads/xxx.png or static/uploads/xxx.png")
    max_layers: int = Field(default=24, ge=1, le=128)
    min_area: int = Field(default=80, ge=1)
