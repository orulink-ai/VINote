from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from app.services.cloud_account_service import CloudAccountService
from app.services.auth_service import get_current_user
from app.services.vilab_cloud_service import VILabCloudService
from app.services.vilab_connection_service import VILabConnectionService

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
    connection_id: str | None = Field(default=None, max_length=100)
    connection_revision: str | None = Field(default=None, max_length=100)


class ModeSelection(BaseModel):
    mode: Literal["cloud", "local"]


class ConnectionCheck(BaseModel):
    model_config = ConfigDict(extra="forbid")
    server_url: str | None = Field(default=None, max_length=2048)
    api_key: str | None = Field(default=None, max_length=4096)
    connection_id: str | None = Field(default=None, max_length=100)
    auth_mode: Literal["account", "api_key"] | None = None
    account_consent: bool = False
    authorized_origin: str | None = Field(default=None, max_length=2048)


class ConnectionSave(BaseModel):
    model_config = ConfigDict(extra="forbid")
    check_id: str = Field(min_length=1, max_length=100)
    asr_model: str = Field(default="", max_length=200)
    llm_model: str = Field(default="", max_length=200)


@router.get("/connections")
def connections(user=Depends(get_current_user)):
    return VILabConnectionService().list(user.user_id)


@router.post("/connections/check")
def check_connection(payload: ConnectionCheck, user=Depends(get_current_user)):
    return VILabConnectionService().check(user.user_id, **payload.model_dump())


@router.put("/connection")
def save_connection(payload: ConnectionSave, user=Depends(get_current_user)):
    return VILabConnectionService().save(user.user_id, payload.check_id, payload.asr_model, payload.llm_model)


@router.get("/config")
def config(user=Depends(get_current_user)):
    return service.status(user.user_id)


@router.get("/models")
def models(user=Depends(get_current_user)):
    return service.models(user.user_id)


@router.put("/config")
def select_models(payload: Selection, user=Depends(get_current_user)):
    return service.select(user.user_id, payload.mode, payload.asr_model, payload.llm_model,
                          connection_id=payload.connection_id, connection_revision=payload.connection_revision)


@router.put("/mode")
def set_mode(payload: ModeSelection, user=Depends(get_current_user)):
    return service.set_mode(user.user_id, payload.mode)
