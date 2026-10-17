import httpx
import pytest
from fastapi import HTTPException

from app.services import cloud_account_service as accounts


@pytest.mark.parametrize("code", ["bad_jwt", "jwt_expired", "session_not_found"])
def test_expired_bearer_preserves_401_for_mobile_refresh(monkeypatch, code):
    monkeypatch.setattr(accounts.settings, "cloud_auth_url", "https://auth.example.test")
    monkeypatch.setattr(accounts.settings, "cloud_auth_public_key", "public-test")
    monkeypatch.setattr(accounts.httpx, "request", lambda *args, **kwargs: httpx.Response(401, json={"error_code": code}))
    with pytest.raises(HTTPException) as error:
        accounts._request("user", token="expired-test")
    assert error.value.status_code == 401


def test_provider_outage_is_not_an_auth_refresh_loop(monkeypatch):
    monkeypatch.setattr(accounts.settings, "cloud_auth_url", "https://auth.example.test")
    monkeypatch.setattr(accounts.settings, "cloud_auth_public_key", "public-test")
    monkeypatch.setattr(accounts.httpx, "request", lambda *args, **kwargs: httpx.Response(503, json={}))
    with pytest.raises(HTTPException) as error:
        accounts._request("user", token="test")
    assert error.value.status_code == 502
