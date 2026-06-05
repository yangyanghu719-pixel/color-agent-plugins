from pathlib import Path
import base64
import binascii
from datetime import datetime, timezone
import json
import logging
import mimetypes
import os
import re
import urllib.parse
from uuid import uuid4
from typing import Any

import requests

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.concurrency import run_in_threadpool
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
from app.services.aliyun_app_chat_test_service import default_upstream_debug, AliyunAppChatTestService
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
DEFAULT_OPERATION_GITHUB_REPO = "yangyanghu719-pixel/color-agent-plugins"
DEFAULT_OPERATION_GITHUB_BRANCH = "composition-lab-data"
DEFAULT_OPERATION_GITHUB_BASE_DIR = "backend_data_storage"
BACKEND_DATA_STORAGE_DIR = Path(DEFAULT_OPERATION_GITHUB_BASE_DIR)
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
WORKFLOW_INPUT_DIR.mkdir(parents=True, exist_ok=True)
BACKEND_DATA_STORAGE_DIR.mkdir(parents=True, exist_ok=True)
startup_log("upload directories ensured with mkdir only")
MAX_REFERENCE_IMAGE_BYTES = 10 * 1024 * 1024
MAX_AB_COMPOSITION_IMAGE_BYTES = 7 * 1024 * 1024
DATA_URL_PATTERN = re.compile(r"^data:(image/(?:png|jpeg|jpg|webp));base64,(.+)$", re.IGNORECASE | re.DOTALL)
GITHUB_CONTENTS_API = "https://api.github.com/repos/{repo}/contents/{path}"


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
aliyun_app_chat_test_service = LazyServiceProxy(AliyunAppChatTestService, "AliyunAppChatTestService")


def get_extract_service() -> ElementExtractService:
    return extract_service._get()


def get_param_generation_service() -> CompositionParamGenerationService:
    return param_generation_service._get()


def get_workflow_param_generation_service() -> AliyunWorkflowParamGenerationService:
    return workflow_param_generation_service._get()


def get_aliyun_app_chat_test_service() -> AliyunAppChatTestService:
    return aliyun_app_chat_test_service._get()



def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def safe_task_id(value: Any | None = None) -> str:
    raw = str(value or "").strip()
    if raw and re.fullmatch(r"[A-Za-z0-9_-]{1,80}", raw):
        return raw
    return uuid4().hex[:12]


def github_operation_config() -> dict[str, str]:
    return {
        "token": os.getenv("GITHUB_OPERATION_TOKEN", "").strip(),
        "repo": os.getenv("GITHUB_OPERATION_REPO", DEFAULT_OPERATION_GITHUB_REPO).strip(),
        "branch": os.getenv("GITHUB_OPERATION_BRANCH", DEFAULT_OPERATION_GITHUB_BRANCH).strip(),
        "base_dir": os.getenv("GITHUB_OPERATION_BASE_DIR", DEFAULT_OPERATION_GITHUB_BASE_DIR).strip().strip("/"),
    }


def safe_github_path_part(value: str) -> str:
    cleaned = re.sub(r"[^0-9A-Za-z_\-\u4e00-\u9fff]+", "_", value).strip("_")
    return cleaned or "未命名"


def timestamp_file_prefix(value: str | None = None) -> str:
    text = (value or utc_now_iso()).replace(":", "-").replace("+00-00", "Z").replace("+", "Z")
    return re.sub(r"[^0-9A-Za-z_.\-]+", "-", text)


def task_artifact_folder(task_id: str) -> str:
    return f"upload_{safe_github_path_part(task_id)}"


def current_save_timestamp() -> str:
    return timestamp_file_prefix(utc_now_iso())


def json_render_stem(value: Any | None = None) -> str:
    text = str(value or "").strip()
    if re.fullmatch(r"JSON_[0-9A-Za-z_.\-]+", text):
        return text
    return f"JSON_{current_save_timestamp()}"


def analysis_save_stem(kind: str = "composition", value: Any | None = None) -> str:
    text = str(value or "").strip()
    prefix = "色彩分析" if kind == "color" else "构图分析"
    if re.fullmatch(rf"{prefix}_[0-9A-Za-z_.\-]+", text):
        return text
    return f"{prefix}_{current_save_timestamp()}"


def github_contents_url(repo: str, repo_path: str) -> str:
    return GITHUB_CONTENTS_API.format(repo=repo, path=urllib.parse.quote(repo_path, safe="/"))


def github_put_file(repo_path: str, content: bytes, commit_message: str) -> dict[str, Any]:
    config = github_operation_config()
    if not config["token"]:
        return {"enabled": False, "message": "未配置 GITHUB_OPERATION_TOKEN，已仅保存到服务器本地 backend_data_storage 目录"}
    url = github_contents_url(config["repo"], repo_path)
    headers = {
        "Authorization": f"Bearer {config['token']}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    params = {"ref": config["branch"]}
    payload: dict[str, Any] = {
        "message": commit_message,
        "content": base64.b64encode(content).decode("ascii"),
        "branch": config["branch"],
    }
    try:
        existing = requests.get(url, headers=headers, params=params, timeout=20)
        if existing.status_code == 200:
            sha = existing.json().get("sha")
            if sha:
                payload["sha"] = sha
        elif existing.status_code not in {404, 422}:
            return {"enabled": True, "ok": False, "status_code": existing.status_code, "message": existing.text[:500]}
        response = requests.put(url, headers=headers, json=payload, timeout=30)
        return {"enabled": True, "ok": 200 <= response.status_code < 300, "status_code": response.status_code, "repo_path": repo_path, "message": response.text[:500]}
    except requests.RequestException as exc:
        return {"enabled": True, "ok": False, "repo_path": repo_path, "message": str(exc)}


def should_delete_local_after_github_sync(github_result: dict[str, Any]) -> bool:
    if not github_result.get("enabled") or not github_result.get("ok"):
        return False
    value = os.getenv("GITHUB_OPERATION_DELETE_LOCAL_AFTER_SYNC", "true").strip().lower()
    return value not in {"0", "false", "no", "off"}


def write_operation_artifact(task_id: Any | None, relative_path: str, content: bytes | str, commit_message: str) -> dict[str, Any]:
    task_key = safe_task_id(task_id)
    content_bytes = content.encode("utf-8") if isinstance(content, str) else content
    safe_relative_path = Path(relative_path).as_posix().lstrip("/")
    local_path = BACKEND_DATA_STORAGE_DIR / task_artifact_folder(task_key) / safe_relative_path
    local_path.parent.mkdir(parents=True, exist_ok=True)
    local_path.write_bytes(content_bytes)
    config = github_operation_config()
    repo_path = f"{config['base_dir']}/{task_artifact_folder(task_key)}/{safe_relative_path}".strip("/")
    github_result = github_put_file(repo_path, content_bytes, commit_message)
    if should_delete_local_after_github_sync(github_result):
        local_path.unlink(missing_ok=True)
    return {"task_id": task_key, "local_path": str(local_path), "repo_path": repo_path, "github": github_result}


def write_operation_text_artifact(task_id: Any | None, relative_path: str, text: str, commit_message: str) -> dict[str, Any]:
    return write_operation_artifact(task_id, relative_path, text, commit_message)


def write_completed_ab_analysis_artifacts(
    *,
    task_id: str,
    image_a_url: str,
    image_b_url: str,
    analysis_text: str,
    json_save_id: Any | None = None,
    analysis_save_id: Any | None = None,
    kind: str = "composition",
) -> dict[str, Any]:
    json_stem = json_render_stem(json_save_id)
    analysis_stem = analysis_save_stem(kind, analysis_save_id)
    saved: dict[str, Any] = {"json_save_id": json_stem, "analysis_save_id": analysis_stem, "artifacts": []}
    image_a = read_workflow_public_image(image_a_url)
    image_b = read_workflow_public_image(image_b_url)
    if image_a:
        content, _ext = image_a
        saved["artifacts"].append(write_operation_artifact(
            task_id,
            f"{json_stem}/{analysis_stem}_图片A.png",
            content,
            f"Save {kind} analysis image A {analysis_stem} for {task_id}",
        ))
    if image_b:
        content, _ext = image_b
        saved["artifacts"].append(write_operation_artifact(
            task_id,
            f"{json_stem}/{analysis_stem}_图片B.png",
            content,
            f"Save {kind} analysis image B {analysis_stem} for {task_id}",
        ))
    saved["artifacts"].append(write_operation_text_artifact(
        task_id,
        f"{json_stem}/{analysis_stem}_分析结果.md",
        analysis_text,
        f"Save {kind} analysis result {analysis_stem} for {task_id}",
    ))
    return saved

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



def aliyun_app_chat_test_public_workflow_url(save_name: str) -> str:
    return f"https://composition-lab.onrender.com/static/uploads/workflow_inputs/{save_name}"


def is_allowed_ab_image_url(image_url: str) -> bool:
    parsed = urllib.parse.urlparse(image_url)
    return (
        parsed.scheme == "https"
        and parsed.netloc.lower() == "composition-lab.onrender.com"
        and parsed.path.startswith("/static/uploads/workflow_inputs/")
        and Path(parsed.path).suffix.lower() in ALLOWED_UPLOAD_EXTENSIONS
    )


def workflow_public_url_to_local_path(image_url: str) -> Path | None:
    if not is_allowed_ab_image_url(image_url):
        return None
    filename = Path(urllib.parse.urlparse(image_url).path).name
    candidate = WORKFLOW_INPUT_DIR / filename
    try:
        candidate.relative_to(WORKFLOW_INPUT_DIR)
    except ValueError:
        return None
    return candidate


def read_workflow_public_image(image_url: str) -> tuple[bytes, str] | None:
    local_path = workflow_public_url_to_local_path(image_url)
    if not local_path or not local_path.exists():
        return None
    return local_path.read_bytes(), local_path.suffix.lower() or ".png"



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


def aliyun_app_chat_test_error_response(
    status_code: int,
    message: str,
    *,
    public_image_url: str = "",
    request_debug: dict[str, Any] | None = None,
    upstream_status: int | None = None,
    full_raw_preview: str = "",
    upstream_debug: dict[str, Any] | None = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "ok": False,
            "error": message,
            "message": message,
            "public_image_url": public_image_url,
            "upstream_status": upstream_status,
            "sse_event_count": 0,
            "text_mode": "snapshot_latest_text",
            "final_text": "",
            "final_text_length": 0,
            "raw_text_preview": full_raw_preview[:1200],
            "textarea_json": "",
            "parsed_json": None,
            "recent_data_previews": [],
            "request_debug": request_debug or {},
            "raw_sse_data_lines": [],
            "parsed_events": [],
            "text_fragments": [],
            "full_raw_preview": full_raw_preview,
            "upstream_debug": upstream_debug or default_upstream_debug(message),
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



@app.get("/aliyun-app-chat-test", response_class=HTMLResponse)
def aliyun_app_chat_test() -> HTMLResponse:
    html = Path("app/templates/aliyun_app_chat_test.html").read_text(encoding="utf-8")
    return HTMLResponse(content=html)


@app.post("/aliyun-app-chat-test/send")
async def aliyun_app_chat_test_send(
    image: UploadFile | None = File(default=None),
    prompt: str | None = Form(default="go"),
    task_id: str | None = Form(default=None),
):
    if image is None or not image.filename:
        return aliyun_app_chat_test_error_response(400, "请上传图片（png/jpg/jpeg/webp）")
    ext = Path(image.filename).suffix.lower()
    if ext not in ALLOWED_UPLOAD_EXTENSIONS:
        return aliyun_app_chat_test_error_response(400, "文件类型不支持，仅支持 png/jpg/jpeg/webp")
    content = await image.read()
    if not content:
        return aliyun_app_chat_test_error_response(400, "上传文件为空")
    task_key = safe_task_id(task_id)
    save_name = f"aliyun-app-input-{uuid4().hex}{ext}"
    save_path = WORKFLOW_INPUT_DIR / save_name
    public_image_url = aliyun_app_chat_test_public_workflow_url(save_name)
    try:
        save_path.write_bytes(content)
    except OSError as exc:
        return aliyun_app_chat_test_error_response(500, "图片保存失败", public_image_url=public_image_url, upstream_debug=default_upstream_debug(str(exc)))
    print(
        "[aliyun-app-chat-test] upload debug",
        {
            "filename": save_name,
            "local_saved_path": str(save_path),
            "public_image_url": public_image_url,
            "prompt": (prompt or "").strip() or "go",
        },
        flush=True,
    )
    write_operation_artifact(
        task_key,
        f"upload_{task_key}{ext}",
        content,
        f"Save manual upload for {task_key}",
    )
    result = await run_in_threadpool(
        get_aliyun_app_chat_test_service().call,
        public_image_url,
        prompt,
        filename=save_name,
        local_saved_path=str(save_path),
    )
    body = result.as_dict()
    body["task_id"] = task_key
    status_code = 200 if result.ok else 502
    error_message = result.upstream_debug.get("error_message")
    if result.upstream_status is None and isinstance(error_message, str) and error_message.startswith("缺少环境变量"):
        status_code = 503
    return JSONResponse(status_code=status_code, content=body)


@app.post("/aliyun-app-chat-test/save-rendered-json-canvas")
async def aliyun_app_chat_test_save_rendered_json_canvas(payload: dict[str, Any]):
    data_url = str(payload.get("data_url") or "")
    match = DATA_URL_PATTERN.match(data_url)
    if not match:
        return JSONResponse(status_code=400, content={"ok": False, "message": "请提交 png/jpeg/webp 的 data URL"})
    mime_type = match.group(1).lower().replace("image/jpg", "image/jpeg")
    try:
        content = base64.b64decode(match.group(2), validate=True)
    except (binascii.Error, ValueError):
        return JSONResponse(status_code=400, content={"ok": False, "message": "图片数据不是有效的 base64"})
    if not content:
        return JSONResponse(status_code=400, content={"ok": False, "message": "图片数据为空"})
    if len(content) > MAX_AB_COMPOSITION_IMAGE_BYTES:
        return JSONResponse(status_code=413, content={"ok": False, "message": "图片超过 7MB，请缩小画布后再保存"})

    task_key = safe_task_id(payload.get("task_id"))
    json_stem = json_render_stem(payload.get("json_save_id"))
    image_artifact = write_operation_artifact(
        task_key,
        f"{json_stem}.png",
        content,
        f"Save rendered JSON canvas {json_stem} for {task_key}",
    )
    textarea_json = str(payload.get("textarea_json") or "").strip()
    json_artifact = None
    if textarea_json:
        json_artifact = write_operation_text_artifact(
            task_key,
            f"{json_stem}/{json_stem}.json",
            textarea_json,
            f"Save JSON source {json_stem} for {task_key}",
        )
    return {
        "ok": True,
        "message": "JSON 渲染画布已保存",
        "task_id": task_key,
        "json_save_id": json_stem,
        "artifact_path": image_artifact["repo_path"],
        "json_artifact_path": json_artifact["repo_path"] if json_artifact else "",
        "mime_type": mime_type,
        "size_bytes": len(content),
    }


@app.post("/aliyun-app-chat-test/save-composition-image")
async def aliyun_app_chat_test_save_composition_image(payload: dict[str, Any]):
    slot = str(payload.get("slot") or "").upper()
    if slot not in {"A", "B"}:
        return JSONResponse(status_code=400, content={"ok": False, "message": "slot 必须是 A 或 B"})
    data_url = str(payload.get("data_url") or "")
    match = DATA_URL_PATTERN.match(data_url)
    if not match:
        return JSONResponse(status_code=400, content={"ok": False, "message": "请提交 png/jpeg/webp 的 data URL"})
    mime_type = match.group(1).lower().replace("image/jpg", "image/jpeg")
    try:
        content = base64.b64decode(match.group(2), validate=True)
    except (binascii.Error, ValueError):
        return JSONResponse(status_code=400, content={"ok": False, "message": "图片数据不是有效的 base64"})
    if not content:
        return JSONResponse(status_code=400, content={"ok": False, "message": "图片数据为空"})
    if len(content) > MAX_AB_COMPOSITION_IMAGE_BYTES:
        return JSONResponse(status_code=413, content={"ok": False, "message": "图片超过 7MB，请缩小画布后再保存"})
    ext = ".jpg" if mime_type == "image/jpeg" else f".{mime_type.rsplit('/', 1)[-1]}"
    save_name = f"composition-ab-{slot.lower()}-{uuid4().hex}{ext}"
    save_path = WORKFLOW_INPUT_DIR / save_name
    try:
        save_path.write_bytes(content)
    except OSError:
        return JSONResponse(status_code=500, content={"ok": False, "message": "保存 A/B 图片失败"})
    task_key = safe_task_id(payload.get("task_id"))
    return {
        "ok": True,
        "message": f"图 {slot} 已保存",
        "slot": slot,
        "task_id": task_key,
        "public_image_url": aliyun_app_chat_test_public_workflow_url(save_name),
        "static_path": f"/static/uploads/workflow_inputs/{save_name}",
        "mime_type": mime_type,
        "size_bytes": len(content),
    }


@app.post("/aliyun-app-chat-test/analyze-ab")
async def aliyun_app_chat_test_analyze_ab(payload: dict[str, Any]):
    image_a_url = str(payload.get("image_a_url") or "").strip()
    image_b_url = str(payload.get("image_b_url") or "").strip()
    if not image_a_url or not image_b_url:
        return JSONResponse(status_code=400, content={"ok": False, "message": "请先分别保存图 A 和图 B"})
    if not is_allowed_ab_image_url(image_a_url) or not is_allowed_ab_image_url(image_b_url):
        return JSONResponse(status_code=400, content={"ok": False, "message": "A/B 图片 URL 必须来自当前页面保存的公网图片"})
    task_key = safe_task_id(payload.get("task_id"))
    result = await run_in_threadpool(get_aliyun_app_chat_test_service().analyze_composition_ab, image_a_url, image_b_url)
    analysis_text = result.analysis if result.ok else result.message
    completed_artifacts = (
        write_completed_ab_analysis_artifacts(
            task_id=task_key,
            image_a_url=image_a_url,
            image_b_url=image_b_url,
            analysis_text=analysis_text,
            json_save_id=payload.get("json_save_id"),
            analysis_save_id=payload.get("analysis_save_id"),
            kind="composition",
        )
        if result.ok
        else {"json_save_id": json_render_stem(payload.get("json_save_id")), "analysis_save_id": "", "artifacts": []}
    )
    status_code = 200 if result.ok else 502
    if result.upstream_status is None and result.upstream_debug.get("error_message") == "缺少环境变量: ALIYUN_API_KEY":
        status_code = 503
    body = result.as_dict()
    body["task_id"] = task_key
    body["json_save_id"] = completed_artifacts["json_save_id"]
    body["analysis_save_id"] = completed_artifacts["analysis_save_id"]
    body["completed_artifacts"] = [item["repo_path"] for item in completed_artifacts["artifacts"]]
    return JSONResponse(status_code=status_code, content=body)


@app.post("/aliyun-app-chat-test/analyze-ab-color")
async def aliyun_app_chat_test_analyze_ab_color(payload: dict[str, Any]):
    image_a_url = str(payload.get("image_a_url") or "").strip()
    image_b_url = str(payload.get("image_b_url") or "").strip()
    if not image_a_url or not image_b_url:
        return JSONResponse(status_code=400, content={"ok": False, "message": "请先分别保存色彩图 A 和色彩图 B"})
    if not is_allowed_ab_image_url(image_a_url) or not is_allowed_ab_image_url(image_b_url):
        return JSONResponse(status_code=400, content={"ok": False, "message": "A/B 图片 URL 必须来自当前页面保存的公网图片"})
    task_key = safe_task_id(payload.get("task_id"))
    result = await run_in_threadpool(get_aliyun_app_chat_test_service().analyze_color_ab, image_a_url, image_b_url)
    completed_artifacts = (
        write_completed_ab_analysis_artifacts(
            task_id=task_key,
            image_a_url=image_a_url,
            image_b_url=image_b_url,
            analysis_text=result.analysis if result.ok else result.message,
            json_save_id=payload.get("json_save_id"),
            analysis_save_id=payload.get("analysis_save_id"),
            kind="color",
        )
        if result.ok
        else {"json_save_id": json_render_stem(payload.get("json_save_id")), "analysis_save_id": "", "artifacts": []}
    )
    status_code = 200 if result.ok else 502
    if result.upstream_status is None and result.upstream_debug.get("error_message") == "缺少环境变量: ALIYUN_API_KEY":
        status_code = 503
    body = result.as_dict()
    body["task_id"] = task_key
    body["json_save_id"] = completed_artifacts["json_save_id"]
    body["analysis_save_id"] = completed_artifacts["analysis_save_id"]
    body["completed_artifacts"] = [item["repo_path"] for item in completed_artifacts["artifacts"]]
    return JSONResponse(status_code=status_code, content=body)



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
    public_image_url = aliyun_app_chat_test_public_workflow_url(save_name)
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
