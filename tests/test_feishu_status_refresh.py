"""Synthetic encrypted credentials only; no real OAuth or provider requests."""
import json
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from app.services import feishu_service as module
from test_feishu_delivery import service  # noqa: F401


GRANTS = "docx:document drive:drive.metadata:readonly wiki:node:create contact:user:search docx:document.block:convert"


def expire(service):
    with module.session_scope() as db:
        row = db.get(module.FeishuConnectionDB, "a")
        tokens = json.loads(module._cipher().decrypt(row.tokens.encode()))
        tokens.update(expires_at=1, scope=GRANTS)
        row.tokens = module._cipher().encrypt(json.dumps(tokens).encode()).decode()
        return row.tokens, row.preferences


def stored(owner="a"):
    with module.session_scope() as db:
        row = db.get(module.FeishuConnectionDB, owner)
        return None if row is None else (row.tokens, row.preferences, row.expired, row.open_id)


def test_expired_status_refreshes_before_reading_grants(service, monkeypatch):
    expire(service)
    calls = []
    def refresh(body):
        assert body == {"grant_type": "refresh_token", "refresh_token": "refresh"}
        calls.append(True)
        return {"access_token": "new-synthetic", "expires_in": 7200}
    monkeypatch.setattr(service, "exchange", refresh)
    status = service.status("a")
    assert status["connection_state"] == "connected"
    assert status["grant_state"] == "verified"
    assert all(status["capabilities"][key] for key in ("personal", "folder", "wiki", "contact_search"))
    assert status["markdown_conversion_preflight"]["user_grant_available"]
    assert not status["markdown_conversion_preflight"]["app_permission_verified"]
    assert service.status("a") == status
    assert len(calls) == 1
    tokens = json.loads(module._cipher().decrypt(stored()[0].encode()))
    assert tokens["scope"] == GRANTS and tokens["refresh_token"] == "refresh"
    assert "new-synthetic" not in json.dumps(status)


@pytest.mark.parametrize("status_code", [400, 403, 429, 502, 504])
def test_refresh_outage_keeps_credentials_and_is_not_reauthorization(service, monkeypatch, status_code):
    original, preferences = expire(service)
    def fail(body):
        raise module.FeishuError("synthetic private detail", status_code)
    monkeypatch.setattr(service, "exchange", fail)
    result = service.status("a")
    assert result["connection_state"] == "service_unavailable"
    assert result["grant_state"] == "unavailable"
    assert not result["expired"] and not result["connected"]
    assert not any(result["capabilities"].values())
    assert "重新授权" in result["capability_reason"]
    assert "synthetic private detail" not in json.dumps(result)
    assert stored() == (original, preferences, False, "ou_a")


def test_explicit_revocation_requires_reauth_but_preserves_connection(service, monkeypatch):
    original, preferences = expire(service)
    calls = []
    def revoked(body):
        calls.append(True)
        raise module.FeishuError("invalid grant", 401)
    monkeypatch.setattr(service, "exchange", revoked)
    result = service.status("a")
    assert result["connection_state"] == "reauthorization_required"
    assert result["expired"] and not result["connected"]
    assert stored() == (original, preferences, True, "ou_a")
    service.status("a")
    assert len(calls) == 1


@pytest.mark.parametrize("scope", ["", "docx:document"])
def test_explicit_reduced_grant_does_not_reuse_old_permissions(service, monkeypatch, scope):
    expire(service)
    monkeypatch.setattr(service, "exchange", lambda body: {
        "access_token": "new", "expires_in": 7200, "scope": scope})
    result = service.status("a")
    assert not result["capabilities"]["folder"]
    assert not result["capabilities"]["wiki"]
    assert not result["capabilities"]["contact_search"]


@pytest.mark.parametrize("response", [
    {}, {"expires_in": 7200}, {"access_token": "new"},
    {"access_token": "new", "expires_in": True},
    {"access_token": "new", "expires_in": float("nan")},
    {"access_token": "new", "expires_in": 0},
    {"access_token": "new", "expires_in": 7200, "scope": None},
])
def test_malformed_refresh_cannot_rejuvenate_old_token(service, monkeypatch, response):
    original, preferences = expire(service)
    monkeypatch.setattr(service, "exchange", lambda body: response)
    assert service.status("a")["connection_state"] == "service_unavailable"
    assert stored() == (original, preferences, False, "ou_a")


@pytest.mark.parametrize("revoked", [False, True])
def test_disconnect_serializes_with_refresh_success_and_failure(service, monkeypatch, revoked):
    expire(service)
    entered, release, disconnect_entered = threading.Event(), threading.Event(), threading.Event()
    def refresh(body):
        entered.set()
        assert release.wait(3)
        if revoked:
            raise module.FeishuError("revoked", 401)
        return {"access_token": "new", "expires_in": 7200}
    def disconnect():
        disconnect_entered.set()
        return service.disconnect("a")
    monkeypatch.setattr(service, "exchange", refresh)
    with ThreadPoolExecutor(max_workers=2) as pool:
        pending = pool.submit(service.status, "a")
        assert entered.wait(3)
        leaving = pool.submit(disconnect)
        assert disconnect_entered.wait(3)
        assert not leaving.done()
        release.set()
        pending.result(timeout=3)
        assert leaving.result(timeout=3)["connection_state"] == "disconnected"
    assert stored() is None
    assert not service.status("a")["connected"]


def test_other_owner_and_disconnected_status_do_not_refresh(service, monkeypatch):
    original = expire(service)
    monkeypatch.setattr(service, "exchange", lambda body: pytest.fail("No other owner refresh"))
    assert service.status("b")["connection_state"] == "disconnected"
    assert stored()[:2] == original
    service.disconnect("a")
    assert service.status("a")["connection_state"] == "disconnected"


def test_outage_can_recover_without_reauthorization_and_keeps_preferences(service, monkeypatch):
    _, preferences = expire(service)
    attempts = []
    def refresh(body):
        attempts.append(True)
        if len(attempts) == 1:
            raise module.FeishuError("synthetic timeout", 502)
        return {"access_token": "rotated", "refresh_token": "rotated-refresh", "expires_in": 7200}
    monkeypatch.setattr(service, "exchange", refresh)
    assert service.status("a")["connection_state"] == "service_unavailable"
    assert service.status("a")["capabilities"]["contact_search"]
    assert stored()[1] == preferences
    assert json.loads(module._cipher().decrypt(stored()[0].encode()))["refresh_token"] == "rotated-refresh"


def test_concurrent_status_refreshes_once(service, monkeypatch):
    expire(service)
    entered, release, second_entered = threading.Event(), threading.Event(), threading.Event()
    attempts = []
    def refresh(body):
        attempts.append(True)
        entered.set()
        assert release.wait(3)
        return {"access_token": "rotated", "expires_in": 7200}
    def second_status():
        second_entered.set()
        return service.status("a")
    monkeypatch.setattr(service, "exchange", refresh)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(service.status, "a")
        assert entered.wait(3)
        second = pool.submit(second_status)
        assert second_entered.wait(3)
        release.set()
        assert first.result(timeout=3) == second.result(timeout=3)
    assert len(attempts) == 1


def test_late_401_does_not_expire_replaced_credentials(service, monkeypatch):
    expire(service)
    def replaced_elsewhere(owner):
        # Deterministically simulate another process replacing the credential
        # after the snapshot was read but before the old refresh failed.
        service.disconnect(owner)
        service.store_connection(owner, {"access_token": "replacement", "refresh_token": "replacement-refresh",
            "expires_in": 7200}, {"open_id": "ou_replacement", "name": "B", "tenant_key": "company"})
        raise module.FeishuError("old grant revoked", 401)
    monkeypatch.setattr(service, "_user_token", replaced_elsewhere)
    with pytest.raises(module.FeishuError):
        service.user_token("a")
    assert stored()[2:] == (False, "ou_replacement")
