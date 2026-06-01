from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

HEX_COLOR_PATTERN = re.compile(r"^#[0-9A-Fa-f]{6}$")
SUPPORTED_TYPES = {
    "dot",
    "hollow_dot",
    "dot_grid",
    "dot_cluster",
    "line",
    "polyline",
    "curve_line",
    "line_group",
    "circle",
    "ellipse",
    "rectangle",
    "triangle",
    "trapezoid",
    "grid_pattern",
    "triangle_pattern",
}
SUPPORTED_ROLES = {
    "dominant_plane",
    "support_plane",
    "accent_plane",
    "structural_line",
    "texture_group",
    "pattern_group",
    "point_group",
    "background_support",
    "unknown",
}


class CompositionCanvas(BaseModel):
    width: int = Field(default=1000, ge=1)
    height: int = Field(default=1000, ge=1)
    background: str = "#FFFFFF"

    @field_validator("background")
    @classmethod
    def validate_background(cls, value: str) -> str:
        if not HEX_COLOR_PATTERN.match(value):
            raise ValueError("background must be a valid hex color like #FFFFFF")
        return value.upper()


class CompositionSourceSummary(BaseModel):
    input_type: str = "manual_sample"
    abstract_style: str = "geometric"
    visual_center: list[float] = Field(default_factory=lambda: [0.5, 0.5], min_length=2, max_length=2)
    balance: str = "centered"
    density: str = "medium"
    main_subject: str = "none"
    subject_region: list[float] | None = Field(default=None, min_length=4, max_length=4)
    subject_priority: Literal["high", "medium", "low"] = "low"

    @field_validator("visual_center")
    @classmethod
    def validate_visual_center(cls, value: list[float]) -> list[float]:
        for axis in value:
            if not 0 <= axis <= 1:
                raise ValueError("visual_center must be between 0 and 1")
        return value

    @field_validator("subject_region")
    @classmethod
    def validate_subject_region(cls, value: list[float] | None) -> list[float] | None:
        if value is not None and any(not 0 <= axis <= 1 for axis in value):
            raise ValueError("subject_region must be between 0 and 1")
        return value


class CompositionElement(BaseModel):
    id: str
    type: str
    role: Literal[
        "dominant_plane",
        "support_plane",
        "accent_plane",
        "structural_line",
        "texture_group",
        "pattern_group",
        "point_group",
        "background_support",
        "unknown",
    ] = "unknown"
    opacity: float = Field(default=1, ge=0, le=1)
    z_index: int = 0

    model_config = {"extra": "allow"}

    @field_validator("type")
    @classmethod
    def validate_type(cls, value: str) -> str:
        if value not in SUPPORTED_TYPES:
            raise ValueError(f"unsupported element type: {value}")
        return value

    @model_validator(mode="after")
    def validate_element_fields(self) -> "CompositionElement":
        data: dict[str, Any] = self.model_dump()

        def need(keys: list[str]) -> None:
            missing = [k for k in keys if k not in data]
            if missing:
                raise ValueError(f"missing required fields: {', '.join(missing)}")

        def in01(key: str) -> None:
            val = data.get(key)
            if val is None or not 0 <= val <= 1:
                raise ValueError(f"{key} must be between 0 and 1")

        def gt0_int(key: str) -> None:
            val = data.get(key)
            if not isinstance(val, int) or val <= 0:
                raise ValueError(f"{key} must be a positive integer")

        def color(key: str) -> None:
            val = data.get(key)
            if not isinstance(val, str) or not HEX_COLOR_PATTERN.match(val):
                raise ValueError(f"{key} must be a valid hex color like #000000")

        t = self.type
        if t in {"dot", "circle"}:
            need(["x", "y", "radius", "fill"])
            for k in ["x", "y", "radius"]:
                in01(k)
            color("fill")
        elif t == "hollow_dot":
            need(["x", "y", "radius", "stroke", "stroke_width"])
            for k in ["x", "y", "radius", "stroke_width"]:
                in01(k)
            color("stroke")
        elif t == "dot_grid":
            need(["x", "y", "width", "height", "rows", "cols", "dot_radius", "rotation", "fill"])
            for k in ["x", "y", "width", "height", "dot_radius"]:
                in01(k)
            gt0_int("rows")
            gt0_int("cols")
            color("fill")
        elif t == "dot_cluster":
            need(["x", "y", "width", "height", "count", "size_min", "size_max", "randomness", "fill"])
            for k in ["x", "y", "width", "height", "size_min", "size_max", "randomness"]:
                in01(k)
            gt0_int("count")
            color("fill")
        elif t == "line":
            need(["x1", "y1", "x2", "y2", "stroke", "stroke_width", "style"])
            for k in ["x1", "y1", "x2", "y2", "stroke_width"]:
                in01(k)
            color("stroke")
            if data.get("style") not in {"solid", "dashed"}:
                raise ValueError("style must be solid or dashed")
        elif t in {"polyline", "curve_line"}:
            need(["points", "stroke", "stroke_width", "style"])
            points = data.get("points", [])
            min_len = 3 if t == "curve_line" else 2
            if len(points) < min_len:
                raise ValueError(f"points must contain at least {min_len} points")
            for p in points:
                if len(p) != 2 or not 0 <= p[0] <= 1 or not 0 <= p[1] <= 1:
                    raise ValueError("points must be [x,y] with each value between 0 and 1")
            color("stroke")
        elif t == "line_group":
            need(["x", "y", "width", "height", "line_count", "angle", "spacing", "stroke", "stroke_width"])
            for k in ["x", "y", "width", "height", "spacing", "stroke_width"]:
                in01(k)
            gt0_int("line_count")
            color("stroke")
        elif t in {"ellipse", "rectangle", "triangle", "trapezoid", "grid_pattern", "triangle_pattern"}:
            common = ["x", "y", "width", "height"]
            need(common)
            for k in common:
                in01(k)
            if t in {"ellipse", "rectangle", "triangle", "trapezoid", "triangle_pattern"}:
                need(["fill"])
                color("fill")
            if t == "triangle":
                if data.get("triangle_kind") not in {"equilateral", "acute", "obtuse"}:
                    raise ValueError("triangle_kind must be equilateral/acute/obtuse")
            if t == "trapezoid":
                need(["top_ratio"])
                in01("top_ratio")
            if t == "grid_pattern":
                need(["rows", "cols", "stroke", "stroke_width"])
                gt0_int("rows")
                gt0_int("cols")
                in01("stroke_width")
                color("stroke")
            if t == "triangle_pattern":
                need(["count", "size_min", "size_max", "distribution"])
                gt0_int("count")
                in01("size_min")
                in01("size_max")
                if data.get("distribution") not in {"regular", "scattered"}:
                    raise ValueError("distribution must be regular or scattered")
        return self


class CompositionParamDocument(BaseModel):
    version: str = "1.0"
    canvas: CompositionCanvas
    source_summary: CompositionSourceSummary
    elements: list[CompositionElement] = Field(default_factory=list)
