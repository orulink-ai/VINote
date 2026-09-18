from typing import Literal
from urllib.parse import urlencode, urlsplit, urlunsplit

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from app.services.cloud_account_service import CloudAccountService
from app.services.auth_service import get_current_user
from app.services.vilab_cloud_service import VILabCloudService
from app.config import settings

router = APIRouter(prefix="/vilab", tags=["vilab"])
service = VILabCloudService()
accounts = CloudAccountService()


class CloudEmail(BaseModel):
    email: str = Field(min_length=3, max_length=254, pattern=r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


class CloudVerify(CloudEmail):
    code: str = Field(min_length=6, max_length=10, pattern=r"^\d+$")


@router.get("/account")
def account(user=Depends(get_current_user)):
    return accounts.status(user.user_id)


@router.post("/account/code")
def account_code(payload: CloudEmail, user=Depends(get_current_user)):
    return accounts.send_code(user.user_id, str(payload.email))


@router.post("/account/verify")
def account_verify(payload: CloudVerify, user=Depends(get_current_user)):
    return accounts.verify_code(user.user_id, str(payload.email), payload.code)


@router.delete("/account")
def account_disconnect(user=Depends(get_current_user)):
    return accounts.disconnect(user.user_id)


class Selection(BaseModel):
    mode: Literal["cloud", "local"]
    asr_model: str = Field(default="", max_length=200)
    llm_model: str = Field(default="", max_length=200)


class ModeSelection(BaseModel):
    mode: Literal["cloud", "local"]


@router.get("/config")
def config(user=Depends(get_current_user)):
    return service.status(user.user_id)


@router.get("/models")
def models(user=Depends(get_current_user)):
    return service.models(user.user_id)


@router.put("/config")
def select_models(payload: Selection, user=Depends(get_current_user)):
    return service.select(user.user_id, payload.mode, payload.asr_model, payload.llm_model)


@router.put("/mode")
def set_mode(payload: ModeSelection, user=Depends(get_current_user)):
    return service.set_mode(user.user_id, payload.mode)


@router.get("/realtime-connection")
def realtime_connection(response: Response, user=Depends(get_current_user)):
    """Return a short-lived, user-scoped realtime ASR connection.

    The deployment API key must never be exposed to the renderer. Realtime
    capture therefore requires the signed-in VINote user to have linked their
    personal cloud account.
    """
    origin = settings.vilab_server_url.strip().rstrip("/")
    if not origin:
        raise HTTPException(503, "云端实时转写服务尚未配置")
    parsed = urlsplit(origin)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise HTTPException(503, "云端实时转写服务地址无效")

    model = service.defaults(user.user_id).get("asr_model")
    if not model:
        raise HTTPException(400, "请选择可用的云端语音转写模型")
    service._validate_selection(service.models(user.user_id), model, "asr")
    token = accounts.access_token(user.user_id)
    websocket_scheme = "wss" if parsed.scheme == "https" else "ws"
    base_path = parsed.path.rstrip("/")
    path = f"{base_path}/v1/asr/transcriptions"
    url = urlunsplit((websocket_scheme, parsed.netloc, path, urlencode({"token": token}), ""))
    response.headers["Cache-Control"] = "no-store"
    return {"url": url, "language": "zh-CN", "model": model}
