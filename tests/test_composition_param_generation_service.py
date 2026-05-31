import json
from pathlib import Path

import pytest

from app.services.composition_param_generation_service import (
    CompositionParamGenerationService,
    build_generation_prompt,
)


def _sample_json() -> dict:
    return json.loads(Path("static/examples/composition_param_sample.json").read_text(encoding="utf-8"))


def test_generation_service_valid_json_passes_schema_validation():
    raw = json.dumps(_sample_json(), ensure_ascii=False)
    result = CompositionParamGenerationService(lambda image, hint: raw).generate("unused.png", "少量大图元")
    assert result.status == "success"
    assert result.valid is True
    assert result.document == _sample_json()
    assert result.errors == []


def test_generation_service_invalid_json_returns_parse_error():
    result = CompositionParamGenerationService(lambda image, hint: "not json").generate("unused.png")
    assert result.status == "error"
    assert result.valid is False
    assert result.document is None
    assert result.raw_text == "not json"
    assert "JSON parse error" in result.errors[0]["message"]


def test_generation_service_schema_invalid_json_returns_validation_errors():
    payload = _sample_json()
    payload["elements"][0]["type"] = "unsupported_shape"
    raw = json.dumps(payload, ensure_ascii=False)
    result = CompositionParamGenerationService(lambda image, hint: raw).generate("unused.png")
    assert result.status == "error"
    assert result.valid is False
    assert result.document is None
    assert result.raw_text == raw
    assert result.errors[0]["path"] == "elements[0].type"


def test_generation_prompt_restricts_types_counts_and_output_format():
    prompt = build_generation_prompt("尽量用少量大图元概括")
    for token in ["dot", "triangle_pattern", "6~20", "24", "normalized coordinate", "不要输出 Markdown 代码块", "尽量用少量大图元概括", "禁止使用 schema 外的别名字段", "cx、cy、r", "line_group: x, y, width, height, line_count, angle, spacing, stroke_width"]:
        assert token in prompt


def _document_with_element(element: dict) -> dict:
    return {
        "version": "1.0",
        "canvas": {"width": 1000, "height": 1000, "background": "#FFFFFF"},
        "source_summary": {
            "input_type": "reference_image",
            "abstract_style": "geometric",
            "visual_center": [0.5, 0.5],
            "balance": "centered",
            "density": "medium",
        },
        "elements": [element],
    }


def test_generation_service_normalizes_circle_center_and_radius_aliases():
    payload = _document_with_element({"kind": "circle", "cx": 0.4, "cy": 0.6, "r": 0.12, "color": "#123456"})
    result = CompositionParamGenerationService(lambda image, hint: json.dumps(payload)).generate("unused.png")
    assert result.valid is True
    assert result.document["elements"][0]["x"] == 0.4
    assert result.document["elements"][0]["y"] == 0.6
    assert result.document["elements"][0]["radius"] == 0.12
    assert result.document["elements"][0]["fill"] == "#123456"
    assert any("normalized cx -> x" in warning for warning in result.normalization_warnings)


def test_generation_service_normalizes_box_size_color_and_stroke_width_aliases():
    payload = _document_with_element({
        "type": "rectangle", "cx": 0.5, "cy": 0.4, "w": 0.4, "h": 0.2,
        "color": "#ABCDEF", "strokeWidth": 0.006,
    })
    result = CompositionParamGenerationService(lambda image, hint: json.dumps(payload)).generate("unused.png")
    assert result.valid is True
    element = result.normalized_payload["elements"][0]
    assert element["x"] == 0.3
    assert pytest.approx(element["y"]) == 0.3
    assert element["width"] == 0.4
    assert element["height"] == 0.2
    assert element["fill"] == "#ABCDEF"
    assert element["stroke_width"] == 0.006
    assert "w" not in element and "h" not in element and "color" not in element and "strokeWidth" not in element


def test_generation_service_normalizes_line_group_aliases_and_defaults():
    payload = _document_with_element({
        "type": "line_group", "x": 0.1, "y": 0.2, "width": 0.3, "height": 0.4,
        "count": 7, "direction": "vertical", "density": "high",
    })
    result = CompositionParamGenerationService(lambda image, hint: json.dumps(payload)).generate("unused.png")
    assert result.valid is True
    element = result.normalized_payload["elements"][0]
    assert element["line_count"] == 7
    assert element["angle"] == 90
    assert element["spacing"] == 0.02
    assert element["stroke_width"] == 0.004
    assert element["stroke"] == "#000000"


def test_generation_service_maps_line_group_density_when_count_is_missing():
    payload = _document_with_element({
        "type": "line_group", "x": 0.1, "y": 0.2, "width": 0.3, "height": 0.4,
        "direction": 30, "density": "high",
    })
    result = CompositionParamGenerationService(lambda image, hint: json.dumps(payload)).generate("unused.png")
    assert result.valid is True
    assert result.normalized_payload["elements"][0]["line_count"] == 16


def test_generation_service_keeps_missing_critical_position_as_validation_error():
    payload = _document_with_element({"type": "circle", "r": 0.1, "color": "#123456"})
    result = CompositionParamGenerationService(lambda image, hint: json.dumps(payload)).generate("unused.png")
    assert result.valid is False
    assert result.normalized_payload is not None
    assert result.normalized_payload["elements"][0]["radius"] == 0.1
    assert "missing required fields: x, y" in result.errors[0]["message"]


def test_generation_service_extracts_json_from_accidental_markdown_fence():
    payload = _document_with_element({"type": "circle", "x": 0.5, "y": 0.5, "radius": 0.1})
    raw = f"```json\n{json.dumps(payload)}\n```"
    result = CompositionParamGenerationService(lambda image, hint: raw).generate("unused.png")
    assert result.valid is True
