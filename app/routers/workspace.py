"""Shared notes and immutable text versions, never original media blobs."""
import re
from urllib.parse import quote, urlencode

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response

from app.config import settings
from app.models.workspace import AskQuestion, GenerateVersion, Operation, PutNote, StrictPayload, now
from pydantic import Field
from app.routers.feishu import principal
from app.services.integration_proxy import proxy_integration
from app.services.workspace_generation import WorkspaceGeneration
from app.services.workspace_service import WorkspaceService

def no_cache(response: Response):
    response.headers["Cache-Control"] = "no-store"


router = APIRouter(prefix="/workspace", tags=["workspace-sync"], dependencies=[Depends(no_cache)])
service = WorkspaceService()
generation = WorkspaceGeneration()


def route(key):
    if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,160}", key):
        raise HTTPException(422, "内容标识无效")
    return "/api/workspace/notes/" + quote(key, safe="")


@router.get("/status")
def status(identity=Depends(principal)):
    remote, result = proxy_integration(identity, "GET", "/api/workspace/status")
    return {**result, "mode": "shared", "service_id": settings.workspace_service_url or settings.feishu_service_url} if remote else {
        "configured": True, "mode": "shared" if settings.workspace_cloud_runtime else "local", "owner": identity[0], "media_sync": False,
        "attachment_storage": "private-cloud" if settings.workspace_storage_key else "local",
        "capabilities": {"notes": True, "versions": True, "conflicts": True, "attachments": True,
                         "item_sync_policy": 1, "operation_receipts": 1,
                         "explicit_import": 1},
        "policy_scope": "device-local", "server_time": now().isoformat(),
    }


class SelectedImport(StrictPayload):
    keys: list[str] = Field(min_length=1, max_length=100)
    sync_authorized: bool


@router.post("/import-local")
def import_local(payload: SelectedImport, identity=Depends(principal)):
    if payload.sync_authorized is not True:
        raise HTTPException(409, "请先明确允许所选内容在此设备同步")
    for key in payload.keys:
        route(key)
    if settings.workspace_cloud_runtime:
        raise HTTPException(409, "请从保存历史内容的桌面设备发起")
    from app.services.workspace_migration_service import import_local_workspace
    return import_local_workspace(identity, payload.keys)


@router.get("/operations/{operation_id}")
def operation_receipt(operation_id: str, note_key: str = Query(min_length=1, max_length=160), identity=Depends(principal)):
    route(note_key)
    if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,160}", operation_id):
        raise HTTPException(422, "操作标识无效")
    path = "/api/workspace/operations/" + quote(operation_id, safe="") + "?" + urlencode({"note_key": note_key})
    remote, result = proxy_integration(identity, "GET", path)
    return result if remote else service.operation(identity[0], operation_id, note_key)


@router.get("/notes")
def notes(offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100),
          include_deleted: bool = False, identity=Depends(principal)):
    remote, result = proxy_integration(identity, "GET", "/api/workspace/notes?" + urlencode(
        {"offset": offset, "limit": limit, "include_deleted": str(include_deleted).lower()}))
    return result if remote else service.list(identity[0], offset, limit, include_deleted)


@router.get("/jobs")
def jobs(identity=Depends(principal)):
    remote, result = proxy_integration(identity, "GET", "/api/workspace/jobs")
    return result if remote else generation.jobs(identity[0])


@router.get("/notes/{key}")
def get_note(key: str, versions_offset: int = Query(0, ge=0), versions_limit: int = Query(50, ge=1, le=100), identity=Depends(principal)):
    path = route(key) + "?" + urlencode({"versions_offset": versions_offset, "versions_limit": versions_limit})
    remote, result = proxy_integration(identity, "GET", path)
    return result if remote else service.get(identity[0], key, versions_offset, versions_limit)


@router.put("/notes/{key}")
def put_note(key: str, payload: PutNote, identity=Depends(principal)):
    remote, result = proxy_integration(identity, "PUT", route(key), payload.model_dump(mode="json", exclude_unset=True))
    return result if remote else service.put(identity[0], key, payload)


@router.get("/notes/{key}/evidence/{revision}")
def evidence(key: str, revision: int, identity=Depends(principal)):
    if revision < 1:
        raise HTTPException(422, "证据修订无效")
    remote, result = proxy_integration(identity, "GET", route(key) + f"/evidence/{revision}")
    return result if remote else service.evidence(identity[0], key, revision)


@router.delete("/notes/{key}")
def delete_note(key: str, base_revision: int = Query(ge=0), operation_id: str = Query(min_length=1, max_length=160), identity=Depends(principal)):
    path = route(key) + "?" + urlencode({"base_revision": base_revision, "operation_id": operation_id})
    remote, result = proxy_integration(identity, "DELETE", path)
    return result if remote else service.set_deleted(identity[0], key, Operation(base_revision=base_revision, operation_id=operation_id), True)


@router.post("/notes/{key}/restore")
def restore(key: str, payload: Operation, identity=Depends(principal)):
    remote, result = proxy_integration(identity, "POST", route(key) + "/restore", payload.model_dump())
    return result if remote else service.set_deleted(identity[0], key, payload, False)


@router.post("/notes/{key}/generate")
def generate(key: str, payload: GenerateVersion, request: Request, identity=Depends(principal)):
    from app.services.tracing_service import DesktopTraceContext, desktop_trace, observation, update_current
    context = None
    if request.headers.get("X-VINote-Client", "").lower() == "desktop":
        context = DesktopTraceContext(
            workflow="meeting" if payload.template == "minutes" else "note_organization",
            source="saved_text", media_type="transcript", session_id=key,
            input={"note_key": key, "operation_id": payload.operation_id,
                   "template": payload.template, "instructions": payload.instructions,
                   "base_revision": payload.base_revision},
        )
    with desktop_trace(context), observation(
        context.trace_name if context else "文本版本生成",
        root={"task_id": payload.operation_id, "user_id": identity[0]},
        input=context.input if context else {},
    ):
        remote, result = proxy_integration(identity, "POST", route(key) + "/generate", payload.model_dump())
        bearer = request.headers.get("authorization", "").removeprefix("Bearer ") if identity[1] is None else None
        result = result if remote else generation.generate(identity, key, payload, bearer)
        update_current(output={"status": "completed", "revision": result["revision"], "final_note": result["content"]})
        return result


@router.post("/notes/{key}/ask")
def ask(key: str, payload: AskQuestion, request: Request, identity=Depends(principal)):
    remote, result = proxy_integration(identity, "POST", route(key) + "/ask", payload.model_dump())
    bearer = request.headers.get("authorization", "").removeprefix("Bearer ") if identity[1] is None else None
    try:
        return result if remote else generation.ask(identity, key, payload, bearer)
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(502, "回答未完成，请保留问题后重试") from None
