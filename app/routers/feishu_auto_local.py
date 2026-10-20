"""Device receipt reads only; never dispatches a new publication on recovery."""
from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field

from app.models.auth import AuthenticatedUser
from app.services.auth_service import get_current_user
from app.services import feishu_auto_runtime as runtime

router = APIRouter(prefix="/feishu/automatic-deliveries/local", tags=["feishu"])
device_router = APIRouter(prefix="/feishu/automatic-deliveries", tags=["feishu"])


class DisableDevice(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_user_id: str = Field(min_length=1, max_length=128)


@device_router.post("/device-disable")
def disable_device(payload: DisableDevice, response: Response,
                   user: AuthenticatedUser = Depends(get_current_user)):
    if payload.expected_user_id != user.user_id:
        raise HTTPException(409, "账号已变化，请返回当前账号的插件设置")
    response.headers["Cache-Control"] = "no-store"
    runtime.bind_device_policy(user.user_id, None)
    return {"device_auto_enabled": False}


@router.get("/{note_id}")
def status(note_id: str, response: Response, user: AuthenticatedUser = Depends(get_current_user)):
    response.headers["Cache-Control"] = "no-store"
    return runtime.local_status(user.user_id, note_id)


@router.post("/{note_id}/check")
def check(note_id: str, response: Response, user: AuthenticatedUser = Depends(get_current_user)):
    response.headers["Cache-Control"] = "no-store"
    return runtime.check_local(user.user_id, note_id)
