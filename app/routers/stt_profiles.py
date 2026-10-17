from fastapi import APIRouter, Depends, Response, status

from app.models.auth import AuthenticatedUser
from app.models.stt_profile import (
    LocalSTTSupportStatus,
    STTProfileCreateRequest,
    STTProfileResponse,
    STTProfileUpdateRequest,
)
from app.services.auth_service import get_current_user
from app.services.stt_profile_service import STTProfileService

router = APIRouter(tags=["stt-profiles"])
_service = STTProfileService()


@router.get("/stt-profiles", response_model=list[STTProfileResponse])
def list_stt_profiles(user: AuthenticatedUser = Depends(get_current_user)):
    return _service.list_profiles(user.user_id)


@router.get("/stt-profiles/local-support", response_model=LocalSTTSupportStatus)
def get_local_stt_support(_user: AuthenticatedUser = Depends(get_current_user)):
    return _service.get_local_support_status()


@router.post("/stt-profiles", response_model=STTProfileResponse, status_code=status.HTTP_201_CREATED)
def create_stt_profile(payload: STTProfileCreateRequest, user: AuthenticatedUser = Depends(get_current_user)):
    return _service.create_profile(user.user_id, payload)


@router.patch("/stt-profiles/{profile_id}", response_model=STTProfileResponse)
def update_stt_profile(
    profile_id: str,
    payload: STTProfileUpdateRequest,
    user: AuthenticatedUser = Depends(get_current_user),
):
    return _service.update_profile(user.user_id, profile_id, payload)


@router.delete("/stt-profiles/{profile_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_stt_profile(profile_id: str, user: AuthenticatedUser = Depends(get_current_user)):
    _service.delete_profile(user.user_id, profile_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/stt-profiles/{profile_id}/set-default", response_model=STTProfileResponse)
def set_default_stt_profile(profile_id: str, user: AuthenticatedUser = Depends(get_current_user)):
    return _service.set_default_profile(user.user_id, profile_id)


@router.post("/stt-profiles/{profile_id}/reveal-key")
def reveal_profile_key(profile_id: str, response: Response, user: AuthenticatedUser = Depends(get_current_user)):
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    return {"api_key": _service.reveal_api_key(user.user_id, profile_id)}
