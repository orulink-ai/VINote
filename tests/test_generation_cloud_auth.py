from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from starlette.requests import Request

from app.models.auth import AuthenticatedUser
from app.models.note import NoteRequest
from app.services import generation_auth_service as auth


def request(cookie=False):
    headers = [(b"cookie", f"{auth.settings.auth_cookie_name}=local".encode())] if cookie else []
    return Request({"type": "http", "headers": headers})


def test_local_session_does_not_call_cloud_auth():
    user = AuthenticatedUser("local-user")
    with patch.object(auth, "local_user", return_value=user), patch.object(auth, "_request") as cloud:
        assert auth.get_optional_generation_user(request(), None) == user
        cloud.assert_not_called()


def test_verified_cloud_subject_uses_existing_mapping():
    @contextmanager
    def session():
        yield SimpleNamespace(scalar=lambda query: SimpleNamespace(user_id="linked-user"))
    identity = {"id": "cloud-subject", "email": "test@example.com", "email_confirmed_at": "confirmed"}
    with patch.object(auth, "local_user", side_effect=HTTPException(401)), patch.object(auth, "_request", return_value=identity), patch.object(auth, "session_scope", session):
        user = auth.get_generation_user(request(), HTTPAuthorizationCredentials(scheme="Bearer", credentials="opaque-token"))
        assert user.user_id == "linked-user"


@pytest.mark.parametrize("identity", [{"id": "subject"}, {"id": "subject", "email_confirmed_at": "confirmed", "is_anonymous": True}])
def test_unverified_or_anonymous_cloud_identity_rejected(identity):
    with patch.object(auth, "local_user", side_effect=HTTPException(401)), patch.object(auth, "_request", return_value=identity):
        with pytest.raises(HTTPException) as error:
            auth.get_generation_user(request(), HTTPAuthorizationCredentials(scheme="Bearer", credentials="opaque-token"))
        assert error.value.status_code == 401


def test_provider_outage_is_not_an_authentication_rejection():
    with patch.object(auth, "local_user", side_effect=HTTPException(401)), patch.object(auth, "_request", side_effect=HTTPException(502)):
        with pytest.raises(HTTPException) as error:
            auth.get_generation_user(request(), HTTPAuthorizationCredentials(scheme="Bearer", credentials="opaque-token"))
        assert error.value.status_code == 502


def test_cookie_failure_cannot_switch_identity_using_another_bearer():
    with patch.object(auth, "local_user", side_effect=HTTPException(401)), patch.object(auth, "_request") as cloud:
        with pytest.raises(HTTPException):
            auth.get_generation_user(request(True), HTTPAuthorizationCredentials(scheme="Bearer", credentials="opaque-token"))
        cloud.assert_not_called()


def test_invalid_cookie_is_not_accepted_as_anonymous():
    with patch.object(auth, "local_user", return_value=None), patch.object(auth, "_request") as cloud:
        with pytest.raises(HTTPException) as error:
            auth.get_optional_generation_user(request(True), None)
        assert error.value.status_code == 401
        cloud.assert_not_called()


def test_url_request_can_enter_the_existing_pipeline_without_missing_fields():
    payload = NoteRequest(video_url="https://www.bilibili.com/video/BV1234567890")
    assert payload.diarize is False
    assert payload.speaker_count is None
