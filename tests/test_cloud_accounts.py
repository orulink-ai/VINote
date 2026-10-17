import json
import time
from contextlib import contextmanager

import pytest
from fastapi import HTTPException
from fastapi import Request
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db import Base
from app.db_models import CloudAccountDB, UserDB
from app.services import cloud_account_service as module
from app.services import auth_service
from app.models.auth import UserResponse


@pytest.fixture
def cloud(monkeypatch, tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'accounts.db'}")
    Base.metadata.create_all(engine)
    @contextmanager
    def sessions():
        with Session(engine) as db:
            with db.begin():
                yield db
    monkeypatch.setattr(module, "session_scope", sessions)
    monkeypatch.setattr(module.settings, "cloud_auth_url", "https://vinote.supabase.co")
    monkeypatch.setattr(module.settings, "cloud_auth_public_key", "sb_publishable_test")
    monkeypatch.setattr(module.settings, "model_profile_encryption_key", "test-encryption")
    yield module.CloudAccountService(), sessions
    engine.dispose()


def test_old_project_session_cannot_authenticate_after_account_switch(cloud, monkeypatch):
    _, sessions = cloud
    monkeypatch.setattr(auth_service, "session_scope", sessions)
    with sessions() as db:
        db.add(UserDB(id="local-a", email="user@example.com", password_hash="unused"))
        db.add(CloudAccountDB(user_id="local-a", issuer="https://old.supabase.co",
                              subject="old-subject", email="user@example.com",
                              session_encrypted="old-session"))
    token = auth_service.create_access_token(UserResponse(id="local-a", email="user@example.com"))
    request = Request({"type": "http", "headers": [
        (b"cookie", f"{auth_service.settings.auth_cookie_name}={token}".encode())]})
    assert auth_service.get_optional_current_user(request, None) is None
    with pytest.raises(HTTPException) as error:
        auth_service.get_current_user(request, None)
    assert error.value.status_code == 401

    with sessions() as db:
        db.get(CloudAccountDB, "local-a").issuer = module.settings.cloud_auth_url
    assert auth_service.get_current_user(request, None).user_id == "local-a"


def test_login_stores_encrypted_personal_session_and_rejects_cross_account_link(cloud, monkeypatch):
    service, sessions = cloud
    from app.db_models import UserDB
    with sessions() as db:
        db.add(UserDB(id="local-a", email="a@example.com", password_hash="unused"))
    def request(path, payload=None, token=None):
        if path == "verify":
            return {"access_token": "personal-token", "refresh_token": "refresh-secret", "expires_in": 3600}
        assert path == "user" and token == "personal-token"
        return {"id": "subject-a", "email": "a@example.com", "email_confirmed_at": "2026-09-09"}
    monkeypatch.setattr(module, "_request", request)
    result = service.verify_code("local-a", "a@example.com", "123456")
    assert result["authenticated"]
    assert "token" not in json.dumps(result)
    with sessions() as db:
        assert "personal-token" not in db.get(CloudAccountDB, "local-a").session_encrypted
    assert service.access_token("local-a") == "personal-token"
    with pytest.raises(HTTPException) as error:
        service.verify_code("local-b", "a@example.com", "123456")
    assert error.value.status_code == 409


def test_binding_cannot_replace_email_or_subject(cloud):
    from app.db_models import UserDB
    service, sessions = cloud
    with sessions() as db:
        db.add(UserDB(id="local-a", email="a@example.com", password_hash="unused"))
    session = {"access_token": "original", "refresh_token": "refresh", "expires_in": 3600}
    identity = {"id": "subject-a", "email": "a@example.com", "email_confirmed_at": "2026-09-09"}
    service.store_session("local-a", session, identity)
    for replacement in [dict(identity, email="b@example.com"), dict(identity, id="subject-b")]:
        with pytest.raises(HTTPException) as error:
            service.store_session("local-a", dict(session, access_token="replacement"), replacement)
        assert error.value.status_code == 409
        assert service.access_token("local-a") == "original"


def test_refresh_rotates_and_is_not_repeated(cloud, monkeypatch):
    service, sessions = cloud
    with sessions() as db:
        db.add(CloudAccountDB(user_id="local-a", issuer=module.settings.cloud_auth_url,
                             subject="a", email="a@example.com",
                             session_encrypted=module._cipher().encrypt(json.dumps({
                                 "access_token": "old", "refresh_token": "refresh-old", "expires_at": 0
                             }).encode()).decode()))
    calls = []
    def request(path, payload=None, token=None):
        calls.append(path)
        assert payload == {"refresh_token": "refresh-old"}
        return {"access_token": "new", "refresh_token": "refresh-new", "expires_at": time.time() + 3600}
    monkeypatch.setattr(module, "_request", request)
    assert service.access_token("local-a") == "new"
    assert service.access_token("local-a") == "new"
    assert len(calls) == 1
    monkeypatch.setattr(module.settings, "cloud_auth_url", "https://other.supabase.co")
    with pytest.raises(HTTPException):
        service.access_token("local-a")


def test_cloud_uses_user_token_not_shared_key(monkeypatch):
    from app.services.vilab_cloud_service import VILabCloudService
    import httpx
    monkeypatch.setattr(module.settings, "cloud_auth_url", "https://vinote.supabase.co")
    monkeypatch.setattr(module.settings, "vilab_server_url", "http://127.0.0.1:9878")
    monkeypatch.setattr(module.CloudAccountService, "access_token", lambda self, user: "personal-" + user)
    def request(method, url, **kwargs):
        assert kwargs["headers"]["Authorization"] == "Bearer personal-user-a"
        assert url == "http://127.0.0.1:9878/v1/models"
        return httpx.Response(200, json={"data": []})
    monkeypatch.setattr(httpx, "request", request)
    assert VILabCloudService().models("user-a") == []


def test_unified_login_preserves_existing_user_and_gets_model_token(cloud, monkeypatch):
    from app.db_models import UserDB
    service, sessions = cloud
    with sessions() as db:
        db.add(UserDB(id="existing-user", email="a@example.com", password_hash="unused"))
    def request(path, payload=None, token=None):
        if path == "verify":
            return {"access_token": "personal-token", "refresh_token": "refresh", "expires_in": 3600}
        return {"id": "verified-subject", "email": "a@example.com", "email_confirmed_at": "2026-09-09"}
    monkeypatch.setattr(module, "_request", request)
    user = service.login("a@example.com", "12345678")
    assert user.id == "existing-user"
    assert service.access_token(user.id) == "personal-token"
    assert "token" not in user.model_dump_json()
    assert service.login("a@example.com", "12345678").id == user.id


def test_unified_login_rejects_unverified_email(cloud, monkeypatch):
    service, sessions = cloud
    monkeypatch.setattr(module, "_request", lambda path, *args, **kwargs:
        {"access_token": "untrusted"} if path == "verify" else {"id": "a", "email": "a@example.com"})
    with pytest.raises(HTTPException) as error:
        service.login("a@example.com", "12345678")
    assert error.value.status_code == 403


def test_password_login_uses_supabase_password_grant(cloud, monkeypatch):
    service, _ = cloud
    calls = []
    def request(path, payload=None, token=None):
        calls.append((path, payload))
        return {"access_token": "token"}
    monkeypatch.setattr(module, "_request", request)
    monkeypatch.setattr(service, "finish_login", lambda session: "signed-in")
    assert service.password_login("a@example.com", "password") == "signed-in"
    assert calls == [("token?grant_type=password", {"email": "a@example.com", "password": "password"})]


def test_registration_sets_password_and_verifies_signup_code(cloud, monkeypatch):
    service, _ = cloud
    calls = []
    monkeypatch.setattr(module, "_request", lambda path, payload=None, token=None: calls.append((path, payload)) or {})
    monkeypatch.setattr(service, "finish_login", lambda session: "registered")
    service.register("a@example.com", "password")
    assert calls[0] == ("signup", {"email": "a@example.com", "password": "password"})
    assert service.confirm_registration("a@example.com", "12345678") == "registered"
    assert calls[1][1]["type"] == "signup"


def test_recovery_requires_verified_otp_before_password_update(cloud, monkeypatch):
    service, _ = cloud
    calls = []
    def request(path, payload=None, token=None, method=None):
        calls.append((path, payload, token, method))
        if path == "verify":
            assert payload["type"] == "recovery"
            return {"access_token": "recovery-session"}
        assert token == "recovery-session" and method == "PUT"
        return {}
    monkeypatch.setattr(module, "_request", request)
    result = service.reset_password("A@example.com", "12345678", "new-password")
    assert calls[0][1]["email"] == "a@example.com"
    assert calls[1][1] == {"password": "new-password"}
    assert "recovery-session" not in json.dumps(result)


def test_recovery_invalid_otp_never_changes_password(cloud, monkeypatch):
    service, _ = cloud
    calls = []
    def request(path, *args, **kwargs):
        calls.append(path)
        raise HTTPException(401, "invalid OTP")
    monkeypatch.setattr(module, "_request", request)
    with pytest.raises(HTTPException):
        service.reset_password("a@example.com", "12345678", "new-password")
    assert calls == ["verify"]


@pytest.mark.parametrize("code,status,expected", [
    ("invalid_credentials", 400, "忘记密码"),
    ("email_not_confirmed", 400, "邮箱尚未验证"),
    ("otp_expired", 403, "验证码无效"),
    ("unexpected", 503, "账号服务暂时不可用"),
])
def test_auth_errors_are_actionable_without_upstream_secrets(cloud, monkeypatch, code, status, expected):
    import httpx
    monkeypatch.setattr(httpx, "request", lambda *a, **kw: httpx.Response(status, json={"error_code": code, "msg": "secret-upstream-value"}))
    with pytest.raises(HTTPException) as error:
        module._request("token?grant_type=password", {})
    assert expected in error.value.detail
    assert "secret-upstream-value" not in error.value.detail
