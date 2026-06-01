from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from pydantic import ValidationError
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.schemas.request_models import ExtractElementsRequest
from app.schemas.response_models import ExtractElementsResponse, HealthResponse
from app.services.element_extract_service import ElementExtractService, ExtractConfig, ExtractError
from app.schemas.composition_param_models import CompositionParamDocument
from app.services.composition_param_generation_service import (
    CompositionParamGenerationService,
    QwenConfigurationError,
    QwenRequestError,
    format_validation_errors,
)

app = FastAPI(title="Composition Lab API", version="0.3.0")

ALLOWED_UPLOAD_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}
UPLOAD_DIR = Path("static/uploads")
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
extract_service = ElementExtractService()
param_generation_service = CompositionParamGenerationService()
MAX_REFERENCE_IMAGE_BYTES = 10 * 1024 * 1024


def generation_error_response(
    status_code: int,
    error_type: str,
    message: str,
    *,
    errors: list[dict[str, str]] | None = None,
    upstream_status: int | None = None,
    upstream_body_preview: str = "",
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "status": "error",
            "error_type": error_type,
            "message": message,
            "raw_text": "",
            "upstream_status": upstream_status,
            "upstream_body_preview": upstream_body_preview[:500],
            "valid": False,
            "document": None,
            "normalized_payload": None,
            "normalization_warnings": [],
            "errors": errors or [{"path": "", "message": message}],
            "source_image": None,
        },
    )


@app.get("/health", response_model=HealthResponse)
def health() -> dict:
    return {"status": "ok", "message": "service is running"}


@app.get("/composition", response_class=HTMLResponse)
def composition() -> HTMLResponse:
    html = Path("app/templates/composition.html").read_text(encoding="utf-8")
    return HTMLResponse(content=html)


@app.get("/composition-layer-test", response_class=HTMLResponse)
def composition_layer_test() -> HTMLResponse:
    html = Path("app/templates/composition_layer_test.html").read_text(encoding="utf-8")
    return HTMLResponse(content=html)




@app.get("/composition-reference-test", response_class=HTMLResponse)
def composition_reference_test() -> HTMLResponse:
    html = Path("app/templates/composition_reference_test.html").read_text(encoding="utf-8")
    return HTMLResponse(content=html)


@app.get("/composition-param-test", response_class=HTMLResponse)
def composition_param_test() -> HTMLResponse:
    html = Path("app/templates/composition_param_test.html").read_text(encoding="utf-8")
    return HTMLResponse(content=html)


@app.post("/composition/validate-param-json")
def validate_param_json(payload: dict) -> dict:
    try:
        document = CompositionParamDocument.model_validate(payload)
        return {
            "valid": True,
            "message": "JSON 合法",
            "element_count": len(document.elements),
            "warnings": [],
        }
    except ValidationError as exc:
        return {"valid": False, "message": "JSON 不合法", "errors": format_validation_errors(exc), "warnings": []}


@app.post("/composition/generate-param-json")
async def composition_generate_param_json(
    image: UploadFile | None = File(default=None),
    user_hint: str | None = Form(default=None),
):
    if image is None or not image.filename:
        return generation_error_response(400, "missing_image", "未上传图片")
    ext = Path(image.filename).suffix.lower()
    if ext not in ALLOWED_UPLOAD_EXTENSIONS:
        return generation_error_response(400, "unsupported_file_type", "不支持的图片格式")
    content = await image.read()
    if not content:
        return generation_error_response(400, "missing_image", "未上传图片")
    if len(content) > MAX_REFERENCE_IMAGE_BYTES:
        return generation_error_response(400, "invalid_image", "上传图片过大，最大允许 10 MB")
    save_name = f"reference-{uuid4().hex}{ext}"
    save_path = UPLOAD_DIR / save_name
    try:
        save_path.write_bytes(content)
    except OSError as exc:
        return generation_error_response(500, "internal_error", "参考图保存失败", errors=[{"path": "image", "message": str(exc)}])
    try:
        return param_generation_service.generate(save_path, user_hint).as_dict()
    except QwenConfigurationError as exc:
        return generation_error_response(503, "qwen_api_error", "Qwen API 调用失败", errors=[{"path": "QWEN_API_KEY", "message": str(exc)}])
    except QwenRequestError as exc:
        return generation_error_response(502, "qwen_api_error", "Qwen API 调用失败", errors=[{"path": "qwen", "message": str(exc)}], upstream_status=exc.upstream_status, upstream_body_preview=exc.upstream_body_preview)
    except Exception as exc:
        return generation_error_response(500, "internal_error", "参数 JSON 生成服务异常", errors=[{"path": "server", "message": str(exc)}])


@app.post("/upload-image")
async def upload_image(file: UploadFile = File(...)) -> dict:
    if not file.filename:
        return {"status": "error", "message": "文件为空"}

    ext = Path(file.filename).suffix.lower()
    if ext not in ALLOWED_UPLOAD_EXTENSIONS:
        return {"status": "error", "message": "文件格式不支持，仅支持 png/jpg/jpeg/webp"}

    content = await file.read()
    if not content:
        return {"status": "error", "message": "文件为空"}

    save_name = f"{uuid4().hex}{ext}"
    save_path = UPLOAD_DIR / save_name

    try:
        save_path.write_bytes(content)
    except OSError:
        return {"status": "error", "message": "保存失败"}

    display_url = f"/static/uploads/{save_name}"
    return {
        "status": "success",
        "message": "图片上传成功",
        "original_image_url": str(save_path),
        "original_image_display_url": display_url,
        "current_image_url": str(save_path),
        "current_image_display_url": display_url,
        "image_url": str(save_path),
        "display_url": display_url,
    }


@app.post("/composition/extract-elements", response_model=ExtractElementsResponse)
def composition_extract_elements(payload: ExtractElementsRequest) -> dict:
    try:
        return extract_service.extract(payload.image_url, ExtractConfig(payload.max_layers, payload.min_area))
    except ExtractError as exc:
        return {
            "status": "error",
            "message": str(exc),
            "image_url": payload.image_url,
            "canvas_width": 0,
            "canvas_height": 0,
            "layer_count": 0,
            "layers": [],
            "debug": {
                "background_rgb": [255, 255, 255],
                "foreground_coverage": 0.0,
                "debug_mask_url": "",
                "debug_overlay_url": "",
                "warnings": [str(exc)],
                "extraction_stats": {
                    "raw_component_count": 0,
                    "kept_component_count": 0,
                    "ignored_noise_count": 0,
                    "small_group_count": 0,
                    "oversized_component_count": 0,
                    "color_bucket_count": 0,
                },
            },
        }


app.mount("/static", StaticFiles(directory="static"), name="static")
