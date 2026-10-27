"""Desktop Cookie-only association; no proxy, node creation or continuation."""
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.config import settings
from app.models.auth import AuthenticatedUser
from app.services.auth_service import get_current_user
from app.services import feishu_meeting_wiki_recovery as recovery

router = APIRouter(prefix='/feishu/meeting-containers/by-delivery', tags=['feishu'])


class Recovery(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    expected_user_id: str = Field(min_length=1, max_length=128)
    confirmed: Literal[True]
    context_revision: str = Field(pattern=r'^[a-f0-9]{64}$')
    url: str = Field(min_length=1, max_length=2048)

    @field_validator('confirmed', mode='before')
    @classmethod
    def explicit_confirmation(cls, value):
        if value is not True:
            raise ValueError('请明确确认关联已有会议目录')
        return value


def _context(request: Request, response: Response, user: AuthenticatedUser = Depends(get_current_user)):
    from app.services.feishu_cli import enabled
    from app.services.feishu_service import FeishuService
    response.headers['Cache-Control'] = 'no-store'
    if (not settings.desktop_runtime or settings.workspace_cloud_runtime or settings.content_cloud_runtime
            or request.headers.get('authorization') or not enabled()):
        raise HTTPException(403, '会议目录恢复仅供当前桌面账号使用')
    return FeishuService().for_owner(user.user_id), user.user_id


@router.get('/{delivery_id}')
def read(delivery_id: str, context=Depends(_context)):
    service, owner = context
    return recovery.read_container(service, owner, delivery_id)


@router.post('/{delivery_id}/recover')
def associate(delivery_id: str, payload: Recovery, context=Depends(_context)):
    service, owner = context
    return recovery.recover_for_delivery(service, owner, delivery_id, **payload.model_dump())
