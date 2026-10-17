"""Verified content identities and revocable, memory-only request credentials."""
import threading
import uuid
from contextvars import ContextVar
from dataclasses import dataclass, field

import anyio
from fastapi import HTTPException, Request
from sqlalchemy import String, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Mapped, mapped_column
from starlette.responses import JSONResponse

from app.config import settings
from app.db import Base, session_scope
from app.db_models import CloudAccountDB
from app.models.auth import AuthenticatedUser
from app.services.cloud_account_service import _request


class ContentIdentityDB(Base):
    __tablename__ = "content_cloud_identities"
    issuer: Mapped[str] = mapped_column(String(500), primary_key=True)
    subject: Mapped[str] = mapped_column(String(100), primary_key=True)
    owner: Mapped[str] = mapped_column(String(36), unique=True)


@dataclass(repr=False)
class CredentialLease:
    owner: str
    bearer: str = field(repr=False)
    active: bool = True


_credential: ContextVar[CredentialLease | None] = ContextVar("content_credential", default=None)
_submission_slot = threading.BoundedSemaphore(1)


def content_bearer(owner: str) -> str:
    lease = _credential.get()
    if not lease or not lease.active or lease.owner != owner:
        raise HTTPException(401, "当前处理凭证已失效，请保留原任务并重新核验")
    return lease.bearer


def verified_user(token: str, *, provision=True) -> AuthenticatedUser:
    identity = _request("user", token=token)
    subject = identity.get("id")
    if (not isinstance(subject, str) or not 1 <= len(subject) <= 100
            or not identity.get("email_confirmed_at") or identity.get("is_anonymous")):
        raise HTTPException(401, "请使用已验证的 VINote 云端账号")
    issuer = settings.cloud_auth_url
    if not issuer:
        raise HTTPException(503, "内容服务账号验证尚未配置")
    if not provision:
        # Capabilities proves the bearer, but is read-only: no identity/table,
        # model catalog, queue or task is created by this preflight GET.
        return AuthenticatedUser(user_id=subject)
    key = (issuer, subject)
    try:
        with session_scope() as db:
            row = db.get(ContentIdentityDB, key)
            if not row:
                linked = db.scalar(select(CloudAccountDB).where(
                    CloudAccountDB.issuer == issuer, CloudAccountDB.subject == subject))
                # Never search for or create a binding by email. Freeze a prior
                # verified binding, otherwise allocate a separate UUID namespace.
                row = ContentIdentityDB(issuer=issuer, subject=subject,
                                        owner=linked.user_id if linked else str(uuid.uuid4()))
                db.add(row)
                db.flush()
            owner = row.owner
    except IntegrityError:
        with session_scope() as db:
            row = db.get(ContentIdentityDB, key)
            if row is None:
                raise
            owner = row.owner
    return AuthenticatedUser(user_id=owner)


def request_user(request: Request) -> AuthenticatedUser:
    user = getattr(request.state, "content_user", None)
    if not user:
        raise HTTPException(401, "请使用已验证的 VINote Bearer 登录凭证")
    content_bearer(user.user_id)
    return user


def protected_path(path: str) -> bool:
    return (path in {"/api/generate", "/api/generate_from_upload", "/api/content-service/capabilities",
                     "/api/content-service/video-source"}
            or path.startswith(("/api/task/", "/api/source-requests/")))


class ContentCredentialMiddleware:
    """Pure ASGI: the lease lasts through awaited background tasks, then revokes.

    BaseHTTPMiddleware would split context propagation. Copying this ContextVar
    to an executor copies the lease object, so a late copied context is revoked
    too. No token is passed in job arguments or persisted in operation receipts.
    """
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not protected_path(scope["path"]):
            return await self.app(scope, receive, send)
        request = Request(scope)
        authorization = request.headers.get("authorization", "")
        try:
            if not authorization.startswith("Bearer ") or not 1 <= len(authorization[7:]) <= 8192:
                raise HTTPException(401, "请使用 VINote Bearer 登录凭证")
            user = await anyio.to_thread.run_sync(lambda: verified_user(authorization[7:],
                provision=not scope["path"].startswith("/api/content-service/")))
        except HTTPException as error:
            return await JSONResponse({"detail": error.detail}, error.status_code)(scope, receive, send)
        body_limit = (settings.content_upload_max_bytes + 1024 * 1024
                      if request.headers.get("content-type", "").lower().startswith("multipart/form-data") else 65536)
        try:
            declared = int(request.headers.get("content-length", "0"))
            if declared < 0 or declared > body_limit:
                raise ValueError()
        except ValueError:
            return await JSONResponse({"detail": "请求内容超过服务限制"}, 413)(scope, receive, send)
        writing = scope["method"] == "POST"
        acquired = False
        if writing:
            acquired = _submission_slot.acquire(blocking=False)
            if not acquired:
                return await JSONResponse({"detail": "内容服务正在处理另一项请求，请稍后核验原提交"}, 429)(scope, receive, send)
        lease = CredentialLease(user.user_id, authorization[7:])
        context = _credential.set(lease)
        scope.setdefault("state", {})["content_user"] = user
        total = 0

        async def limited_receive():
            nonlocal total
            message = await receive()
            if message["type"] == "http.request":
                total += len(message.get("body", b""))
                if total > body_limit:
                    raise HTTPException(413, "上传内容超过服务限制，原文件仍保留在设备")
            return message
        try:
            await self.app(scope, limited_receive, send)
        finally:
            lease.active = False
            lease.bearer = ""
            _credential.reset(context)
            if acquired:
                _submission_slot.release()
