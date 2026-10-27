"""Connection changes never infer, move old jobs, or borrow another Origin's auth."""
from contextlib import contextmanager
from copy import deepcopy
import json

import httpx
import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.config import settings
from app.db import Base
from app.db_models import VILabConnectionDB, VILabConnectionStateDB
from app.services import vilab_cloud_service as cloud
from app.services import vilab_connection_service as module


CATALOG = [{"id": "asr", "modelType": "asr", "runtimeStatus": "available"},
           {"id": "llm", "modelType": "llm", "runtimeStatus": "available"}]


@pytest.fixture
def connections(tmp_path, monkeypatch):
    engine = create_engine("sqlite:///" + (tmp_path / "connections.db").as_posix())
    Base.metadata.create_all(engine)
    @contextmanager
    def scope():
        with Session(engine) as db, db.begin():
            yield db
    monkeypatch.setattr(module, "session_scope", scope)
    monkeypatch.setattr(cloud, "session_scope", scope)
    monkeypatch.setattr(settings, "vilab_server_url", "https://default.example")
    monkeypatch.setattr(settings, "vilab_api_key", "default-only-key")
    monkeypatch.setattr(settings, "cloud_auth_url", "")
    monkeypatch.setattr(settings, "model_profile_encryption_key", "synthetic-key")
    monkeypatch.setattr(settings, "content_cloud_runtime", False)
    monkeypatch.setattr(settings, "workspace_cloud_runtime", False)
    monkeypatch.setattr(module, "_checks", {})
    calls = []
    def request(method, url, **kwargs):
        calls.append((method, url, kwargs))
        assert method == "GET" and url.endswith("/v1/models"), "checks must not invoke inference"
        return httpx.Response(200, json={"data": deepcopy(CATALOG)})
    monkeypatch.setattr(httpx, "request", request)
    yield module.VILabConnectionService(), cloud.VILabCloudService(), calls, scope
    engine.dispose()


def checked(service, **kwargs):
    return service.check("alice", server_url="http://127.0.0.1:9876", api_key="private-key", **kwargs)


def activate(service, result, **kwargs):
    return service.save("alice", result["check_id"], "asr", "llm", **kwargs)


def test_check_is_only_get_catalog_and_does_not_persist_or_change_config(connections):
    service, cloud_service, calls, scope = connections
    before = cloud_service.status("alice")
    result = checked(service)
    assert result["models"] == CATALOG and "private-key" not in json.dumps(result)
    assert cloud_service.status("alice") == before
    with scope() as db:
        assert db.scalar(select(VILabConnectionDB)) is None
        assert db.get(VILabConnectionStateDB, "alice") is None
    assert calls[0][2]["headers"] == {"Authorization": "Bearer private-key"}
    assert calls[0][2]["follow_redirects"] is False and calls[0][2]["trust_env"] is False


def test_new_origin_never_borrows_default_or_previous_credential(connections):
    service, cloud_service, calls, scope = connections
    first = activate(service, checked(service))
    result = service.check("alice", server_url="https://second.example")
    assert calls[-1][2]["headers"] == {}
    second = activate(service, result)
    cloud_service.models("alice")
    assert calls[-1][1] == "https://second.example/v1/models" and calls[-1][2]["headers"] == {}
    assert first["connection_id"] != second["connection_id"]
    with scope() as db:
        stored = db.get(VILabConnectionDB, first["connection_id"])
        assert stored.credential and "private-key" not in stored.credential


def test_frozen_task_keeps_original_origin_and_credential_after_switch(connections):
    service, cloud_service, calls, _ = connections
    activate(service, checked(service))
    snapshot = cloud_service.connection_snapshot("alice")
    activate(service, service.check("alice", server_url="https://new.example", api_key="new-key"))
    with cloud_service.task_snapshot("alice", snapshot=snapshot):
        cloud_service.models("alice")
    assert calls[-1][1] == "http://127.0.0.1:9876/v1/models"
    assert calls[-1][2]["headers"] == {"Authorization": "Bearer private-key"}
    assert cloud_service.status("alice")["server_url"] == "https://new.example"


def test_saved_connection_models_survive_switching_and_no_models_are_automatically_selected(connections):
    service, cloud_service, _, _ = connections
    first = activate(service, checked(service))
    activate(service, service.check("alice", server_url="https://second.example"))
    check = service.check("alice", connection_id=first["connection_id"])
    assert (check["asr_model"], check["llm_model"]) == ("asr", "llm")
    service.save("alice", check["check_id"], "", "")
    assert cloud_service.status("alice")["asr_model"] == ""


def test_check_is_owner_bound_one_time_and_stale_switch_fails_closed(connections):
    service, _, _, _ = connections
    result = checked(service)
    with pytest.raises(HTTPException):
        service.save("bob", result["check_id"], "asr", "llm")
    other = service.check("alice", server_url="https://other.example")
    activate(service, other)
    with pytest.raises(HTTPException):
        activate(service, result)
    with pytest.raises(HTTPException):
        activate(service, other)


def test_owner_and_origin_of_frozen_reference_are_both_required(connections):
    service, cloud_service, calls, _ = connections
    config = activate(service, checked(service))
    count = len(calls)
    for owner, origin in [("bob", config["server_url"]), ("alice", "https://different.example")]:
        with pytest.raises(HTTPException):
            cloud_service.authorization(owner, origin, config["connection_id"])
    with pytest.raises(HTTPException):
        cloud_service.authorization("alice", "https://different.example", None)
    assert len(calls) == count


def test_failed_check_preserves_selection_and_never_follows_redirect(connections, monkeypatch):
    service, cloud_service, _, _ = connections
    before = cloud_service.status("alice")
    monkeypatch.setattr(httpx, "request", lambda *a, **kw: httpx.Response(302, headers={"location": "https://other.example"}))
    with pytest.raises(HTTPException):
        checked(service)
    assert cloud_service.status("alice") == before


@pytest.mark.parametrize("url", ["http://8.8.8.8", "http://169.254.169.254", "http://0.0.0.0",
    "https://user:secret@example.com", "https://example.com/path", "https://example.com?key=x",
    "https://example.com#fragment", "https://example.com\n", "file:///tmp/x", "http://[ff02::1]",
    "https://example.com\\evil", "https://@example.com"])
def test_unsafe_origins_fail_before_network(connections, url):
    service, _, calls, _ = connections
    with pytest.raises(HTTPException):
        service.check("alice", server_url=url)
    assert calls == []


@pytest.mark.parametrize("url", ["http://127.0.0.1:9876", "http://192.168.1.2:9876",
    "http://10.2.3.4", "http://172.20.0.2", "http://[::1]:9876", "https://public.example"])
def test_explicit_loopback_lan_and_https_origins(connections, url):
    service, _, calls, _ = connections
    service.check("alice", server_url=url)
    assert calls[0][1] == url + "/v1/models"


def test_external_connection_never_uses_shared_account_token(connections, monkeypatch):
    from app.services.cloud_account_service import CloudAccountService
    service, cloud_service, calls, _ = connections
    monkeypatch.setattr(settings, "cloud_auth_url", "https://account.example")
    monkeypatch.setattr(CloudAccountService, "access_token", lambda *a: pytest.fail("default account token leaked"))
    activate(service, checked(service))
    cloud_service.models("alice")
    assert calls[-1][2]["headers"] == {"Authorization": "Bearer private-key"}


def test_asr_resolves_frozen_connection_credentials_without_inference(connections):
    from app.services.stt_profile_service import STTProfileService
    from app.transcribers.vilab_transcriber import VILabTranscriber
    service, cloud_service, _, _ = connections
    config = activate(service, checked(service))
    resolved = STTProfileService().resolve_config(user_id="alice", stt_profile_id=None)
    assert resolved.cloud_connection_id == config["connection_id"]
    adapter = VILabTranscriber(resolved.base_url, "", resolved.model_name,
                              cloud_user_id="alice", cloud_connection_id=resolved.cloud_connection_id)
    activate(service, service.check("alice", server_url="https://changed.example", api_key="changed-key"))
    assert adapter._recognition_bearer() == "private-key"


def test_durable_source_keeps_connection_id_and_rejects_owner_or_origin_substitution(connections):
    from app.services.task_model_source import capture_source, validate_source
    service, _, _, _ = connections
    original = activate(service, checked(service))
    source = capture_source("alice", {"needs_stt": True})
    assert source["connection_id"] == original["connection_id"] and "credential" not in source
    activate(service, service.check("alice", server_url="https://changed.example"))
    assert validate_source(source, "alice") == source
    with pytest.raises(HTTPException):
        validate_source({**source, "server_url": "https://changed.example"}, "alice")
    with pytest.raises(HTTPException):
        validate_source({**source, "owner": "bob"}, "bob")


def test_catalog_switch_race_cannot_save_old_choices_into_new_connection(connections, monkeypatch):
    service, cloud_service, _, _ = connections
    first = activate(service, checked(service))
    check = service.check("alice", server_url="https://changed.example")
    def race(owner):
        activate(service, check)
        return CATALOG
    monkeypatch.setattr(cloud_service, "models", race)
    with pytest.raises(HTTPException):
        cloud_service.select("alice", "cloud", "asr", "llm")
    assert cloud_service.status("alice")["connection_id"] != first["connection_id"]


def test_key_replacement_creates_new_binding_and_old_snapshot_stays_readable(connections):
    service, cloud_service, _, _ = connections
    old = activate(service, checked(service))
    updated = service.check("alice", connection_id=old["connection_id"], api_key="rotated-key")
    current = activate(service, updated)
    assert current["connection_id"] != old["connection_id"]
    assert cloud_service.authorization("alice", old["server_url"], old["connection_id"])["Authorization"] == "Bearer private-key"
    assert cloud_service.authorization("alice", current["server_url"], current["connection_id"])["Authorization"] == "Bearer rotated-key"


def test_expired_proof_and_foreign_connection_fail_without_activation(connections):
    service, cloud_service, calls, _ = connections
    result = checked(service)
    module._checks[result["check_id"]]["until"] = 0
    with pytest.raises(HTTPException):
        activate(service, result)
    original = activate(service, checked(service))
    count = len(calls)
    with pytest.raises(HTTPException):
        service.check("bob", connection_id=original["connection_id"])
    assert len(calls) == count
    assert cloud_service.status("alice")["connection_id"] == original["connection_id"]


def test_saved_url_change_cannot_borrow_key_and_wrong_model_type_cannot_save(connections):
    service, cloud_service, calls, _ = connections
    original = activate(service, checked(service))
    count = len(calls)
    with pytest.raises(HTTPException):
        service.check("alice", connection_id=original["connection_id"], server_url="https://new.example")
    assert len(calls) == count
    result = service.check("alice", server_url="https://new.example")
    with pytest.raises(HTTPException):
        service.save("alice", result["check_id"], "llm", "asr")
    assert cloud_service.status("alice")["connection_id"] == original["connection_id"]


def test_authenticated_api_checks_owner_and_requires_explicit_save(connections):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from types import SimpleNamespace
    from app.routers import vilab
    from app.services.auth_service import get_current_user
    _, cloud_service, calls, _ = connections
    owner = ["alice"]
    app = FastAPI(); app.include_router(vilab.router, prefix="/api")
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(user_id=owner[0])
    client = TestClient(app)
    response = client.post("/api/vilab/connections/check", json={"server_url": "http://127.0.0.1:9876", "api_key": "explicit-key"})
    assert response.status_code == 200 and "explicit-key" not in response.text
    assert cloud_service.status("alice")["server_url"] == "https://default.example"
    body = {"check_id": response.json()["check_id"], "asr_model": "asr", "llm_model": "llm"}
    owner[0] = "bob"
    assert client.put("/api/vilab/connection", json=body).status_code == 409
    owner[0] = "alice"
    saved = client.put("/api/vilab/connection", json=body)
    assert saved.status_code == 200 and saved.json()["server_url"] == "http://127.0.0.1:9876"
    assert "explicit-key" not in saved.text
    assert all(call[0] == "GET" for call in calls)


def test_desktop_connection_routes_are_not_available_in_cloud_runtime(connections, monkeypatch):
    service, _, calls, _ = connections
    monkeypatch.setattr(settings, "content_cloud_runtime", True)
    for action in (lambda: service.list("alice"), lambda: checked(service), lambda: service.save("alice", "no-proof", "", "")):
        with pytest.raises(HTTPException) as error:
            action()
        assert error.value.status_code == 404
    assert not calls


def test_legacy_http_adapter_keeps_frozen_connection_outside_task_context(connections, monkeypatch, tmp_path):
    from app.transcribers.vilab_transcriber import VILabTranscriber
    service, _, _, _ = connections
    original = activate(service, checked(service))
    adapter = VILabTranscriber(original["server_url"], "", "asr", cloud_user_id="alice",
                              cloud_connection_id=original["connection_id"])
    activate(service, service.check("alice", server_url="https://changed.example"))
    monkeypatch.setattr("subprocess.check_output", lambda *a, **kw: "1")
    observed = []
    def request(self, owner, method, path, **kwargs):
        observed.append(self.status(owner))
        return {"text": "synthetic transcript"}
    monkeypatch.setattr(cloud.VILabCloudService, "request", request)
    path = tmp_path / "synthetic.wav"; path.write_bytes(b"synthetic")
    adapter._transcribe_http(str(path))
    assert observed[0]["connection_id"] == original["connection_id"]
    assert observed[0]["server_url"] == original["server_url"]


def shared_account(connections, monkeypatch):
    from app.db_models import CloudAccountDB
    from app.services.cloud_account_service import CloudAccountService
    _, _, _, scope = connections
    monkeypatch.setattr(settings, "cloud_auth_url", "https://shared-account.example")
    with scope() as db:
        db.add(CloudAccountDB(user_id="alice", issuer=settings.cloud_auth_url, subject="subject-alice",
                             email="alice@example.invalid", session_encrypted="synthetic-existing-session"))
    tokens = ["fresh-shared-session"]
    monkeypatch.setattr(CloudAccountService, "access_token", lambda self, owner: tokens[0] if owner == "alice" else pytest.fail("wrong account"))
    return tokens


@pytest.mark.parametrize("origin", ["http://192.168.1.143:9876", "https://api.orulink.ai"])
def test_explicit_account_check_needs_only_url_and_never_persists_token(connections, monkeypatch, origin):
    service, cloud_service, calls, scope = connections
    tokens = shared_account(connections, monkeypatch)
    before = cloud_service.status("alice")
    result = service.check("alice", server_url=origin, auth_mode="account", account_consent=True,
                           authorized_origin=origin)
    assert calls[-1][2]["headers"] == {"Authorization": "Bearer " + tokens[0]}
    assert cloud_service.status("alice") == before
    assert tokens[0] not in json.dumps(result) and tokens[0] not in repr(module._checks)
    config = activate(service, result)
    assert config["connection_auth_mode"] == "account"
    with scope() as db:
        assert db.get(VILabConnectionDB, config["connection_id"]).credential == ""
    tokens[0] = "rotated-shared-session"
    cloud_service.models("alice")
    assert calls[-1][1] == origin + "/v1/models"
    assert calls[-1][2]["headers"] == {"Authorization": "Bearer rotated-shared-session"}


@pytest.mark.parametrize("consent,authorized", [(False, "https://custom.example"),
    (True, None), (True, "https://other.example")])
def test_account_mode_cannot_send_token_without_exact_origin_consent(connections, monkeypatch, consent, authorized):
    service, _, calls, _ = connections
    shared_account(connections, monkeypatch)
    with pytest.raises(HTTPException):
        service.check("alice", server_url="https://custom.example", auth_mode="account",
                       account_consent=consent, authorized_origin=authorized)
    assert not calls


def test_account_snapshot_mode_and_identity_are_frozen_without_token(connections, monkeypatch):
    from app.db_models import CloudAccountDB
    from app.services.task_model_source import capture_source, validate_source
    service, cloud_service, calls, scope = connections
    shared_account(connections, monkeypatch)
    origin = "http://192.168.1.143:9876"
    config = activate(service, service.check("alice", server_url=origin, auth_mode="account",
                       account_consent=True, authorized_origin=origin))
    source = capture_source("alice", {"needs_stt": True})
    assert source["connection_auth_mode"] == "account"
    with pytest.raises(HTTPException):
        validate_source({**source, "connection_auth_mode": "api_key"}, "alice")
    activate(service, service.check("alice", server_url="https://other.example", api_key="other-key"))
    with cloud_service.task_snapshot("alice", snapshot=source):
        cloud_service.models("alice")
    assert calls[-1][1] == origin + "/v1/models"
    count = len(calls)
    with scope() as db:
        db.get(CloudAccountDB, "alice").subject = "different-subject"
    with cloud_service.task_snapshot("alice", snapshot=source), pytest.raises(HTTPException):
        cloud_service.models("alice")
    assert len(calls) == count
