"""Cookie-authenticated desktop attendance confirmation, never notification."""
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.config import settings
from app.models.auth import AuthenticatedUser
from app.routers.feishu import ContactSelection
from app.services.auth_service import get_current_user
from app.services import meeting_participants as participants

router = APIRouter(prefix="/meeting-participants", tags=["meeting-participants"])


class ConfirmParticipants(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    confirmed: Literal[True]
    task_id: str = Field(pattern=r"^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$")
    evidence_revision: str = Field(pattern=r"^[a-f0-9]{64}$")
    confirmation_revision: int = Field(ge=0)
    contacts: list[ContactSelection] = Field(max_length=20)

    @field_validator("confirmed", mode="before")
    @classmethod
    def explicit_confirmation(cls, value):
        if value is not True:
            raise ValueError("请明确确认本会议实际参会人")
        return value


def _context(request: Request, response: Response, user: AuthenticatedUser = Depends(get_current_user)):
    from app.services.feishu_cli import enabled
    from app.services.feishu_service import FeishuService

    response.headers["Cache-Control"] = "no-store"
    if (not settings.desktop_runtime or settings.workspace_cloud_runtime or settings.content_cloud_runtime
            or request.headers.get("authorization") or not enabled()):
        raise HTTPException(403, "参会人确认仅供当前桌面账号使用")
    provider = FeishuService().for_owner(user.user_id)
    provider.user_token(user.user_id)
    binding = provider.contact_binding(user.user_id)
    if binding.get("owner") != user.user_id:
        raise HTTPException(409, "飞书连接与当前桌面账号不匹配")
    return provider, user.user_id


@router.get("/{note_key}")
def get_participants(note_key: str, context=Depends(_context)):
    provider, owner = context
    return participants.get_meeting_participants(provider, owner, note_key)


@router.put("/{note_key}")
def confirm_participants(note_key: str, payload: ConfirmParticipants, context=Depends(_context)):
    provider, owner = context
    result = participants.confirm_meeting_participants(provider, owner, note_key,
        confirmed=payload.confirmed, task_id=payload.task_id, evidence_revision=payload.evidence_revision,
        confirmation_revision=payload.confirmation_revision,
        contacts=[item.model_dump() for item in payload.contacts])
    from app.services.feishu_auto_runtime import resume_participants
    resume_participants(owner, note_key)
    return result
