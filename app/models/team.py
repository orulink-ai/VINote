from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

TeamRole = Literal["owner", "admin", "member"]


class TeamMemberResponse(BaseModel):
    id: str
    user_id: str
    email: str
    role: TeamRole
    joined_at: datetime


class TeamSummaryResponse(BaseModel):
    id: str
    name: str
    owner_id: str
    current_user_role: TeamRole
    member_count: int
    created_at: datetime
    updated_at: datetime
    members: list[TeamMemberResponse]


class TeamCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)


class TeamMemberCreateRequest(BaseModel):
    email: str = Field(min_length=3, max_length=255)
    role: Literal["admin", "member"] = "member"
