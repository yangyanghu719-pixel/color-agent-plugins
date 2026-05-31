import json
from pathlib import Path

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
    for token in ["dot", "triangle_pattern", "6~20", "24", "normalized coordinate", "不要输出 Markdown 代码块", "尽量用少量大图元概括"]:
        assert token in prompt
