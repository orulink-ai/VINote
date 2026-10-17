from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, HTTPException, Request, Response, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from passlib.context import CryptContext
from sqlalchemy import select

from app.config import settings
from app.db import session_scope
from app.db_models import CloudAccountDB, UserDB
from app.models.auth import AuthCredentials, AuthenticatedUser, UserResponse

_bearer = HTTPBearer(auto_error=False)
_password_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def _normalize_email(email: str) -> str:
    return email.strip().lower()


def hash_password(password: str) -> str:
    return _password_context.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    return _password_context.verify(password, password_hash)


def create_user(payload: AuthCredentials) -> UserResponse:
    email = _normalize_email(payload.email)
    with session_scope() as db:
        existing = db.scalar(select(UserDB).where(UserDB.email == email))
        if existing:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered")

        user = UserDB(email=email, password_hash=hash_password(payload.password))
        db.add(user)
        db.flush()
        return UserResponse(id=user.id, email=user.email)


def authenticate_user(payload: AuthCredentials) -> UserResponse:
    email = _normalize_email(payload.email)
    with session_scope() as db:
        user = db.scalar(select(UserDB).where(UserDB.email == email))
        if not user or not verify_password(payload.password, user.password_hash):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")

        return UserResponse(id=user.id, email=user.email)


def get_user_by_id(user_id: str) -> UserResponse | None:
    with session_scope() as db:
        user = db.get(UserDB, user_id)
        if not user:
            return None
        return UserResponse(id=user.id, email=user.email)


def create_access_token(user: UserResponse) -> str:
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=settings.access_token_expire_seconds)
    payload = {
        "sub": user.id,
        "email": user.email,
        "exp": expires_at,
    }
    return jwt.encode(payload, settings.app_jwt_secret, algorithm="HS256")


def set_auth_cookie(response: Response, token: str):
    response.set_cookie(
        key=settings.auth_cookie_name,
        value=token,
        httponly=True,
        secure=settings.auth_cookie_secure,
        samesite=settings.auth_cookie_samesite,
        max_age=settings.access_token_expire_seconds,
        domain=settings.auth_cookie_domain or None,
        path="/",
    )


def clear_auth_cookie(response: Response):
    response.delete_cookie(
        key=settings.auth_cookie_name,
        domain=settings.auth_cookie_domain or None,
        path="/",
        samesite=settings.auth_cookie_samesite,
    )


def _decode_token(token: str) -> AuthenticatedUser:
    try:
        payload = jwt.decode(token, settings.app_jwt_secret, algorithms=["HS256"])
    except jwt.InvalidTokenError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid access token") from exc

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid access token payload")

    return AuthenticatedUser(user_id=user_id, email=payload.get("email"))


def _uses_current_account_project(user_id: str) -> bool:
    if not settings.cloud_auth_url:
        return True
    with session_scope() as db:
        account = db.get(CloudAccountDB, user_id)
        return bool(account and account.issuer == settings.cloud_auth_url)


def _extract_token(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None,
) -> str | None:
    cookie_token = request.cookies.get(settings.auth_cookie_name)
    if cookie_token:
        return cookie_token
    if credentials:
        return credentials.credentials
    return None


def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> AuthenticatedUser:
    token = _extract_token(request, credentials)
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")
    user = _decode_token(token)
    if not _uses_current_account_project(user.user_id):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Please sign in to the current account project")
    return user


def get_optional_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> AuthenticatedUser | None:
    token = _extract_token(request, credentials)
    if not token:
        return None
    user = _decode_token(token)
    return user if _uses_current_account_project(user.user_id) else None
