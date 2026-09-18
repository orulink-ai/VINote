from fastapi import APIRouter, Depends, HTTPException, Response, status

from app.models.auth import AuthenticatedUser
from app.models.team import TeamCreateRequest, TeamMemberCreateRequest, TeamSummaryResponse
from app.services.auth_service import get_current_user
from app.services.team_repository import TeamRepository

router = APIRouter(tags=["teams"])
_repository = TeamRepository()


@router.get("/teams", response_model=list[TeamSummaryResponse])
def list_teams(user: AuthenticatedUser = Depends(get_current_user)):
    return _repository.list_teams(user.user_id)


@router.post("/teams", response_model=TeamSummaryResponse, status_code=status.HTTP_201_CREATED)
def create_team(payload: TeamCreateRequest, user: AuthenticatedUser = Depends(get_current_user)):
    try:
        return _repository.create_team(user.user_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/teams/{team_id}", response_model=TeamSummaryResponse)
def get_team(team_id: str, user: AuthenticatedUser = Depends(get_current_user)):
    team = _repository.get_team(user.user_id, team_id)
    if not team:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Team not found")
    return team


@router.post("/teams/{team_id}/members", response_model=TeamSummaryResponse)
def add_team_member(
    team_id: str,
    payload: TeamMemberCreateRequest,
    user: AuthenticatedUser = Depends(get_current_user),
):
    try:
        team = _repository.add_member(user.user_id, team_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    if not team:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Team not found")
    return team


@router.delete("/teams/{team_id}/members/{member_id}", response_model=TeamSummaryResponse)
def remove_team_member(team_id: str, member_id: str, user: AuthenticatedUser = Depends(get_current_user)):
    try:
        team = _repository.remove_member(user.user_id, team_id, member_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    if not team:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Team or member not found")
    return team


@router.delete("/teams/{team_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_team(team_id: str, user: AuthenticatedUser = Depends(get_current_user)):
    try:
        deleted = _repository.delete_team(user.user_id, team_id)
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc

    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Team not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
