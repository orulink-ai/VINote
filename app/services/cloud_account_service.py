"""VINote-owned Supabase identity; tokens stay in the backend."""
import base64
import hashlib
import json
import logging
import threading
import time

import httpx
from cryptography.fernet import Fernet
from fastapi import HTTPException
from sqlalchemy import select

from app.config import settings
from app.db import session_scope
from app.db_models import CloudAccountDB

# Serialize refresh-token rotation in this process; the DB row lock covers workers.
_locks = [threading.RLock() for _ in range(64)]


def _lock(user_id):
    return _locks[int(hashlib.sha256(user_id.encode()).hexdigest(), 16) % len(_locks)]


def _cipher():
    if not settings.model_profile_encryption_key:
        raise HTTPException(503, "云端会话加密尚未配置")
    digest = hashlib.sha256(settings.model_profile_encryption_key.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def _request(path, payload=None, token=None, method=None):
    if not settings.cloud_auth_url or not settings.cloud_auth_public_key:
        raise HTTPException(503, "VINote 云端账号服务尚未配置")
    headers = {"apikey": settings.cloud_auth_public_key}
    if token:
        headers["Authorization"] = "Bearer " + token
    try:
        response = httpx.request(method or ("GET" if payload is None else "POST"),
                                 settings.cloud_auth_url + "/auth/v1/" + path,
                                 headers=headers, json=payload, timeout=20,
                                 follow_redirects=False)
    except httpx.RequestError as exc:
        # 仅记录异常类型，避免输出请求头、密码或令牌。
        logging.getLogger(__name__).warning("VINote account transport failed: %s", type(exc).__name__)
        raise HTTPException(502, "无法连接 VINote 账号服务") from None
    if not response.is_success:
        if response.status_code == 429:
            raise HTTPException(429, "操作过于频繁，请稍后重试")
        try:
            code = response.json().get("error_code", "")
        except (ValueError, AttributeError):
            code = ""
        messages = {
            "invalid_credentials": "邮箱或密码不正确；曾使用验证码登录的账号，请通过忘记密码设置登录密码。",
            "email_not_confirmed": "邮箱尚未验证，请完成注册验证后登录。",
            "otp_expired": "验证码无效或已过期，请获取新验证码。",
            "weak_password": "密码不符合安全要求，请使用更长且包含字母和数字的密码。",
            "same_password": "新密码不能与当前密码相同。",
            "user_already_exists": "账号已注册，请登录或使用忘记密码。",
            "email_exists": "邮箱已注册，请登录或使用忘记密码。",
        }
        if response.status_code >= 500:
            raise HTTPException(502, "账号服务暂时不可用，请稍后重试。")
        raise HTTPException(401 if code in {"invalid_credentials", "otp_expired"} else 400,
                            messages.get(code, "账号请求未成功，请稍后重试或联系管理员。"))
    return response.json() if response.content else {}


class CloudAccountService:
    def status(self, user_id):
        with session_scope() as db:
            row = db.get(CloudAccountDB, user_id)
            linked = bool(row and row.issuer == settings.cloud_auth_url)
            return {"configured": bool(settings.cloud_auth_url and settings.cloud_auth_public_key),
                    "authenticated": linked, "email": row.email if linked else None}

    def send_code(self, user_id, email):
        _cipher()
        _request("otp", {"email": email, "create_user": True})
        return {"message": "验证码已发送，请检查邮箱"}

    def verify_code(self, user_id, email, code):
        session = _request("verify", {"email": email, "token": code, "type": "email"})
        identity = _request("user", token=session["access_token"])
        return self.store_session(user_id, session, identity)

    def login(self, email, code):
        """A verified VINote identity opens both the app and model session."""
        _cipher()
        session = _request("verify", {"email": email, "token": code, "type": "email"})
        return self.finish_login(session)

    def password_login(self, email, password):
        _cipher()
        session = _request("token?grant_type=password", {"email": email, "password": password})
        return self.finish_login(session)

    def request_password_reset(self, email):
        _request("recover", {"email": email.strip().lower()})
        return {"message": "若邮箱已注册，将收到重设密码验证码，请检查邮箱。"}

    def reset_password(self, email, code, password):
        # Only a freshly verified recovery OTP may authorize this update.
        session = _request("verify", {"email": email.strip().lower(), "token": code, "type": "recovery"})
        _request("user", {"password": password}, token=session["access_token"], method="PUT")
        return {"message": "密码已更新，请使用新密码登录。"}

    def register(self, email, password):
        _cipher()
        _request("signup", {"email": email, "password": password})
        return {"message": "请查收注册验证码；已注册账号请直接登录"}

    def confirm_registration(self, email, code):
        session = _request("verify", {"email": email, "token": code, "type": "signup"})
        return self.finish_login(session)

    def finish_login(self, session):
        import secrets
        from app.db_models import UserDB
        from app.models.auth import UserResponse
        from app.services.auth_service import hash_password
        identity = _request("user", token=session["access_token"])
        if not identity.get("email_confirmed_at") or identity.get("is_anonymous"):
            raise HTTPException(403, "请先验证邮箱")
        with session_scope() as db:
            linked = db.scalar(select(CloudAccountDB).where(
                CloudAccountDB.issuer == settings.cloud_auth_url,
                CloudAccountDB.subject == identity["id"]))
            user = db.get(UserDB, linked.user_id) if linked else db.scalar(
                select(UserDB).where(UserDB.email == identity["email"].strip().lower()))
            if not user:
                user = UserDB(email=identity["email"].strip().lower(), password_hash=hash_password(secrets.token_urlsafe(32)))
                db.add(user)
                db.flush()
            existing = db.get(CloudAccountDB, user.id)
            if existing and (existing.issuer != settings.cloud_auth_url or existing.subject != identity["id"]):
                raise HTTPException(409, "账号身份不匹配，请联系管理员")
            result = UserResponse(id=user.id, email=user.email)
        self.store_session(result.id, session, identity)
        return result

    def store_session(self, user_id, session, identity):
        cipher = _cipher()
        if not identity.get("email_confirmed_at") or identity.get("is_anonymous"):
            raise HTTPException(403, "请先验证邮箱")
        with _lock(user_id), session_scope() as db:
            from app.db_models import UserDB
            user = db.get(UserDB, user_id)
            if not user or user.email.strip().lower() != identity["email"].strip().lower():
                raise HTTPException(409, "云端身份必须与当前 VINote 账号邮箱一致")
            existing = db.scalar(select(CloudAccountDB).where(
                CloudAccountDB.issuer == settings.cloud_auth_url,
                CloudAccountDB.subject == identity["id"]))
            if existing and existing.user_id != user_id:
                raise HTTPException(409, "此云端账号已关联其他 VINote 账号")
            row = db.get(CloudAccountDB, user_id)
            if row and (row.issuer != settings.cloud_auth_url or row.subject != identity["id"]):
                raise HTTPException(409, "账号身份不匹配，请联系管理员")
            if not row:
                row = CloudAccountDB(user_id=user_id)
                db.add(row)
            row.issuer, row.subject, row.email = settings.cloud_auth_url, identity["id"], identity["email"]
            row.session_encrypted = cipher.encrypt(json.dumps(self._session(session)).encode()).decode()
        return self.status(user_id)

    @staticmethod
    def _session(data):
        return {"access_token": data["access_token"], "refresh_token": data["refresh_token"],
                "expires_at": data.get("expires_at") or time.time() + data.get("expires_in", 3600)}

    def access_token(self, user_id):
        with _lock(user_id), session_scope() as db:
            row = db.scalar(select(CloudAccountDB).where(CloudAccountDB.user_id == user_id).with_for_update())
            if not row or row.issuer != settings.cloud_auth_url:
                raise HTTPException(401, "当前会话没有云端凭证，请退出后重新登录")
            cipher = _cipher()
            session = json.loads(cipher.decrypt(row.session_encrypted.encode()))
            if session["expires_at"] <= time.time() + 60:
                session = self._session(_request("token?grant_type=refresh_token",
                                                {"refresh_token": session["refresh_token"]}))
                row.session_encrypted = cipher.encrypt(json.dumps(session).encode()).decode()
            return session["access_token"]

    def disconnect(self, user_id):
        token = None
        with _lock(user_id), session_scope() as db:
            row = db.get(CloudAccountDB, user_id)
            if row:
                if row.issuer == settings.cloud_auth_url:
                    token = json.loads(_cipher().decrypt(row.session_encrypted.encode())).get("access_token")
                db.delete(row)
        revoked = True
        if token:
            try:
                _request("logout?scope=local", {}, token)
            except HTTPException:
                revoked = False
        return {"authenticated": False, "remote_revoked": revoked}
