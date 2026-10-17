"""Installed text plugins and explicit preview/save operations."""
from fastapi import APIRouter, Depends, Request, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from typing import Literal
from app.routers.feishu import principal
from app.routers.workspace import no_cache
from app.services.integration_proxy import proxy_integration
from app.services.content_plugin_service import ContentPluginService

router = APIRouter(prefix="/plugins", tags=["content-plugins"], dependencies=[Depends(no_cache)])
service = ContentPluginService()


class Setting(BaseModel):
    model_config = ConfigDict(extra="forbid")
    installed: bool
    enabled: bool = True


class Preview(BaseModel):
    model_config = ConfigDict(extra="forbid")
    plugin_id: Literal["translation", "actions", "glossary", "diagram"]
    note_key: str = Field(min_length=1, max_length=160, pattern=r"^[A-Za-z0-9_.:-]+$")
    version_id: str = Field(min_length=1, max_length=160)
    base_revision: int = Field(ge=1)
    operation_id: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_-]+$")
    language: str = Field(default="en", max_length=10)
    glossary: str = Field(default="", max_length=4000)


def bearer(request):
    value = request.headers.get("Authorization", "")
    return value[7:] if value.startswith("Bearer ") else None


@router.get("")
def catalog(identity=Depends(principal)):
    remote, result = proxy_integration(identity, "GET", "/api/plugins")
    return [item for item in (result if remote else service.catalog(identity[0])) if item["id"] != "diagram"]


@router.put("/{plugin_id}")
def setting(plugin_id: str, payload: Setting, identity=Depends(principal)):
    if plugin_id == "diagram" and payload.installed and payload.enabled:
        raise HTTPException(409, "可视化生成已停用；历史结果保留")
    remote, result = proxy_integration(identity, "PUT", "/api/plugins/" + plugin_id, payload.model_dump())
    return result if remote else service.setting(identity[0], plugin_id, payload.installed, payload.enabled)


@router.get("/runs")
def runs(identity=Depends(principal)):
    remote, result = proxy_integration(identity, "GET", "/api/plugins/runs")
    return result if remote else service.runs(identity[0])


@router.get("/runs/{run_id}")
def get(run_id: str, identity=Depends(principal)):
    remote, result = proxy_integration(identity, "GET", "/api/plugins/runs/" + run_id)
    return result if remote else service.get(identity[0], run_id)


@router.post("/runs")
def start(payload: Preview, request: Request, identity=Depends(principal)):
    if payload.plugin_id == "diagram":
        raise HTTPException(409, "可视化生成已停用；历史结果保留")
    remote, result = proxy_integration(identity, "POST", "/api/plugins/runs", payload.model_dump())
    return result if remote else service.start(identity, payload, bearer(request))


@router.post("/runs/{run_id}/retry")
def retry(run_id: str, request: Request, identity=Depends(principal)):
    remote_read, previous = proxy_integration(identity, "GET", "/api/plugins/runs/" + run_id)
    if remote_read and previous.get("plugin_id") == "diagram":
        raise HTTPException(409, "可视化生成已停用；历史结果保留")
    remote, result = proxy_integration(identity, "POST", "/api/plugins/runs/" + run_id + "/retry")
    return result if remote else service.retry(identity, run_id, bearer(request))


@router.post("/runs/{run_id}/save")
def save(run_id: str, identity=Depends(principal)):
    remote, result = proxy_integration(identity, "POST", "/api/plugins/runs/" + run_id + "/save")
    return result if remote else service.save(identity[0], run_id)
