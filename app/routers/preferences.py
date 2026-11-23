from fastapi import APIRouter, Depends, HTTPException, Response

from app.config import settings
from app.models.auth import AuthenticatedUser
from app.models.preferences import PreferenceResponse, PreferenceUpdateRequest
from app.services.auth_service import get_current_user
from app.services.preferences_repository import PreferenceRepository

router = APIRouter(tags=["preferences"])
_repository = PreferenceRepository()
_HEADERS = {"Cache-Control": "private, no-store", "Vary": "Cookie, Authorization"}


@router.get("/preferences", response_model=PreferenceResponse)
def get_preferences(response: Response, user: AuthenticatedUser = Depends(get_current_user)):
    response.headers.update(_HEADERS)
    return _repository.get_preferences(user.user_id)


@router.patch("/preferences", response_model=PreferenceResponse)
def update_preferences(
    payload: PreferenceUpdateRequest,
    response: Response,
    user: AuthenticatedUser = Depends(get_current_user),
):
    response.headers.update(_HEADERS)
    if payload.visual_slides_auto_generate is not None and not settings.visual_slides_enabled:
        raise HTTPException(409, "视觉幻灯片功能已禁用", headers=_HEADERS)
    return _repository.update_preferences(
        user.user_id,
        language=payload.language,
        visual_slides_auto_generate=payload.visual_slides_auto_generate,
    )
