from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.models.auth import AuthenticatedUser
from app.routers import vilab
from app.services.auth_service import get_current_user


def make_client():
    app = FastAPI()
    app.include_router(vilab.router, prefix="/api")
    app.dependency_overrides[get_current_user] = lambda: AuthenticatedUser(
        user_id="user-1", email="person@example.com"
    )
    return TestClient(app)


def test_realtime_connection_uses_personal_token(monkeypatch):
    monkeypatch.setattr(vilab, "settings", SimpleNamespace(vilab_server_url="http://192.168.1.143:9876"))
    monkeypatch.setattr(vilab.accounts, "access_token", lambda user_id: f"token for {user_id}")

    response = make_client().get("/api/vilab/realtime-connection")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json() == {
        "url": "ws://192.168.1.143:9876/v1/asr/transcriptions?token=token+for+user-1",
        "language": "zh-CN",
    }


def test_realtime_connection_rejects_missing_service(monkeypatch):
    monkeypatch.setattr(vilab, "settings", SimpleNamespace(vilab_server_url=""))
    response = make_client().get("/api/vilab/realtime-connection")
    assert response.status_code == 503
