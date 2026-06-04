from pathlib import Path
import logging
import mimetypes
import urllib.parse
from uuid import uuid4
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image, UnidentifiedImageError

from app.schemas.request_models import ExtractElementsRequest
from app.schemas.response_models import ExtractElementsResponse, HealthResponse
from app.services.element_extract_service import ElementExtractService, ExtractConfig, ExtractError
from app.services.composition_param_generation_service import (
    CompositionParamGenerationService,
    QwenConfigurationError,
    QwenRequestError,
    sanitize_composition_document,
)
from app.services.aliyun_workflow_param_generation_service import (
    AliyunWorkflowParamGenerationService,
    WorkflowConfigurationError,
    WorkflowParseError,
    WorkflowRequestError,
    build_local_file_image_url_check,
    check_public_image_url_async,
)

logger = logging.getLogger(__name__)


def startup_log(message: str) -> None:
    print(f"[composition-lab startup] {message}", flush=True)
    logger.info("[composition-lab startup] %s", message)


startup_log("before creating FastAPI app")
app = FastAPI(title="Composition Lab API", version="0.3.0")
startup_log("after creating FastAPI app")

ALLOWED_UPLOAD_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}
UPLOAD_DIR = Path("static/uploads")
WORKFLOW_INPUT_DIR = UPLOAD_DIR / "workflow_inputs"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
WORKFLOW_INPUT_DIR.mkdir(parents=True, exist_ok=True)
startup_log("upload directories ensured with mkdir only")
MAX_REFERENCE_IMAGE_BYTES = 10 * 1024 * 1024


class LazyServiceProxy:
    def __init__(self, factory, name: str) -> None:
        object.__setattr__(self, "_factory", factory)
        object.__setattr__(self, "_name", name)
        object.__setattr__(self, "_instance", None)

    def _get(self):
        instance = object.__getattribute__(self, "_instance")
        if instance is None:
            name = object.__getattribute__(self, "_name")
            startup_log(f"creating {name} lazily")
            instance = object.__getattribute__(self, "_factory")()
            object.__setattr__(self, "_instance", instance)
        return instance

    def __getattr__(self, name: str):
        return getattr(self._get(), name)

    def __setattr__(self, name: str, value) -> None:
        if name.startswith("_"):
            object.__setattr__(self, name, value)
            return
        setattr(self._get(), name, value)


extract_service = LazyServiceProxy(ElementExtractService, "ElementExtractService")
param_generation_service = LazyServiceProxy(CompositionParamGenerationService, "CompositionParamGenerationService")
workflow_param_generation_service = LazyServiceProxy(AliyunWorkflowParamGenerationService, "AliyunWorkflowParamGenerationService")


def get_extract_service() -> ElementExtractService:
    return extract_service._get()


def get_param_generation_service() -> CompositionParamGenerationService:
    return param_generation_service._get()


def get_workflow_param_generation_service() -> AliyunWorkflowParamGenerationService:
    return workflow_param_generation_service._get()


def get_saved_image_debug(save_path: Path, content: bytes, content_type: str | None = None) -> dict[str, Any]:
    debug = {
        "image_size_bytes": len(content),
        "image_mime_type": content_type or mimetypes.guess_type(save_path.name)[0] or "",
        "source_width": None,
        "source_height": None,
    }
    try:
        with Image.open(save_path) as img:
            debug["source_width"] = img.width
            debug["source_height"] = img.height
            debug["image_mime_type"] = Image.MIME.get(img.format, debug["image_mime_type"])
    except (UnidentifiedImageError, OSError):
        pass
    return debug


def is_same_public_host(image_url: str, public_base_url: str) -> bool:
    image_host = urllib.parse.urlparse(image_url).netloc.lower()
    public_host = urllib.parse.urlparse(public_base_url).netloc.lower()
    return bool(image_host and public_host and image_host == public_host)


async def build_workflow_image_debug(
    *,
    image_url: str,
    public_base_url: str,
    save_path: Path,
    content: bytes,
    content_type: str | None = None,
) -> dict[str, Any]:
    debug = get_saved_image_debug(save_path, content, content_type)
    if is_same_public_host(image_url, public_base_url):
        debug.update(build_local_file_image_url_check(image_url, save_path))
    else:
        debug.update(await check_public_image_url_async(image_url))
    return debug


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


def workflow_error_response(
    status_code: int,
    message: str,
    *,
    image_url: str = "",
    raw_workflow_response: Any | None = None,
    raw_text: str = "",
    errors: list[dict[str, str]] | None = None,
    upstream_status: int | None = None,
    upstream_body_preview: str = "",
    upstream_debug: dict[str, Any] | None = None,
) -> JSONResponse:
    debug = upstream_debug or {
        "request_id": None,
        "status_code": upstream_status,
        "chunk_count": 0,
        "first_chunk_ms": None,
        "total_elapsed_ms": None,
        "finish_reason": None,
        "error_message": message,
    }
    return JSONResponse(
        status_code=status_code,
        content={
            "ok": False,
            "valid": False,
            "message": message,
            "image_url": image_url,
            "public_image_url": image_url,
            "raw_workflow_response": raw_workflow_response,
            "raw_text": raw_text,
            "raw_text_preview": raw_text[:1000] if raw_text else upstream_body_preview[:1000],
            "document": None,
            "textarea_json": "",
            "warnings": [],
            "dropped_elements": [],
            "strict_validation": {"valid": False, "errors": errors or [{"path": "", "message": message}]},
            "errors": errors or [{"path": "", "message": message}],
            "upstream_status": upstream_status if upstream_status is not None else debug.get("status_code"),
            "upstream_body_preview": upstream_body_preview[:1000],
            "upstream_debug": debug,
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


@app.get("/composition-workflow-test", response_class=HTMLResponse)
def composition_workflow_test() -> HTMLResponse:
    html = Path("app/templates/composition_workflow_test.html").read_text(encoding="utf-8")
    return HTMLResponse(content=html)


@app.post("/composition/validate-param-json")
def validate_param_json(payload: dict) -> dict:
    return sanitize_composition_document(payload)


@app.post("/composition/application-health-check")
def composition_application_health_check() -> dict:
    aggregation = get_workflow_param_generation_service().call_application("", "请只回复 OK", stream=False, image_debug={"health_check": True}, skip_image_check=True)
    return {
        "ok": "OK" in aggregation.raw_text.upper(),
        "raw_text": aggregation.raw_text,
        "raw_text_length": len(aggregation.raw_text),
        "app_endpoint_url": aggregation.upstream_debug.get("endpoint_url"),
        "app_id_masked": aggregation.upstream_debug.get("app_id_masked"),
        "upstream_debug": aggregation.upstream_debug,
    }


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
        return get_param_generation_service().generate(save_path, user_hint).as_dict()
    except QwenConfigurationError as exc:
        return generation_error_response(503, "qwen_api_error", "Qwen API 调用失败", errors=[{"path": "QWEN_API_KEY", "message": str(exc)}])
    except QwenRequestError as exc:
        return generation_error_response(502, "qwen_api_error", "Qwen API 调用失败", errors=[{"path": "qwen", "message": str(exc)}], upstream_status=exc.upstream_status, upstream_body_preview=exc.upstream_body_preview)
    except Exception as exc:
        return generation_error_response(500, "internal_error", "参数 JSON 生成服务异常", errors=[{"path": "server", "message": str(exc)}])


@app.post("/composition/generate-param-json-by-workflow")
async def composition_generate_param_json_by_workflow(
    image: UploadFile | None = File(default=None),
    user_hint: str | None = Form(default=None),
):
    if image is None or not image.filename:
        return workflow_error_response(400, "上传文件缺失")
    ext = Path(image.filename).suffix.lower()
    if ext not in ALLOWED_UPLOAD_EXTENSIONS:
        return workflow_error_response(400, "文件类型不支持，仅支持 jpg/jpeg/png/webp")
    content = await image.read()
    if not content:
        return workflow_error_response(400, "上传文件缺失")
    if len(content) > MAX_REFERENCE_IMAGE_BYTES:
        return workflow_error_response(400, "上传图片过大，最大允许 10 MB")
    save_name = f"workflow-input-{uuid4().hex}{ext}"
    save_path = WORKFLOW_INPUT_DIR / save_name
    try:
        save_path.write_bytes(content)
    except OSError as exc:
        return workflow_error_response(500, "图片保存失败", errors=[{"path": "image", "message": str(exc)}])
    public_image_url = f"https://composition-lab.onrender.com/static/uploads/workflow_inputs/{save_name}"
    prompt = (user_hint or "").strip() or "go"
    app_id_exists = bool(get_workflow_param_generation_service()._env("ALIYUN_APPLICATION_ID"))
    api_key_exists = bool(get_workflow_param_generation_service()._env("ALIYUN_API_KEY"))
    print(f"[workflow adapter] received filename: {image.filename}", flush=True)
    print(f"[workflow adapter] saved local path: {save_path}", flush=True)
    print(f"[workflow adapter] public_image_url: {public_image_url}", flush=True)
    print(f"[workflow adapter] prompt: {prompt}", flush=True)
    print(f"[workflow adapter] app_id_exists: {app_id_exists}; api_key_exists: {api_key_exists}", flush=True)
    try:
        result = get_workflow_param_generation_service().generate_minimal_dashscope_app_json(public_image_url, prompt)
        body = result.as_dict()
        body["public_image_url"] = public_image_url
        body["raw_text_preview"] = result.raw_text[:1000]
        body["image_url"] = public_image_url
        return body
    except WorkflowConfigurationError as exc:
        return workflow_error_response(503, "调用阿里云智能体应用失败：环境变量未配置", image_url=public_image_url, errors=[{"path": "env", "message": str(exc)}])
    except WorkflowRequestError as exc:
        return workflow_error_response(502, "调用阿里云智能体应用失败", image_url=public_image_url, errors=[{"path": "application", "message": str(exc)}], upstream_status=exc.upstream_status, upstream_body_preview=exc.upstream_body_preview, upstream_debug=exc.upstream_debug)
    except WorkflowParseError as exc:
        return workflow_error_response(502, str(exc), image_url=public_image_url, raw_workflow_response=exc.raw_workflow_response, raw_text=exc.raw_text, errors=exc.errors, upstream_debug=exc.upstream_debug)
    except Exception as exc:
        return workflow_error_response(500, "智能体应用参数 JSON 生成服务异常", image_url=public_image_url, errors=[{"path": "server", "message": str(exc)}])


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
        return get_extract_service().extract(payload.image_url, ExtractConfig(payload.max_layers, payload.min_area))
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


startup_log(f"after registering routes ({len(app.routes)} routes before static mount)")
app.mount("/static", StaticFiles(directory="static"), name="static")
startup_log("after mounting static files")
