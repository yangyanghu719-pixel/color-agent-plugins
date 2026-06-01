from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from PIL import Image
from pydantic import ValidationError

from app.schemas.composition_param_models import CompositionParamDocument, SUPPORTED_TYPES
from app.services.qwen_client import image_to_data_url

DEFAULT_QWEN_BASE_URL = "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"
DEFAULT_QWEN_MODEL = "qwen-vl-max"


class QwenConfigurationError(RuntimeError):
    """Raised when Qwen environment configuration is incomplete."""


class QwenRequestError(RuntimeError):
    """Raised when the Qwen API request fails or produces no content."""

    def __init__(self, message: str, upstream_status: int | None = None, upstream_body_preview: str = "") -> None:
        super().__init__(message)
        self.upstream_status = upstream_status
        self.upstream_body_preview = upstream_body_preview[:500]


def format_validation_errors(exc: ValidationError) -> list[dict[str, str]]:
    errors = []
    for error in exc.errors():
        parts: list[str] = []
        for part in error.get("loc", []):
            if isinstance(part, int) and parts:
                parts[-1] = f"{parts[-1]}[{part}]"
            else:
                parts.append(str(part))
        errors.append({"path": ".".join(parts), "message": error.get("msg", "invalid")})
    return errors


def read_source_image_info(image_path: str | Path) -> dict[str, int | float] | None:
    """Read source dimensions and derive a proportional preview canvas."""
    path = Path(image_path)
    if not path.is_file():
        return None
    with Image.open(path) as image:
        width, height = image.size
    if width <= 0 or height <= 0:
        return None
    return {"width": width, "height": height, "aspect_ratio": round(width / height, 6)}


def canvas_for_source(source_image: dict[str, int | float] | None) -> dict[str, int | str]:
    if not source_image:
        return {"width": 1000, "height": 1000, "background": "#FFFFFF"}
    width, height = int(source_image["width"]), int(source_image["height"])
    aspect_ratio = width / height
    if 0.95 <= aspect_ratio <= 1.05:
        canvas_width, canvas_height = 1000, 1000
    elif width > height:
        canvas_width, canvas_height = 1000, round(1000 * height / width)
    else:
        canvas_width, canvas_height = round(1000 * width / height), 1000
    return {"width": canvas_width, "height": canvas_height, "background": "#FFFFFF"}


def build_generation_prompt(user_hint: str | None = None, canvas: dict[str, int | str] | None = None) -> str:
    supported = ", ".join(sorted(SUPPORTED_TYPES))
    schema = json.dumps(CompositionParamDocument.model_json_schema(), ensure_ascii=False)
    hint = user_hint.strip() if user_hint and user_hint.strip() else "无额外提示"
    target_canvas = canvas or {"width": 1000, "height": 1000}
    return f"""你是一个“构成图像参数化转译助手”。你的唯一任务是把用户上传的白底抽象构成参考图转译为可编辑的 CompositionParamDocument JSON 草案，而不是精确像素复制。

严格规则：
1. 只能使用以下图元 type：{supported}。
2. 优先用少量较大的结构概括，不要碎片化。大结构优先，小装饰其次。
3. 默认目标元素数量为 6~20 个。即使图像复杂，也绝对不要超过 24 个 elements。不要输出几十上百个小元素。
4. 所有位置、尺寸、半径、线宽使用 normalized coordinate，数值范围为 0~1；canvas 必须使用后端按原图比例计算的 {target_canvas["width"]}x{target_canvas["height"]}，不要改成 1000x1000。
5. 顶层必须包含 version、canvas、source_summary、elements。
6. source_summary 必须包含 input_type、abstract_style、visual_center、balance、density、main_subject、subject_region、subject_priority。main_subject 用 character / person / object / animal / building / icon / geometric_shape / none 等简短值；subject_region 使用 [x, y, width, height] normalized coordinate；subject_priority 使用 high / medium / low。
7. 输出必须是严格合法 JSON，且符合下方 CompositionParamDocument JSON Schema。
8. 不要输出 Markdown 代码块，不要解释，不要输出任何 JSON 以外的文字。
9. 每个元素需要唯一 id、合法 role、opacity 和 z_index，并满足相应 type 的字段约束。
10. 禁止使用 schema 外的别名字段：cx、cy、r、center_x、center_y、w、h、color、strokeWidth。
11. 必须严格使用以下字段名：
   - circle / dot / hollow_dot: x, y, radius，其中 x/y 表示中心点。
   - rectangle / ellipse / triangle / trapezoid: x, y, width, height，其中 x/y 表示左上角。
   - line: x1, y1, x2, y2。
   - line_group: x, y, width, height, line_count, angle, spacing, stroke_width。
   - grid_pattern: x, y, width, height, rows, cols, stroke_width。
   - dot_grid: x, y, width, height, rows, cols, dot_radius。
   - triangle_pattern: x, y, width, height, count, size_min, size_max。
12. rectangle / ellipse / triangle / trapezoid / pattern / group 的 x/y 都表示左上角；所有坐标必须在 0~1 范围内。不要使用 schema 外字段。
13. 颜色必须直接根据参考图判断，不要使用固定建议色板。每个 plane / shape 必须输出 fill；每个 line / line_group / grid_pattern 必须输出 stroke；点类必须输出 fill 或 stroke。
14. 每个颜色值必须是 #RRGGBB 格式，并来自参考图主要颜色或近似颜色。不要省略颜色字段，不要把缺失颜色交给后端默认补黑；只有参考图中明确为黑色的区域才使用 #000000。
15. line_group 用于表达可读的线性节奏，不是大面积涂黑。stroke_width 必须明显小于 spacing，建议不超过 spacing * 0.35；背景纹理线组应更稀疏、更轻。

转译优先级：
第一优先级：保留主体。先识别画面中的 main subject；主体可能是人物、物体、动物、建筑、图标或中心形状。如果存在明显主体，必须用 2~6 个 role 为 dominant_plane / support_plane / accent_plane 的 plane/shape 元素表达主体。可以使用 ellipse、circle、rectangle、triangle、trapezoid 或 polygon-like approximation；当前 schema 没有自由 polygon 时，优先组合 ellipse / rectangle / triangle / trapezoid 近似。不要求还原细节，但必须保留主体的大位置、大体块和主色关系。
第二优先级：保留大构图关系。保留画面比例、视觉中心、主体和背景的位置关系、大色块、动势方向和主次关系。
第三优先级：保留纹理和背景节奏。line_group / grid_pattern / dot_grid / triangle_pattern 只能作为辅助。存在明显主体时，texture_group / pattern_group 的元素数量不能超过总元素的 40%，至少 30% 的元素应服务于主体表达。line_group 不应成为唯一主要内容，除非原图本身就是纯线构成。

禁止的坏结果：
- 不要只输出背景速度线。
- 不要只输出 line_group / texture_group。
- 如果画面中有主体，不允许忽略主体。
- 主体不需要细节还原，但必须有可见的大体块表达。
- 背景纹理必须弱于主体。
- 输出的是可编辑构成草案，不是背景纹理检测结果。

用户可选提示：{hint}

CompositionParamDocument JSON Schema：
{schema}
"""


class QwenParamClient:
    def generate(self, image_path: str | Path, user_hint: str | None = None) -> str:
        api_key = os.getenv("QWEN_API_KEY")
        if not api_key:
            raise QwenConfigurationError("未配置环境变量 QWEN_API_KEY，无法调用 Qwen 视觉模型")
        base_url = os.getenv("QWEN_BASE_URL", DEFAULT_QWEN_BASE_URL)
        model = os.getenv("QWEN_MODEL", DEFAULT_QWEN_MODEL)
        from openai import OpenAI

        client = OpenAI(api_key=api_key, base_url=base_url)
        try:
            completion = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": build_generation_prompt(user_hint, canvas_for_source(read_source_image_info(image_path)))},
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": "请将这张白底抽象构成参考图转译为可编辑的参数 JSON 草案。只输出 JSON。"},
                            {"type": "image_url", "image_url": {"url": image_to_data_url(str(image_path))}},
                        ],
                    },
                ],
                extra_body={"enable_thinking": False},
            )
        except Exception as exc:
            response = getattr(exc, "response", None)
            upstream_status = getattr(exc, "status_code", None) or getattr(response, "status_code", None)
            upstream_body = getattr(response, "text", "") if response is not None else ""
            raise QwenRequestError("Qwen API 调用失败", upstream_status, upstream_body or str(exc)) from exc
        content = completion.choices[0].message.content
        if not content:
            raise QwenRequestError("Qwen API 返回了空内容")
        return content.strip()


qwen_client = QwenParamClient()


def extract_json_payload(raw_text: str) -> Any:
    """Extract a JSON value from Qwen output while tolerating accidental prose or fences."""
    text = raw_text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError as original_exc:
        decoder = json.JSONDecoder()
        for marker in ("{", "["):
            offset = text.find(marker)
            while offset != -1:
                try:
                    payload, _ = decoder.raw_decode(text[offset:])
                    return payload
                except json.JSONDecodeError:
                    offset = text.find(marker, offset + 1)
        raise original_exc


def _warning(warnings: list[str], index: int, message: str) -> None:
    warnings.append(f"elements[{index}]: {message}")


def _move_alias(element: dict[str, Any], target: str, aliases: tuple[str, ...], warnings: list[str], index: int) -> None:
    for alias in aliases:
        if alias not in element:
            continue
        if target not in element:
            element[target] = element[alias]
            _warning(warnings, index, f"normalized {alias} -> {target}")
        else:
            _warning(warnings, index, f"discarded alias {alias} because {target} already exists")
        element.pop(alias, None)


def _default(element: dict[str, Any], key: str, value: Any, warnings: list[str], index: int) -> None:
    if key not in element:
        element[key] = value
        _warning(warnings, index, f"filled default {key}={value!r}")


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _clamp_number(element: dict[str, Any], key: str, minimum: float, maximum: float, warnings: list[str], index: int) -> None:
    if key not in element:
        return
    number = _number(element[key])
    if number is None:
        return
    clamped = min(max(number, minimum), maximum)
    if element[key] != clamped:
        _warning(warnings, index, f"clamped/coerced {key}: {element[key]!r} -> {clamped}")
    element[key] = clamped


def _coerce_positive_int(element: dict[str, Any], key: str, warnings: list[str], index: int) -> None:
    if key not in element:
        return
    number = _number(element[key])
    if number is None:
        return
    coerced = max(1, int(number))
    if element[key] != coerced:
        _warning(warnings, index, f"coerced {key}: {element[key]!r} -> {coerced}")
    element[key] = coerced


def _normalize_direction(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    return {
        "horizontal": 0,
        "vertical": 90,
        "diagonal": 45,
        "diagonal_up": -45,
        "diagonal_down": 45,
        "水平": 0,
        "垂直": 90,
        "斜线": 45,
    }.get(value.lower(), value)


def _element_mentions_dark(element: dict[str, Any]) -> bool:
    text = " ".join(str(value).lower() for value in element.values())
    return any(keyword in text for keyword in ("black", "dark", "silhouette", "shadow", "黑", "暗", "剪影", "阴影"))


def _fallback_color(element: dict[str, Any], color_key: str) -> str:
    if _element_mentions_dark(element):
        return "#000000"
    role = element.get("role", "unknown")
    if role in {"background_support", "texture_group", "pattern_group"}:
        return "#B0B0B0"
    if color_key == "stroke" or role == "structural_line":
        return "#707070"
    if role == "support_plane":
        return "#B8B8B8"
    return "#909090"


def _set_number(element: dict[str, Any], key: str, value: float | int, warnings: list[str], index: int, reason: str) -> None:
    if element.get(key) != value:
        _warning(warnings, index, f"adjusted {key}: {element.get(key)!r} -> {value!r} ({reason})")
        element[key] = value


def _normalize_line_group_readability(element: dict[str, Any], warnings: list[str], index: int) -> None:
    width, height = _number(element.get("width")), _number(element.get("height"))
    spacing, stroke_width = _number(element.get("spacing")), _number(element.get("stroke_width"))
    line_count = int(_number(element.get("line_count")) or 1)
    if spacing is None or stroke_width is None:
        return
    is_background = width is not None and height is not None and width > 0.7 and height > 0.7
    if is_background:
        if spacing < 0.035:
            spacing = 0.035
            _set_number(element, "spacing", spacing, warnings, index, "background texture line groups need visible gaps")
        if line_count > 24:
            line_count = 24
            _set_number(element, "line_count", line_count, warnings, index, "background texture line groups are capped at 24 lines")
        if _number(element.get("opacity")) is not None and _number(element["opacity"]) > 0.45:
            _set_number(element, "opacity", 0.45, warnings, index, "background texture line groups stay visually light")
        max_stroke_width = min(0.006, spacing * 0.25)
    else:
        if spacing < 0.01:
            spacing = 0.01
            _set_number(element, "spacing", spacing, warnings, index, "line groups need visible gaps")
        if line_count > 48:
            line_count = 48
            _set_number(element, "line_count", line_count, warnings, index, "line group count capped for readable rhythm")
        max_stroke_width = min(0.02, spacing * 0.35)
    max_coverage_stroke = 0.35 / max(line_count, 1)
    max_stroke_width = min(max_stroke_width, max_coverage_stroke)
    if stroke_width >= spacing or stroke_width > max_stroke_width:
        _set_number(element, "stroke_width", max_stroke_width, warnings, index, "keep lines separated and coverage readable")


def _append_subject_quality_warnings(payload: dict, warnings: list[str]) -> None:
    source_summary = payload.get("source_summary")
    elements = payload.get("elements")
    if not isinstance(source_summary, dict) or not isinstance(elements, list) or not elements:
        return
    main_subject = str(source_summary.get("main_subject", "none")).strip().lower()
    if not main_subject or main_subject == "none":
        return
    plane_roles = {"dominant_plane", "support_plane", "accent_plane"}
    texture_roles = {"texture_group", "pattern_group"}
    texture_types = {"line_group", "grid_pattern", "dot_grid", "triangle_pattern"}
    objects = [element for element in elements if isinstance(element, dict)]
    plane_count = sum(element.get("role") in plane_roles for element in objects)
    texture_count = sum(element.get("role") in texture_roles or element.get("type") in texture_types for element in objects)
    if plane_count < 2:
        warnings.append("main subject may be underrepresented")
    if objects and texture_count / len(objects) > 0.6:
        warnings.append("texture elements dominate the draft")


def normalize_composition_param_payload(payload: dict, warnings: list[str] | None = None, forced_canvas: dict[str, int | str] | None = None) -> dict:
    """Normalize common Qwen aliases into the existing CompositionParamDocument schema."""
    normalized = json.loads(json.dumps(payload))
    normalization_warnings = warnings if warnings is not None else []
    if forced_canvas is not None:
        if normalized.get("canvas") != forced_canvas:
            normalization_warnings.append(f"document.canvas: overridden by source image ratio -> {forced_canvas['width']}x{forced_canvas['height']}")
        normalized["canvas"] = dict(forced_canvas)
    elements = normalized.get("elements")
    if not isinstance(elements, list):
        return normalized

    center_box_types = {"ellipse", "rectangle", "triangle", "trapezoid", "dot_cluster", "line_group", "grid_pattern", "dot_grid", "triangle_pattern"}
    fill_types = {"dot", "circle", "ellipse", "rectangle", "triangle", "trapezoid", "dot_grid", "dot_cluster", "triangle_pattern"}
    stroke_types = {"hollow_dot", "line", "polyline", "curve_line", "line_group", "grid_pattern"}
    stroke_width_types = {"hollow_dot", "line", "polyline", "curve_line", "line_group", "grid_pattern"}

    for index, raw_element in enumerate(elements):
        if not isinstance(raw_element, dict):
            continue
        element = raw_element
        _move_alias(element, "type", ("kind",), normalization_warnings, index)
        _move_alias(element, "fill", ("color", "colour"), normalization_warnings, index)
        _move_alias(element, "opacity", ("alpha",), normalization_warnings, index)
        _move_alias(element, "z_index", ("layer", "z"), normalization_warnings, index)
        _move_alias(element, "stroke_width", ("strokeWidth",), normalization_warnings, index)
        element_type = element.get("type")

        if element_type in {"circle", "dot", "hollow_dot"}:
            _move_alias(element, "x", ("cx", "center_x"), normalization_warnings, index)
            _move_alias(element, "y", ("cy", "center_y"), normalization_warnings, index)
            _move_alias(element, "radius", ("r",), normalization_warnings, index)
            if "radius" not in element and "size" in element:
                size = element.pop("size")
                element["radius"] = _number(size) / 2 if _number(size) is not None else size
                _warning(normalization_warnings, index, "normalized size diameter -> radius")
        elif element_type in center_box_types:
            _move_alias(element, "width", ("w",), normalization_warnings, index)
            _move_alias(element, "height", ("h",), normalization_warnings, index)
            for target, aliases, size in (("x", ("cx", "center_x"), "width"), ("y", ("cy", "center_y"), "height")):
                for alias in aliases:
                    if alias not in element:
                        continue
                    center = element.pop(alias)
                    if target not in element and _number(center) is not None and _number(element.get(size)) is not None:
                        element[target] = _number(center) - _number(element[size]) / 2
                        _warning(normalization_warnings, index, f"normalized center {alias} -> top-left {target}")
                    elif target in element:
                        _warning(normalization_warnings, index, f"discarded alias {alias} because {target} already exists")
                    else:
                        _warning(normalization_warnings, index, f"could not normalize {alias} without numeric {size}")
        if element_type == "line":
            _move_alias(element, "x1", ("x_start",), normalization_warnings, index)
            _move_alias(element, "y1", ("y_start",), normalization_warnings, index)
            _move_alias(element, "x2", ("x_end",), normalization_warnings, index)
            _move_alias(element, "y2", ("y_end",), normalization_warnings, index)
            for point_key, x_key, y_key in (("start", "x1", "y1"), ("end", "x2", "y2")):
                point = element.pop(point_key, None)
                if isinstance(point, list) and len(point) == 2:
                    if x_key not in element:
                        element[x_key] = point[0]
                    if y_key not in element:
                        element[y_key] = point[1]
                    _warning(normalization_warnings, index, f"normalized {point_key} -> {x_key},{y_key}")
        if element_type == "line_group":
            _move_alias(element, "width", ("w",), normalization_warnings, index)
            _move_alias(element, "height", ("h",), normalization_warnings, index)
            _move_alias(element, "line_count", ("count", "lines"), normalization_warnings, index)
            _move_alias(element, "angle", ("direction",), normalization_warnings, index)
            if "angle" in element:
                element["angle"] = _normalize_direction(element["angle"])
            if "line_count" not in element and "density" in element:
                density = str(element["density"]).lower()
                if density in {"low", "medium", "high"}:
                    element["line_count"] = {"low": 5, "medium": 10, "high": 16}[density]
                    _warning(normalization_warnings, index, f"normalized density={density!r} -> line_count={element['line_count']}")
        if element_type == "grid_pattern":
            _move_alias(element, "rows", ("row_count",), normalization_warnings, index)
            _move_alias(element, "cols", ("col_count", "columns"), normalization_warnings, index)
        if element_type == "dot_grid":
            _move_alias(element, "width", ("w",), normalization_warnings, index)
            _move_alias(element, "height", ("h",), normalization_warnings, index)
            _move_alias(element, "rows", ("row_count",), normalization_warnings, index)
            _move_alias(element, "cols", ("col_count", "columns"), normalization_warnings, index)
            _move_alias(element, "dot_radius", ("dot_size", "dotRadius"), normalization_warnings, index)
        if element_type == "triangle_pattern":
            _move_alias(element, "count", ("number", "amount"), normalization_warnings, index)
            _move_alias(element, "size_min", ("min_size",), normalization_warnings, index)
            _move_alias(element, "size_max", ("max_size",), normalization_warnings, index)

        missing_color = (element_type in fill_types and "fill" not in element) or (element_type in stroke_types and "stroke" not in element)
        _default(element, "id", f"element-{index + 1}", normalization_warnings, index)
        _default(element, "role", "unknown", normalization_warnings, index)
        default_opacity = 0.45 if element.get("role") in {"background_support", "texture_group", "pattern_group"} else 1
        _default(element, "opacity", default_opacity, normalization_warnings, index)
        _default(element, "z_index", index, normalization_warnings, index)
        if element_type in fill_types:
            _default(element, "fill", _fallback_color(element, "fill"), normalization_warnings, index)
        if element_type in stroke_types:
            _default(element, "stroke", _fallback_color(element, "stroke"), normalization_warnings, index)
        if missing_color and element.get("role") in {"background_support", "texture_group", "pattern_group"} and _number(element.get("opacity")) is not None and _number(element["opacity"]) > 0.45:
            _set_number(element, "opacity", 0.45, normalization_warnings, index, "neutral fallback textures stay visually light")
        if element_type in stroke_width_types:
            _default(element, "stroke_width", 0.004, normalization_warnings, index)
        if element_type in {"ellipse", "rectangle", "triangle", "trapezoid", "dot_grid"}:
            _default(element, "rotation", 0, normalization_warnings, index)
        if element_type in {"line", "polyline", "curve_line"}:
            _default(element, "style", "solid", normalization_warnings, index)
        if element_type == "line_group":
            _default(element, "line_count", 10, normalization_warnings, index)
            _default(element, "spacing", 0.02, normalization_warnings, index)
        if element_type in {"grid_pattern", "dot_grid"}:
            _default(element, "rows", 4, normalization_warnings, index)
            _default(element, "cols", 6, normalization_warnings, index)
        if element_type == "dot_grid":
            _default(element, "dot_radius", 0.008, normalization_warnings, index)
        if element_type == "triangle":
            _default(element, "triangle_kind", "equilateral", normalization_warnings, index)
        if element_type == "trapezoid":
            _default(element, "top_ratio", 0.6, normalization_warnings, index)
        if element_type == "triangle_pattern":
            _default(element, "distribution", "scattered", normalization_warnings, index)

        for key in ("x", "y", "x1", "y1", "x2", "y2"):
            _clamp_number(element, key, 0, 1, normalization_warnings, index)
        for key in ("width", "height"):
            _clamp_number(element, key, 0.01, 1, normalization_warnings, index)
        for key in ("radius",):
            _clamp_number(element, key, 0.005, 1, normalization_warnings, index)
        for key in ("stroke_width", "spacing", "dot_radius", "size_min", "size_max", "randomness", "top_ratio"):
            _clamp_number(element, key, 0, 1, normalization_warnings, index)
        _clamp_number(element, "opacity", 0, 1, normalization_warnings, index)
        for key in ("line_count", "rows", "cols", "count"):
            _coerce_positive_int(element, key, normalization_warnings, index)
        if "z_index" in element and _number(element["z_index"]) is not None:
            coerced_z_index = int(_number(element["z_index"]))
            if element["z_index"] != coerced_z_index:
                _warning(normalization_warnings, index, f"coerced z_index: {element['z_index']!r} -> {coerced_z_index}")
            element["z_index"] = coerced_z_index
        if element_type == "line_group":
            _normalize_line_group_readability(element, normalization_warnings, index)

    _append_subject_quality_warnings(normalized, normalization_warnings)
    return normalized


@dataclass
class GenerationResult:
    status: str
    message: str
    raw_text: str
    valid: bool
    errors: list[dict[str, str]]
    document: dict | None
    normalized_payload: dict | None
    normalization_warnings: list[str]
    source_image: dict[str, int | float] | None = None
    error_type: str | None = None
    upstream_status: int | None = None
    upstream_body_preview: str = ""

    def as_dict(self) -> dict:
        return {
            "status": self.status,
            "message": self.message,
            "raw_text": self.raw_text,
            "valid": self.valid,
            "errors": self.errors,
            "document": self.document,
            "normalized_payload": self.normalized_payload,
            "normalization_warnings": self.normalization_warnings,
            "source_image": self.source_image,
            "error_type": self.error_type,
            "upstream_status": self.upstream_status,
            "upstream_body_preview": self.upstream_body_preview,
        }


class CompositionParamGenerationService:
    def __init__(self, generate_text: Callable[[str | Path, str | None], str] | None = None) -> None:
        self.generate_text = generate_text or qwen_client.generate

    def generate(self, image_path: str | Path, user_hint: str | None = None) -> GenerationResult:
        source_image = read_source_image_info(image_path)
        forced_canvas = canvas_for_source(source_image) if source_image else None
        raw_text = self.generate_text(image_path, user_hint)
        try:
            payload = extract_json_payload(raw_text)
        except json.JSONDecodeError as exc:
            return GenerationResult("error", "Qwen 返回内容不是合法 JSON", raw_text, False, [{"path": "", "message": f"JSON parse error: {exc.msg} at line {exc.lineno} column {exc.colno}"}], None, None, [], source_image, "qwen_non_json_response")
        if not isinstance(payload, dict):
            return GenerationResult("error", "Qwen 返回 JSON 顶层必须是对象", raw_text, False, [{"path": "", "message": "document must be a JSON object"}], None, None, [], source_image, "schema_validation_error")
        normalization_warnings: list[str] = []
        normalized_payload = normalize_composition_param_payload(payload, normalization_warnings, forced_canvas)
        try:
            document = CompositionParamDocument.model_validate(normalized_payload)
        except ValidationError as exc:
            return GenerationResult("error", "Qwen 返回 JSON 未通过 CompositionParamDocument schema 校验", raw_text, False, format_validation_errors(exc), None, normalized_payload, normalization_warnings, source_image, "schema_validation_error")
        return GenerationResult("success", "参数 JSON 草案生成成功", raw_text, True, [], document.model_dump(), normalized_payload, normalization_warnings, source_image)
