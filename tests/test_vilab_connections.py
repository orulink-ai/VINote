"""VILab is a fixed public deployment; legacy connection switching is retired."""
from contextlib import contextmanager

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from types import SimpleNamespace

from app.config import settings
from app.db import Base
from app.db_models import VILabConnectionDB, VILabConnectionStateDB, VILabPreferenceDB
from app.services import task_model_source as sources
from app.services import vilab_cloud_service as cloud


FIXED_URL = "https://api-hk.orulink.ai"
CATALOG = [
    {"id": "meeting-asr", "modelType": "asr", "runtimeStatus": "available"},
    {"id": "meeting-llm", "modelType": "llm", "runtimeStatus": "available"},
]


@pytest.fixture
def fixed_service(tmp_path, monkeypatch):
    engine = create_engine("sqlite:///" + (tmp_path / "fixed.db").as_posix())
    Base.metadata.create_all(engine)

    @contextmanager
    def scope():
        with Session(engine) as db, db.begin():
            yield db

    monkeypatch.setattr(cloud, "session_scope", scope)
    monkeypatch.setattr(settings, "vilab_server_url", FIXED_URL)
    monkeypatch.setattr(settings, "vilab_api_key", "synthetic-fixed-key")
    monkeypatch.setattr(settings, "cloud_auth_url", "")
    monkeypatch.setattr(settings, "content_cloud_runtime", False)
    monkeypatch.setattr(settings, "workspace_cloud_runtime", False)
    with scope() as db:
        db.add(VILabPreferenceDB(user_id="alice", mode="cloud", asr_model="meeting-asr",
                                 llm_model="meeting-llm"))
    yield cloud.VILabCloudService(), scope
    engine.dispose()


def test_legacy_connection_routes_are_not_mounted(fixed_service):
    from app.routers import vilab
    from app.services.auth_service import get_current_user

    app = FastAPI()
    app.include_router(vilab.router, prefix="/api")
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(user_id="alice")
    with TestClient(app) as client:
        assert client.get("/api/vilab/connections").status_code == 404
        assert client.post("/api/vilab/connections/check", json={}).status_code == 404
        assert client.put("/api/vilab/connection", json={}).status_code == 404


def test_config_is_read_only_and_exposes_the_fixed_public_origin(fixed_service, monkeypatch):
    from app.routers import vilab
    from app.services.auth_service import get_current_user

    service, _ = fixed_service
    monkeypatch.setattr(cloud.VILabCloudService, "models", lambda self, owner: CATALOG)
    app = FastAPI()
    app.include_router(vilab.router, prefix="/api")
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(user_id="alice")
    with TestClient(app) as client:
        before = client.get("/api/vilab/config").json()
        assert before["server_url"] == FIXED_URL
        assert "connection_id" not in before
        saved = client.put("/api/vilab/config", json={
            "mode": "cloud",
            "asr_model": "meeting-asr",
            "llm_model": "meeting-llm",
            "connection_id": "legacy-external",
            "connection_revision": "legacy-revision",
        })
        assert saved.status_code == 200, saved.text
        assert saved.json()["server_url"] == FIXED_URL
        assert "connection_id" not in saved.json()


def test_authorization_ignores_historical_connection_identity(fixed_service):
    service, _ = fixed_service
    headers = service.authorization("alice", FIXED_URL, "historical-connection", "account")
    assert headers == {"Authorization": "Bearer synthetic-fixed-key"}
    with pytest.raises(HTTPException) as error:
        service.authorization("alice", "https://external.invalid", "historical-connection")
    assert error.value.status_code == 409


def test_external_origin_is_rejected_before_a_shared_account_token_is_read(fixed_service, monkeypatch):
    from app.services.cloud_account_service import CloudAccountService

    service, _ = fixed_service
    monkeypatch.setattr(settings, "cloud_auth_url", "https://account.invalid")
    monkeypatch.setattr(CloudAccountService, "access_token", lambda *args: pytest.fail("token read"))
    with pytest.raises(HTTPException) as error:
        service.authorization("alice", "https://external.invalid")
    assert error.value.status_code == 409


def test_status_ignores_a_persisted_external_connection(fixed_service):
    service, scope = fixed_service
    with scope() as db:
        db.add(VILabConnectionDB(id="external", user_id="alice", server_url="https://external.invalid",
                                 credential="", asr_model="external-asr", llm_model="external-llm"))
        db.add(VILabConnectionStateDB(user_id="alice", connection_id="external"))
    status = service.status("alice")
    assert status["server_url"] == FIXED_URL
    assert "connection_id" not in status


def test_historical_connection_fields_are_readable_but_ignored(fixed_service, monkeypatch):
    service, _ = fixed_service
    monkeypatch.setattr(cloud.VILabCloudService, "models", lambda self, owner: CATALOG)
    source = sources.capture_source("alice", {"needs_stt": True})
    assert source["server_url"] == FIXED_URL
    assert "connection_id" not in source
    historical = {**source, "connection_id": "legacy-external", "connection_auth_mode": "account"}
    assert sources.validate_source(historical, "alice") == historical
    assert service.authorization("alice", historical["server_url"], historical["connection_id"],
                                 historical["connection_auth_mode"]) == {
        "Authorization": "Bearer synthetic-fixed-key"
    }


@pytest.mark.parametrize("origin", ["https://external.invalid", "http://192.168.1.143:9876", ""])
def test_durable_source_rejects_every_non_fixed_origin(fixed_service, monkeypatch, origin):
    service, _ = fixed_service
    monkeypatch.setattr(cloud.VILabCloudService, "models", lambda self, owner: CATALOG)
    source = sources.capture_source("alice", {"needs_stt": True})
    with pytest.raises(HTTPException) as error:
        sources.validate_source({**source, "server_url": origin}, "alice")
    assert error.value.status_code == 409


def test_models_always_target_the_fixed_public_origin(fixed_service, monkeypatch):
    import httpx

    service, _ = fixed_service
    calls = []

    def request(method, url, **kwargs):
        calls.append((method, url, kwargs))
        return httpx.Response(200, json={"data": CATALOG})

    monkeypatch.setattr(cloud.httpx, "request", request)
    assert service.models("alice")[0]["id"] == "meeting-asr"
    assert calls[0][1] == FIXED_URL + "/v1/models"
    assert calls[0][2]["headers"] == {"Authorization": "Bearer synthetic-fixed-key"}
    assert calls[0][2]["follow_redirects"] is False
    assert calls[0][2]["trust_env"] is False
