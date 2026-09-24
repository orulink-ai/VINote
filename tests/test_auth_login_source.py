from contextlib import contextmanager

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.db import Base
from app.db_models import AuthLoginEventDB, UserDB
from app.models.auth import UserResponse
from app.routers import auth
from app.services import auth_audit_service


@pytest.fixture
def setup(monkeypatch, tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'audit.db'}")
    Base.metadata.create_all(engine)
    @contextmanager
    def sessions():
        with Session(engine) as db, db.begin():
            yield db
    with sessions() as db:
        db.add(UserDB(id="test-user", email="test@example.com", password_hash="unused"))
    monkeypatch.setattr(auth_audit_service, "session_scope", sessions)
    monkeypatch.setattr(auth.settings, "cloud_auth_url", "https://example.supabase.co")
    monkeypatch.setattr(auth, "create_access_token", lambda user: "test-token")
    app = FastAPI()
    app.include_router(auth.router)
    yield TestClient(app), sessions
    engine.dispose()


@pytest.mark.parametrize("client,platform,expected", [("mobile", "android", "mobile"), ("mobile", "ios", "mobile"), ("desktop", "windows", "desktop"), ("forged", "invalid", "unknown")])
@pytest.mark.parametrize("path,payload,method", [
    ("sign-in", {"password": "password123"}, "password_login"),
    ("register/verify", {"code": "123456"}, "confirm_registration"),
    ("verify", {"code": "123456"}, "login"),
])
def test_success_records_same_user_and_source(setup, monkeypatch, client, platform, expected, path, payload, method):
    http, sessions = setup
    monkeypatch.setattr(auth.CloudAccountService, method, lambda *args: UserResponse(id="test-user", email="test@example.com"))
    response = http.post('/auth/' + path, json={"email": "test@example.com", **payload}, headers={"X-VINote-Client": client, "X-VINote-Platform": platform})
    assert response.status_code == 200
    assert response.json()["id"] == "test-user"
    with sessions() as db:
        rows = db.scalars(select(AuthLoginEventDB)).all()
        assert len(rows) == 1
        assert rows[0].client == expected
        assert rows[0].platform == ("unknown" if platform == "invalid" else platform)


def test_failed_login_is_not_recorded_as_success(setup, monkeypatch):
    http, sessions = setup
    def reject(*args):
        raise HTTPException(401, "invalid credentials")
    monkeypatch.setattr(auth.CloudAccountService, "password_login", reject)
    assert http.post('/auth/sign-in', json={"email": "test@example.com", "password": "incorrect"}).status_code == 401
    with sessions() as db:
        assert db.scalars(select(AuthLoginEventDB)).all() == []


def test_desktop_and_mobile_stay_authenticated_when_other_client_logs_out(setup, monkeypatch):
    from app.services.auth_service import create_access_token
    http, _ = setup
    user = UserResponse(id="test-user", email="test@example.com")
    monkeypatch.setattr(auth, "create_access_token", create_access_token)
    monkeypatch.setattr(auth, "get_user_by_id", lambda user_id: user)
    monkeypatch.setattr(auth.CloudAccountService, "password_login", lambda *args: user)
    def forbid_disconnect(*args):
        pytest.fail("ordinary sign-out must not disconnect the shared cloud account")
    monkeypatch.setattr(auth.CloudAccountService, "disconnect", forbid_disconnect)
    desktop = TestClient(http.app)
    mobile = TestClient(http.app)
    credentials = {"email": user.email, "password": "password123"}
    assert desktop.post('/auth/sign-in', json=credentials, headers={"X-VINote-Client": "desktop"}).status_code == 200
    result = mobile.post('/auth/sign-in', json=credentials, headers={"X-VINote-Client": "mobile"})
    mobile.cookies.clear()
    bearer = {"Authorization": 'Bearer ' + result.json()['access_token']}
    assert desktop.get('/auth/me').status_code == 200
    assert mobile.get('/auth/me', headers=bearer).status_code == 200
    assert mobile.post('/auth/sign-out', headers=bearer).status_code == 204
    assert desktop.get('/auth/me').status_code == 200
    # 再次登录手机后，桌面退出也不能使手机会话失效。
    result = mobile.post('/auth/sign-in', json=credentials)
    mobile.cookies.clear()
    bearer = {"Authorization": 'Bearer ' + result.json()['access_token']}
    assert desktop.post('/auth/sign-out').status_code == 204
    assert desktop.get('/auth/me').status_code == 401
    assert mobile.get('/auth/me', headers=bearer).status_code == 200
