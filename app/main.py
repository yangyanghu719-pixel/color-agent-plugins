from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, File, UploadFile
from pydantic import ValidationError
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from app.schemas.request_models import ExtractElementsRequest
from app.schemas.response_models import ExtractElementsResponse, HealthResponse
from app.services.element_extract_service import ElementExtractService, ExtractConfig, ExtractError
from app.schemas.composition_param_models import CompositionParamDocument

app = FastAPI(title="Composition Lab API", version="0.3.0")

ALLOWED_UPLOAD_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}
UPLOAD_DIR = Path("static/uploads")
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
extract_service = ElementExtractService()


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
        errors = []
        for e in exc.errors():
            loc = []
            for part in e.get("loc", []):
                if isinstance(part, int):
                    loc[-1] = f"{loc[-1]}[{part}]"
                else:
                    loc.append(str(part))
            errors.append({"path": ".".join(loc), "message": e.get("msg", "invalid")})
        return {"valid": False, "message": "JSON 不合法", "errors": errors, "warnings": []}

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
