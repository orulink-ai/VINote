from dataclasses import dataclass

from pydantic import BaseModel, Field


@dataclass
class AuthenticatedUser:
    user_id: str
    email: str | None = None


class AuthCredentials(BaseModel):
    email: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=6, max_length=128)


class UserResponse(BaseModel):
    id: str
    email: str


class AuthResponse(UserResponse):
    """登录结果；Cookie 供桌面端使用，Bearer Token 供移动端使用。"""

    access_token: str
    token_type: str = "bearer"


class SessionResponse(BaseModel):
    authenticated: bool
    user: UserResponse | None = None
