from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from app.models.auth import AuthCredentials, AuthResponse, SessionResponse, UserResponse
from app.services.auth_service import (
    authenticate_user,
    clear_auth_cookie,
    create_access_token,
    create_user,
    get_current_user,
    get_optional_current_user,
    get_user_by_id,
    set_auth_cookie,
)

from app.services.auth_audit_service import record_login
router = APIRouter(tags=["auth"])


from pydantic import BaseModel, Field
from app.config import settings
from app.services.cloud_account_service import CloudAccountService


class LoginEmail(BaseModel):
    email: str = Field(min_length=3, max_length=254, pattern=r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


class LoginCode(LoginEmail):
    code: str = Field(min_length=6, max_length=10, pattern=r"^\d+$")


class ResetPassword(LoginCode):
    password: str = Field(min_length=6, max_length=128)


@router.post("/auth/password/code")
def password_code(payload: LoginEmail):
    return CloudAccountService().request_password_reset(payload.email)


@router.post("/auth/password/reset")
def password_reset(payload: ResetPassword, response: Response):
    response.headers["Cache-Control"] = "no-store"
    return CloudAccountService().reset_password(payload.email, payload.code, payload.password)


@router.get("/auth/config")
def auth_config():
    return {"email_code": bool(settings.cloud_auth_url and settings.cloud_auth_public_key)}


@router.post("/auth/code")
def login_code(payload: LoginEmail):
    return CloudAccountService().send_code(None, payload.email)


@router.post("/auth/verify", response_model=AuthResponse)
def login_verify(payload: LoginCode, response: Response, request: Request):
    user = CloudAccountService().login(payload.email, payload.code)
    record_login(user.id, request)
    token = create_access_token(user)
    set_auth_cookie(response, token)
    response.headers["Cache-Control"] = "no-store"
    return AuthResponse(**user.model_dump(), access_token=token)


@router.post("/auth/sign-up", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
def sign_up(payload: AuthCredentials, response: Response, request: Request):
    if settings.cloud_auth_url:
        raise HTTPException(400, "请通过邮箱验证注册 VINote 账号")
    user = create_user(payload)
    record_login(user.id, request)
    token = create_access_token(user)
    set_auth_cookie(response, token)
    return AuthResponse(**user.model_dump(), access_token=token)


@router.post("/auth/sign-in", response_model=AuthResponse)
def sign_in(payload: AuthCredentials, response: Response, request: Request):
    user = CloudAccountService().password_login(payload.email, payload.password) if settings.cloud_auth_url else authenticate_user(payload)
    record_login(user.id, request)
    token = create_access_token(user)
    set_auth_cookie(response, token)
    return AuthResponse(**user.model_dump(), access_token=token)


@router.post("/auth/sign-out", status_code=status.HTTP_204_NO_CONTENT)
def sign_out(response: Response, user=Depends(get_optional_current_user)):
    # 普通退出仅清除当前终端凭证，不能删除其他终端仍在使用的共享云端会话。
    clear_auth_cookie(response)
    response.status_code = status.HTTP_204_NO_CONTENT


@router.get("/auth/me", response_model=UserResponse)
def me(user=Depends(get_current_user)):
    current = get_user_by_id(user.user_id)
    if not current:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")
    return current


@router.get("/auth/session", response_model=SessionResponse)
def session(user=Depends(get_optional_current_user)):
    if not user:
        return SessionResponse(authenticated=False, user=None)

    current = get_user_by_id(user.user_id)
    if not current:
        return SessionResponse(authenticated=False, user=None)

    return SessionResponse(authenticated=True, user=current)


@router.post("/auth/register/code")
def register_code(payload: AuthCredentials):
    return CloudAccountService().register(payload.email, payload.password)


@router.post("/auth/register/verify", response_model=AuthResponse)
def register_verify(payload: LoginCode, response: Response, request: Request):
    user = CloudAccountService().confirm_registration(payload.email, payload.code)
    record_login(user.id, request)
    token = create_access_token(user)
    set_auth_cookie(response, token)
    response.headers["Cache-Control"] = "no-store"
    return AuthResponse(**user.model_dump(), access_token=token)
