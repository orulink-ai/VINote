from fastapi import APIRouter, Depends, Response, status

from app.models.auth import AuthenticatedUser
from app.models.model_profile import (
    ModelProfileCreateRequest,
    ModelProfileResponse,
    ModelProfileTestRequest,
    ModelProfileTestResponse,
    ModelProfileUpdateRequest,
)
from app.services.auth_service import get_current_user
from app.services.model_profile_service import ModelProfileService

router = APIRouter(tags=["model-profiles"])
_service = ModelProfileService()


@router.get("/model-profiles", response_model=list[ModelProfileResponse])
def list_model_profiles(user: AuthenticatedUser = Depends(get_current_user)):
    return _service.list_profiles(user.user_id)


@router.post("/model-profiles", response_model=ModelProfileResponse, status_code=status.HTTP_201_CREATED)
def create_model_profile(payload: ModelProfileCreateRequest, user: AuthenticatedUser = Depends(get_current_user)):
    return _service.create_profile(user.user_id, payload)


@router.patch("/model-profiles/{profile_id}", response_model=ModelProfileResponse)
def update_model_profile(
    profile_id: str,
    payload: ModelProfileUpdateRequest,
    user: AuthenticatedUser = Depends(get_current_user),
):
    return _service.update_profile(user.user_id, profile_id, payload)


@router.delete("/model-profiles/{profile_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_model_profile(profile_id: str, user: AuthenticatedUser = Depends(get_current_user)):
    _service.delete_profile(user.user_id, profile_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/model-profiles/{profile_id}/set-default", response_model=ModelProfileResponse)
def set_default_model_profile(profile_id: str, user: AuthenticatedUser = Depends(get_current_user)):
    return _service.set_default_profile(user.user_id, profile_id)


@router.post("/model-profiles/test", response_model=ModelProfileTestResponse)
def test_model_profile(payload: ModelProfileTestRequest, user: AuthenticatedUser = Depends(get_current_user)):
    return _service.test_connection(payload)


@router.post("/model-profiles/{profile_id}/test", response_model=ModelProfileTestResponse)
def test_saved_model_profile(profile_id: str, user: AuthenticatedUser = Depends(get_current_user)):
    return _service.test_saved_profile(user.user_id, profile_id)


@router.post("/model-profiles/{profile_id}/reveal-key")
def reveal_profile_key(profile_id: str, response: Response, user: AuthenticatedUser = Depends(get_current_user)):
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    return {"api_key": _service.reveal_api_key(user.user_id, profile_id)}
