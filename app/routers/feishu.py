"""Feishu OAuth and deliveries, with optional shared-service proxy."""
import hashlib
import logging
from typing import Literal
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, Response
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.config import settings
from app.db import session_scope
from app.db_models import CloudAccountDB
from app.services.auth_service import get_current_user
from app.services.cloud_account_service import CloudAccountService, _request
from app.services.feishu_service import FeishuService
from app.services.feishu_application_service import application_status, save_application, clear_application

router = APIRouter(prefix="/feishu", tags=["feishu"])
service = FeishuService()


class OAuthAccessLogFilter(logging.Filter):
    def filter(self, record):
        if isinstance(record.args, tuple) and len(record.args) >= 3 and isinstance(record.args[2], str) and record.args[2].split("?", 1)[0] == "/api/feishu/callback":
            values = list(record.args)
            values[2] = "/api/feishu/callback"
            record.args = tuple(values)
        return True


logging.getLogger("uvicorn.access").addFilter(OAuthAccessLogFilter())


def cloud_owner(subject):
    return hashlib.sha256((settings.cloud_auth_url + ":" + subject).encode()).hexdigest()


def principal(request: Request):
    authorization = request.headers.get("authorization", "")
    if authorization.startswith("Bearer "):
        # This route alone accepts a verified Supabase bearer. No unsigned JWT claims.
        identity = _request("user", token=authorization[7:])
        if not identity.get("id") or not identity.get("email_confirmed_at") or identity.get("is_anonymous"):
            raise HTTPException(401, "请验证 VINote 账号后重试")
        return cloud_owner(identity["id"]), None
    if settings.workspace_cloud_runtime:
        raise HTTPException(401, "请使用已验证的 VINote 云端账号访问共享服务")
    user = get_current_user(request, None)
    with session_scope() as db:
        account = db.get(CloudAccountDB, user.user_id)
        owner = cloud_owner(account.subject) if account and account.issuer == settings.cloud_auth_url else user.user_id
    return owner, user.user_id


def proxy(identity, method, path, body=None):
    if not settings.feishu_service_url or identity[1] is None:
        return False, None
    token = CloudAccountService().access_token(identity[1])
    try:
        response = httpx.request(method, settings.feishu_service_url + "/api/feishu" + path,
                                 headers={"Authorization": "Bearer " + token}, json=body,
                                 timeout=45, follow_redirects=False)
        payload = response.json()
    except (httpx.RequestError, ValueError):
        raise HTTPException(502, "无法连接飞书集成服务，请重试") from None
    if not response.is_success:
        raise HTTPException(response.status_code, payload.get("detail", "飞书集成请求未完成"))
    return True, payload


class Destination(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["personal", "folder", "wiki"] = "personal"
    folder_token: str = Field(default="", max_length=200, pattern=r"^[a-zA-Z0-9_-]*$")
    space_id: str = Field(default="", max_length=100, pattern=r"^[a-zA-Z0-9_-]*$")
    node_token: str = Field(default="", max_length=200, pattern=r"^[a-zA-Z0-9_-]*$")

    @model_validator(mode="after")
    def validate_target(self):
        # The service repeats validation for non-HTTP callers.
        service.normalize_destination(self.model_dump())
        return self


class Preferences(BaseModel):
    notify_self: bool = True
    groups: list[str] = Field(default_factory=list, max_length=20)
    auto_publish: bool = False
    destination_config: Destination | None = None
    permission_policy: Literal["private", "inherit"] | None = None


class ContactSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    open_id: str = Field(pattern=r"^ou_[A-Za-z0-9_-]{1,196}$")
    selection_token: str = Field(min_length=1, max_length=4096)


class Publish(BaseModel):
    operation_id: str | None = Field(default=None, min_length=1, max_length=160)
    note_key: str = Field(min_length=1, max_length=160)
    title: str | None = Field(default=None, min_length=1, max_length=500)
    content: str | None = Field(default=None, min_length=1, max_length=300000)
    automatic: bool = False
    destination_config: Destination | None = None
    permission_policy: Literal["private", "inherit"] | None = None
    notify_self: bool | None = None
    groups: list[str] | None = Field(default=None, max_length=20)
    version_id: str | None = Field(default=None, min_length=1, max_length=160)
    revision_id: str | None = Field(default=None, min_length=1, max_length=160)
    source_mode: Literal["local_snapshot"] | None = None
    contacts: list[ContactSelection] | None = Field(default=None, max_length=20)
    recipient_access_policy: Literal["grant_view_and_notify"] | None = None


class RetryRecipients(BaseModel):
    recipients: list[str] | None = Field(default=None, min_length=1, max_length=41)


class ResumePending(BaseModel):
    limit: int = Field(default=3, ge=1, le=5)


class DocumentRecovery(BaseModel):
    url: str = Field(min_length=1, max_length=2000)


@router.get("/status")
def status(identity=Depends(principal), response: Response = None):
    if response is not None:
        response.headers["Cache-Control"] = "no-store"
    remote, result = proxy(identity, "GET", "/status")
    return result if remote else service.for_owner(identity[0]).status(identity[0])


@router.post("/authorize")
def authorize(identity=Depends(principal)):
    remote, result = proxy(identity, "POST", "/authorize")
    return result if remote else service.for_owner(identity[0]).authorize(identity[0])


@router.get("/callback", response_class=HTMLResponse)
def callback(state: str, code: str = "", error: str = ""):
    if error or not code:
        service.consume_state(state)
        return HTMLResponse('<meta charset="utf-8"><h1>授权未完成</h1><p>请回到 VINote 设置重新连接。</p>', status_code=400,
                            headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"})
    service.callback(state, code)
    return HTMLResponse('<meta charset="utf-8"><h1>飞书连接成功</h1><p>请回到 VINote，点击“我已完成授权”核验连接。</p>',
                        headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"})


@router.delete("/connection")
def disconnect(identity=Depends(principal)):
    remote, result = proxy(identity, "DELETE", "/connection")
    return result if remote else service.for_owner(identity[0]).disconnect(identity[0])


@router.get("/groups")
def groups(identity=Depends(principal)):
    remote, result = proxy(identity, "GET", "/groups")
    return result if remote else service.for_owner(identity[0]).groups(identity[0])


@router.get("/contacts")
def contacts(response: Response, query: str = Query(min_length=1, max_length=50, pattern=r"\S"),
             page_size: int = Query(default=20, ge=1, le=50),
             page_token: str = Query(default="", max_length=2000), identity=Depends(principal)):
    """One search page; items carry open_id/name/selection_token (900s).

    Requires the existing owner's contact:user:search grant. Selection is
    per-publication, not a saved notification default. Reading permission and
    bot availability remain not_checked; no document/message write occurs.
    """
    response.headers["Cache-Control"] = "no-store"
    params = dict(query=query, page_size=page_size, page_token=page_token)
    remote, result = proxy(identity, "GET", "/contacts?" + urlencode(params))
    return result if remote else service.for_owner(identity[0]).contacts(identity[0], **params)


@router.put("/preferences")
def preferences(payload: Preferences, identity=Depends(principal)):
    body = payload.model_dump(exclude_none=True)
    remote, result = proxy(identity, "PUT", "/preferences", body)
    return result if remote else service.for_owner(identity[0]).save_preferences(identity[0], body)


@router.get("/destinations")
def destinations(kind: Literal["folder", "wiki"] = "folder",
                 folder_token: str = Query(default="", max_length=200, pattern=r"^[a-zA-Z0-9_-]*$"),
                 space_id: str = Query(default="", max_length=100, pattern=r"^[a-zA-Z0-9_-]*$"),
                 parent_node_token: str = Query(default="", max_length=200, pattern=r"^[a-zA-Z0-9_-]*$"),
                 page_token: str = Query(default="", max_length=2000), identity=Depends(principal)):
    params = dict(kind=kind, folder_token=folder_token, space_id=space_id,
                  parent_node_token=parent_node_token, page_token=page_token)
    remote, result = proxy(identity, "GET", "/destinations?" + urlencode(params))
    return result if remote else service.for_owner(identity[0]).destinations(identity[0], **params)


@router.post("/destinations/check")
def check_destination(payload: Destination, identity=Depends(principal)):
    body = payload.model_dump()
    remote, result = proxy(identity, "POST", "/destinations/check", body)
    return result if remote else service.for_owner(identity[0]).check_destination(identity[0], body)


@router.get("/deliveries/by-id/{job_id}")
def delivery_by_id(job_id: str, response: Response, identity=Depends(principal)):
    from urllib.parse import quote
    response.headers["Cache-Control"] = "no-store"
    remote, result = proxy(identity, "GET", "/deliveries/by-id/" + quote(job_id, safe=""))
    return result if remote else service.for_owner(identity[0]).delivery_by_id(identity[0], job_id)


@router.get("/deliveries/by-operation/{operation_id}")
def delivery_by_operation(operation_id: str, response: Response, identity=Depends(principal)):
    from urllib.parse import quote
    response.headers["Cache-Control"] = "no-store"
    remote, result = proxy(identity, "GET", "/deliveries/by-operation/" + quote(operation_id, safe=""))
    return result if remote else service.for_owner(identity[0]).delivery_by_operation(identity[0], operation_id)


@router.get("/deliveries/{note_key}")
def delivery(note_key: str, identity=Depends(principal)):
    from urllib.parse import quote
    remote, result = proxy(identity, "GET", "/deliveries/" + quote(note_key, safe=""))
    return result if remote else service.for_owner(identity[0]).delivery(identity[0], note_key)


@router.post("/deliveries")
def publish(payload: Publish, background: BackgroundTasks, identity=Depends(principal)):
    body = payload.model_dump(exclude_none=True)
    if payload.recipient_access_policy:
        if payload.automatic or not payload.operation_id:
            raise HTTPException(422, "阅读授权与通知需要明确的新发布操作")
        remote, capability = proxy(identity, "GET", "/status")
        if remote and capability.get("recipient_access_protocol") != 1:
            raise HTTPException(409, {"code": "RECIPIENT_ACCESS_PROTOCOL_UNAVAILABLE",
                                      "message": "远端服务尚未支持阅读授权与通知，尚未提交"})
    if payload.contacts:
        if payload.automatic or not payload.operation_id:
            raise HTTPException(422, "联系人通知需要手动确认及 operation_id")
        # Old proxies may silently discard unknown request fields. Fail before POST.
        remote, capability = proxy(identity, "GET", "/status")
        if remote and capability.get("contact_selection_protocol") != 1:
            raise HTTPException(409, {"code": "CONTACT_PROTOCOL_UNAVAILABLE",
                                      "message": "远端飞书服务尚未支持联系人发布，请升级服务后重试"})
    remote, result = proxy(identity, "POST", "/deliveries", body)
    if remote:
        return result
    result = service.for_owner(identity[0]).enqueue(identity[0], **body)
    dispatch = result.pop("_dispatch_required", True) if result else False
    if result and dispatch:
        background.add_task(service.for_owner(identity[0]).process, identity[0], result["id"])
    return result


@router.post("/deliveries/{job_id}/retry")
def retry(job_id: str, background: BackgroundTasks, payload: RetryRecipients | None = None,
          identity=Depends(principal)):
    selected = payload.recipients if payload else None
    remote, result = proxy(identity, "POST", f"/deliveries/{job_id}/retry",
                           payload.model_dump() if payload else None)
    if remote:
        return result
    # Verify ownership before scheduling (not only inside the worker).
    from app.db_models import FeishuDeliveryDB
    with session_scope() as db:
        job = db.get(FeishuDeliveryDB, job_id)
        if not job or job.owner != identity[0]:
            raise HTTPException(404, "交付记录不存在")
        if selected is not None:
            service.validate_retry_recipients(job, selected)
        result = service.serialize(job, db=db)
        if result["phase"] in ("unknown", "permission_unknown"):
            raise HTTPException(409, "原交付结果尚未核验，不能重放未知步骤；请查询原回执")
    background.add_task(service.for_owner(identity[0]).process, identity[0], job_id, selected)
    return result


@router.post("/deliveries/{job_id}/verify-permissions")
def verify_permissions(job_id: str, response: Response, identity=Depends(principal)):
    """Read provider ACLs and checkpoint evidence; never schedule delivery."""
    from urllib.parse import quote
    response.headers["Cache-Control"] = "no-store"
    remote, result = proxy(identity, "POST", "/deliveries/" + quote(job_id, safe="") + "/verify-permissions", {})
    return result if remote else service.for_owner(identity[0]).verify_delivery_permissions(identity[0], job_id)


@router.post("/deliveries/resume")
def resume_pending(background: BackgroundTasks, payload: ResumePending | None = None,
                   identity=Depends(principal)):
    body = payload.model_dump() if payload else {"limit": 3}
    remote, result = proxy(identity, "POST", "/deliveries/resume", body)
    if remote:
        return result
    result = service.for_owner(identity[0]).pending_recovery(identity[0], body["limit"])
    # Starlette executes these sequentially; each worker still claims its DB lease.
    for job_id in result["scheduled"]:
        background.add_task(service.for_owner(identity[0]).process, identity[0], job_id)
    return result


@router.post("/deliveries/{job_id}/document")
def recover_document(job_id: str, payload: DocumentRecovery, identity=Depends(principal)):
    remote, result = proxy(identity, "POST", f"/deliveries/{job_id}/document", payload.model_dump())
    return result if remote else service.for_owner(identity[0]).recover_document(identity[0], job_id, payload.url)


class EnterpriseApplication(BaseModel):
    model_config = ConfigDict(extra="forbid")
    app_id: str = Field(min_length=8, max_length=120)
    app_secret: str = Field(min_length=8, max_length=300)
    tenant_key: str = Field(min_length=1, max_length=120, pattern=r"^[A-Za-z0-9_-]+$")
    document_domain: str = Field(min_length=10, max_length=300)


@router.get("/application")
def get_application(identity=Depends(principal)):
    remote, result = proxy(identity, "GET", "/application")
    return result if remote else application_status(identity[0])


@router.put("/application")
def put_application(payload: EnterpriseApplication, identity=Depends(principal)):
    remote, result = proxy(identity, "PUT", "/application", payload.model_dump())
    if remote:
        return result
    try:
        return save_application(identity[0], payload.model_dump())
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from None


@router.delete("/application")
def delete_application(identity=Depends(principal)):
    remote, result = proxy(identity, "DELETE", "/application")
    return result if remote else clear_application(identity[0])
