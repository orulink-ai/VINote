"""Owner-scoped device display associations, without processing permissions."""
from fastapi import APIRouter, Depends, HTTPException, Request, Response

from app.config import settings
from app.models.auth import AuthenticatedUser
from app.models.meeting_source_link import ConfirmMeetingSourceLink
from app.services.auth_service import get_current_user
from app.services.meeting_source_link import MeetingSourceLinkService

router = APIRouter(prefix='/meeting-source-links', tags=['meeting-source-links'])


def _owner(request: Request, response: Response, user: AuthenticatedUser = Depends(get_current_user)):
    response.headers['Cache-Control'] = 'no-store'
    if (not settings.desktop_runtime or settings.workspace_cloud_runtime
            or settings.content_cloud_runtime or request.headers.get('authorization')):
        raise HTTPException(403, '归档关联仅供当前设备登录账号使用')
    return user.user_id


@router.get('/targets')
def targets(owner=Depends(_owner)):
    return MeetingSourceLinkService().targets(owner)


@router.get('/{note_id}')
def association(note_id: str, owner=Depends(_owner)):
    return MeetingSourceLinkService().get(owner, note_id)


@router.put('/{note_id}')
def confirm(note_id: str, payload: ConfirmMeetingSourceLink, owner=Depends(_owner)):
    return MeetingSourceLinkService().confirm(owner, note_id, payload)
