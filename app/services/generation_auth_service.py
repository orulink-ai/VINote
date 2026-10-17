"""Generation accepts local sessions and verified, already-linked cloud accounts."""
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select

from app.config import settings
from app.db import session_scope
from app.db_models import CloudAccountDB
from app.models.auth import AuthenticatedUser
from app.services.auth_service import get_optional_current_user as local_user
from app.services.cloud_account_service import _request

_bearer = HTTPBearer(auto_error=False)


def get_optional_generation_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> AuthenticatedUser | None:
    try:
        user = local_user(request, credentials)
        if user is None and (credentials or request.cookies.get(settings.auth_cookie_name)):
            raise HTTPException(401, "当前登录身份无效，请重新登录")
        return user
    except HTTPException as error:
        if error.status_code != 401 or not credentials or request.cookies.get(settings.auth_cookie_name):
            raise
    # Never decode unverified cloud claims or bind accounts by email alone.
    identity = _request("user", token=credentials.credentials)
    if not identity.get("id") or not identity.get("email_confirmed_at") or identity.get("is_anonymous"):
        raise HTTPException(401, "请验证 VINote 账号后重试")
    with session_scope() as db:
        account = db.scalar(select(CloudAccountDB).where(
            CloudAccountDB.issuer == settings.cloud_auth_url,
            CloudAccountDB.subject == identity["id"],
        ))
        if not account:
            raise HTTPException(403, "当前账号尚未连接此内容服务，请先在桌面端登录同一 VINote 账号")
        return AuthenticatedUser(user_id=account.user_id, email=identity.get("email"))


def get_generation_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> AuthenticatedUser:
    user = get_optional_generation_user(request, credentials)
    if not user:
        raise HTTPException(401, "Authentication required")
    return user
