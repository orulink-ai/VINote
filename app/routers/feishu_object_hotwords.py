"""Cookie-authenticated desktop CLI object aliases; never a cloud/proxy route."""
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from app.config import settings
from app.models.auth import AuthenticatedUser
from app.services.auth_service import get_current_user
from app.services import feishu_object_hotwords as hotwords

router = APIRouter(prefix="/feishu/object-hotwords", tags=["feishu"])


class CreateAlias(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    alias: str = Field(min_length=1, max_length=50)
    target_id: str = Field(min_length=1, max_length=200)


def _context(request: Request, response: Response,
             user: AuthenticatedUser = Depends(get_current_user)):
    response.headers["Cache-Control"] = "no-store"
    service = hotwords.service
    if (not settings.desktop_runtime or settings.workspace_cloud_runtime or settings.content_cloud_runtime or
            request.headers.get("authorization") or not service.enabled()):
        raise HTTPException(403, "对象别称仅供已启用飞书 CLI 的桌面使用")
    # Local account mapping is shared with contacts/groups, but import lazily to
    # avoid a service/router cycle during main's route registration.
    from app.routers.feishu import principal
    from app.services.feishu_service import FeishuService

    owner, local_user_id = principal(request)
    if local_user_id != user.user_id:
        raise HTTPException(403, "请使用当前桌面账号访问对象别称")
    provider = FeishuService().for_owner(owner)
    # contact_binding reads DB metadata only. Verify the real CLI profile/user
    # first; the CLI owns any necessary token refresh. Never disclose a stale
    # profile's objects or mutate aliases when this verification fails.
    provider.user_token(owner)
    binding = provider.contact_binding(owner)
    # Validate against the same current provider before any cached disclosure.
    service._assert_current(owner, binding)
    return service, provider, owner, binding


@router.get("")
def list_hotwords(context=Depends(_context)):
    service, _, owner, binding = context
    return service.snapshot(owner, binding)


@router.post("/refresh")
def refresh_hotwords(context=Depends(_context)):
    service, provider, owner, binding = context
    # A bounded has-chatted contact page joins the visible-group/search cache.
    # Even has_more=false completes only this filtered page, not a directory.
    page = provider.refresh_objects(owner)
    result = service.refresh(owner, binding)
    return {**result, "has_more": page["has_more"], "partial": True}


@router.post("")
def create_alias(payload: CreateAlias, context=Depends(_context)):
    service, _, owner, binding = context
    service.add_alias(owner, binding, payload.alias, payload.target_id)
    return service.snapshot(owner, binding)


@router.delete("/{alias_id}")
def delete_alias(alias_id: str, context=Depends(_context)):
    service, _, owner, binding = context
    service.delete_alias(owner, binding, alias_id)
    return service.snapshot(owner, binding)
