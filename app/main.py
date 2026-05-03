from pathlib import Path
from uuid import uuid4

import json
import logging
import os

import httpx
from fastapi import FastAPI, File, UploadFile
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from app.schemas.request_models import AnalyzeRequest, HiAgentFeedbackRequest, RecolorRequest, SegmentRequest
from app.schemas.response_models import AnalyzeResponse, HealthResponse, RecolorResponse, SegmentResponse
from app.services.analyze_service import AnalyzeService
from app.services.recolor_service import RecolorService
from app.services.segment_service import SegmentService

app = FastAPI(title="Color Agent Plugins API", version="0.1.0")

ALLOWED_UPLOAD_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}
UPLOAD_DIR = Path("static/uploads")
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

logger = logging.getLogger(__name__)


@app.get("/health", response_model=HealthResponse)
def health() -> dict:
    return {"status": "ok", "message": "service is running"}


@app.post("/segment", response_model=SegmentResponse)
def segment(payload: SegmentRequest) -> dict:
    return SegmentService.segment_colors(payload)


@app.post("/recolor", response_model=RecolorResponse)
def recolor(payload: RecolorRequest) -> dict:
    return RecolorService.recolor(payload)


@app.post("/analyze", response_model=AnalyzeResponse)
def analyze(payload: AnalyzeRequest) -> dict:
    return AnalyzeService.analyze(payload)




def _is_absolute_url(url: str) -> bool:
    return url.startswith("http://") or url.startswith("https://")




def _extract_hiagent_error_text(resp: httpx.Response | None = None, exc: Exception | None = None) -> str:
    parts = []
    if resp is not None:
        parts.append(resp.text or "")
        try:
            parts.append(json.dumps(resp.json(), ensure_ascii=False))
        except Exception:
            pass
    if exc is not None:
        parts.append(str(exc))
    return " ".join(p for p in parts if p)


def _hiagent_error_message(resp: httpx.Response | None = None, exc: Exception | None = None, timeout: bool = False) -> str:
    if timeout:
        return "HiAgent 请求超时，可能是网络访问限制或接口响应过慢。"

    if resp is not None and resp.status_code in (401, 403):
        return "HiAgent 鉴权失败，请检查 HIAGENT_API_KEY 和 HIAGENT_APP_ID。"

    error_text = _extract_hiagent_error_text(resp=resp, exc=exc)
    if "AppID is empty" in error_text:
        return "HiAgent 请求缺少 APPID，请检查 Render 环境变量 HIAGENT_APP_ID 是否已设置。"

    return "HiAgent 请求失败，请稍后重试。"
@app.get("/hiagent-health-test")
def hiagent_health_test() -> dict:
    logger.info("hiagent health test start")

    api_base = os.getenv("HIAGENT_API_BASE", "").rstrip("/")
    api_key = os.getenv("HIAGENT_API_KEY", "")
    user_id = os.getenv("HIAGENT_USER_ID", "coloragent")
    app_id = os.getenv("HIAGENT_APP_ID", "")

    if not api_base or not api_key:
        return {"status": "failed", "stage": "config", "message": "HiAgent 尚未配置"}
    if not app_id:
        return {"status": "failed", "stage": "config", "message": "HiAgent 尚未配置 APPID，请先在 Render 环境变量中设置 HIAGENT_APP_ID。"}

    logger.info("hiagent api base: %s", api_base)

    try:
        with httpx.Client(timeout=30) as client:
            resp = client.post(
                f"{api_base}/create_conversation",
                headers={"Apikey": api_key, "AppID": app_id, "Content-Type": "application/json"},
                json={"UserID": user_id, "AppID": app_id},
            )
    except httpx.TimeoutException:
        logger.warning("hiagent create_conversation timeout")
        return {"status": "failed", "stage": "create_conversation", "message": _hiagent_error_message(timeout=True)}
    except Exception as exc:
        logger.exception("hiagent create_conversation error")
        return {"status": "failed", "stage": "create_conversation", "message": _hiagent_error_message(exc=exc)}

    body_text = resp.text or ""
    preview = body_text[:300]

    if not (200 <= resp.status_code < 300):
        logger.warning("hiagent create_conversation http error")
        return {
            "status": "failed",
            "stage": "create_conversation",
            "message": _hiagent_error_message(resp=resp),
            "status_code": resp.status_code,
            "response_preview": preview,
        }

    try:
        parsed = resp.json()
    except json.JSONDecodeError:
        logger.warning("hiagent create_conversation http error")
        return {
            "status": "failed",
            "stage": "create_conversation",
            "message": "HiAgent 返回不是有效 JSON",
            "response_preview": preview,
        }

    app_conversation_id = parsed.get("Conversation", {}).get("AppConversationID")
    if app_conversation_id:
        logger.info("hiagent create_conversation success")
        return {
            "status": "ok",
            "stage": "create_conversation",
            "message": "HiAgent create_conversation success",
            "conversation_id_exists": True,
            "app_id_configured": True,
        }

    logger.warning("hiagent create_conversation http error")
    return {
        "status": "failed",
        "stage": "create_conversation",
        "message": _hiagent_error_message(resp=resp),
        "status_code": resp.status_code,
        "response_preview": preview,
    }


@app.post("/hiagent-feedback")
def hiagent_feedback(payload: HiAgentFeedbackRequest) -> dict:
    if not isinstance(payload.color_regions, list) or not isinstance(payload.adjustment_history, list):
        return {"status": "failed", "message": "请求参数格式错误：color_regions 和 adjustment_history 必须是数组。"}

    if not payload.adjustment_history:
        return {"status": "failed", "message": "请先保存至少一次色块调整，再生成实验反馈。"}

    original_image_url = str(payload.original_image_url)
    adjusted_image_url = str(payload.adjusted_image_url)

    if not _is_absolute_url(original_image_url) or not _is_absolute_url(adjusted_image_url):
        return {"status": "failed", "message": "original_image_url 和 adjusted_image_url 必须是完整 URL。"}

    api_base = os.getenv("HIAGENT_API_BASE", "").rstrip("/")
    api_key = os.getenv("HIAGENT_API_KEY", "")
    user_id = os.getenv("HIAGENT_USER_ID", "color-agent-user")
    app_id = os.getenv("HIAGENT_APP_ID", "")

    if not api_base or not api_key:
        return {"status": "failed", "message": "HiAgent 尚未配置，请先在 Render 环境变量中设置 HIAGENT_API_BASE 和 HIAGENT_API_KEY。"}
    if not app_id:
        return {"status": "failed", "stage": "config", "message": "HiAgent 尚未配置 APPID，请先在 Render 环境变量中设置 HIAGENT_APP_ID。"}

    query = f"""你是色彩构成实验导师。以下是学生完成的一次色彩构成实验资料。

【原始图片链接】
{original_image_url}

【调色后图片链接】
{adjusted_image_url}

【主色区域信息】
{payload.color_regions}

【学生调色记录】
{payload.adjustment_history}

请根据原图、调色后图片和学生的 H/S/L 调整记录，完成色彩构成分析。

请严格按以下结构输出：

一、色彩关系
二、视觉感受
三、适用场景
四、画面变化解释
五、色彩构成知识
六、下一轮实验建议
七、反思问题

要求：
- 不要替学生自动调色；
- 不要只说好看或不好看；
- 必须结合 H/S/L 调整记录解释；
- 如果无法直接读取图片，请基于图片链接、主色区域和调色记录进行分析，并说明分析依据。
"""

    try:
        with httpx.Client(timeout=30) as client:
            conv_resp = client.post(
                f"{api_base}/create_conversation",
                headers={"Apikey": api_key, "AppID": app_id, "Content-Type": "application/json"},
                json={"UserID": user_id, "AppID": app_id},
            )
            conv_resp.raise_for_status()
            conv_body = conv_resp.json()
            if "AppID is empty" in _extract_hiagent_error_text(resp=conv_resp):
                return {"status": "failed", "message": _hiagent_error_message(resp=conv_resp)}
            app_conversation_id = conv_body.get("Conversation", {}).get("AppConversationID")
            if not app_conversation_id:
                return {"status": "failed", "message": "HiAgent 创建会话失败：未返回 AppConversationID。"}
    except httpx.TimeoutException:
        return {"status": "failed", "message": _hiagent_error_message(timeout=True)}
    except Exception as exc:
        return {"status": "failed", "message": _hiagent_error_message(exc=exc)}

    try:
        with httpx.Client(timeout=60) as client:
            chat_resp = client.post(
                f"{api_base}/chat_query_v2",
                headers={"Apikey": api_key, "AppID": app_id, "Content-Type": "application/json"},
                json={
                    "UserID": user_id,
                    "AppConversationID": app_conversation_id,
                    "Query": query,
                    "ResponseMode": "blocking",
                    "AppID": app_id,
                },
            )
            chat_resp.raise_for_status()
            chat_body = chat_resp.json()
            if "AppID is empty" in _extract_hiagent_error_text(resp=chat_resp):
                return {"status": "failed", "message": _hiagent_error_message(resp=chat_resp)}
    except httpx.TimeoutException:
        return {"status": "failed", "message": _hiagent_error_message(timeout=True)}
    except Exception as exc:
        return {"status": "failed", "message": _hiagent_error_message(exc=exc)}

    answer = chat_body.get("answer")
    if not answer:
        return {"status": "failed", "message": "HiAgent 返回格式异常：未找到 answer 字段。"}

    return {"status": "success", "answer": answer}


@app.get("/experiment", response_class=HTMLResponse)
def experiment() -> HTMLResponse:
    html = Path("app/templates/experiment.html").read_text(encoding="utf-8")
    return HTMLResponse(content=html)


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
        "image_url": str(save_path),
        "display_url": display_url,
    }


app.mount("/static", StaticFiles(directory="static"), name="static")
