"""Offline public boundary + actual pipeline; no device DB or provider calls."""
import asyncio
import io
import json
import tempfile
import uuid
import wave
from pathlib import Path
from contextvars import copy_context
from types import SimpleNamespace

import httpx
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select, func
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import settings
from app import db
from app.services import cloud_content_identity as identity
from app.services import cloud_content_worker as worker
from app.services.vilab_cloud_service import VILabCloudService


@pytest.fixture
def runtime(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "workspace_cloud_runtime", True)
    monkeypatch.setattr(settings, "content_cloud_runtime", True)
    monkeypatch.setattr(settings, "cloud_auth_url", "https://identity.example")
    monkeypatch.setattr(settings, "vilab_server_url", "https://model.example")
    temporary = tempfile.TemporaryDirectory(prefix="vinote-content-")
    monkeypatch.setattr(settings, "output_dir", Path(temporary.name) / "o")
    monkeypatch.setattr(settings, "data_dir", Path(temporary.name) / "d")
    monkeypatch.setattr(settings, "langfuse_enabled", False)
    settings.output_dir.mkdir(); settings.data_dir.mkdir()
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    event.listen(engine, "connect", lambda connection, _: connection.execute("PRAGMA foreign_keys=ON"))
    from app import create_app
    app = create_app()  # imports/registers the new model before init_db/startup
    db.Base.metadata.create_all(engine)
    monkeypatch.setattr(db, "SessionLocal", sessionmaker(engine, expire_on_commit=False))
    monkeypatch.setattr(db, "engine", engine)
    subjects = {"alice-token": str(uuid.uuid4()), "bob-token": str(uuid.uuid4())}
    auth_calls, provider_calls = [], []

    def verify(path, token=None):
        auth_calls.append(token)
        if token == "outage":
            raise HTTPException(502, "auth unavailable")
        if token not in subjects:
            raise HTTPException(401, "expired")
        return {"id": subjects[token], "email": "same@example.com", "email_confirmed_at": "yes"}
    monkeypatch.setattr(identity, "_request", verify)

    def provider(self, owner, method, path, **kwargs):
        token = identity.content_bearer(owner)
        provider_calls.append((owner, token, method, path))
        if path == "/v1/default-models":
            return {"asr_model": "asr-fixed", "llm_model": "llm-fixed"}
        if path == "/v1/models":
            return {"data": [{"id": "asr-fixed", "modelType": "asr", "runtimeStatus": "available",
                              "capabilities": {"recordedAudio": {"protocol": 1, "supported": True,
                                  "strategy": "adaptive_pause", "policySource": "service_budget",
                                  "maxSessionAudioBytes": 2097152}}},
                             {"id": "llm-fixed", "modelType": "llm", "runtimeStatus": "available"}]}
        assert path == "/openai/v1/chat/completions"
        assert kwargs["json"]["model"] == "llm-fixed"
        return {"choices": [{"message": {"content": "# Offline result\n\nVerified source body."}}]}
    real_request = VILabCloudService.request
    monkeypatch.setattr(VILabCloudService, "request", provider)
    case = SimpleNamespace(client=TestClient(app), app=app, engine=engine, subjects=subjects,
                           auth_calls=auth_calls, provider_calls=provider_calls,
                           real_request=real_request, root=settings.output_dir)
    yield case
    case.client.close(); engine.dispose(); temporary.cleanup()


def headers(token="alice-token", operation=None):
    return {"Authorization": "Bearer " + token, "X-VINote-Client": "mobile",
            **({"X-VINote-Operation-Id": operation} if operation else {})}


def upload(case, *, token="alice-token", operation="one-operation", source="transcript", content=b"source text", **options):
    return case.client.post("/api/generate_from_upload", headers=headers(token, operation),
        data={"source_type": source, "title": "Offline source", **options},
        files={"file": ("source.txt" if source == "transcript" else "source.wav", content)})


def test_caps_verified_read_only_no_model_or_schema_mutation(runtime):
    assert runtime.client.get("/api/content-service/capabilities").status_code == 401
    result = runtime.client.get("/api/content-service/capabilities", headers=headers())
    assert result.status_code == 200
    assert {k: result.json()[k] for k in ("content_service_protocol", "generation", "sync", "video_url")} == {
        "content_service_protocol": 1, "generation": True, "sync": False, "video_url": True}
    assert result.json()["video_url_platforms"] == ["bilibili"]
    with db.session_scope() as session:
        assert session.scalar(select(func.count()).select_from(identity.ContentIdentityDB)) == 0
    assert runtime.provider_calls == []


@pytest.mark.parametrize("path", ["/api/files", "/api/notes", "/api/workspace/status",
    "/api/workspace/notes", "/api/auth/sign-in", "/api/generate_from_file", "/api/generate_sync",
    "/api/generate_from_upload_sync", "/api/task/anything/retry"])
def test_allowlist_excludes_device_sync_auth_and_unsafe_compat_routes(runtime, path):
    assert runtime.client.get(path, headers=headers()).status_code in {404, 405}
    assert runtime.client.post(path, headers=headers(), json={}).status_code in {404, 405}
    assert runtime.provider_calls == []


def test_real_transcript_post_pipeline_receipt_result_owner_and_no_user_fk(runtime):
    result = upload(runtime)
    assert result.status_code == 200, result.text
    receipt = result.json(); assert receipt["state"] == "accepted"
    task = receipt["task_id"]
    read = runtime.client.get("/api/task/" + task, headers=headers())
    assert read.status_code == 200, read.text
    assert read.json()["status"] == "success", read.text
    assert read.json()["result"]["markdown"].startswith("# Offline result")
    assert read.headers["cache-control"] == "private, no-store"
    assert runtime.client.get("/api/task/" + task, headers=headers("bob-token")).status_code == 404
    assert runtime.client.get("/api/source-requests/one-operation", headers=headers("bob-token")).status_code == 404
    from app.db_models import UserDB, CloudAccountDB
    with db.session_scope() as session:
        assert session.scalar(select(func.count()).select_from(UserDB)) == 0
        assert session.scalar(select(func.count()).select_from(CloudAccountDB)) == 0
    folder = worker.artifacts().find_task_dir(task)
    assert (folder / "generation_client").read_text() == "mobile"
    for path in runtime.root.rglob("*"):
        if path.is_file():
            assert b"alice-token" not in path.read_bytes()
            assert b"refresh_token" not in path.read_bytes()
    assert runtime.provider_calls
    with pytest.raises(HTTPException):
        identity.content_bearer(runtime.provider_calls[0][0])


def test_operation_repeat_no_provider_dispatch_and_payload_conflict(runtime):
    first = upload(runtime).json()
    count = len(runtime.provider_calls)
    second = upload(runtime)
    assert second.status_code == 200
    assert second.json()["task_id"] == first["task_id"]
    assert len(runtime.provider_calls) == count
    assert upload(runtime, content=b"different body").status_code == 409
    assert len(runtime.provider_calls) == count


def test_reserved_crash_is_query_only_and_never_schedules(runtime, monkeypatch):
    monkeypatch.setattr(worker, "prepare_models", lambda *args: (_ for _ in ()).throw(HTTPException(503, "not ready")))
    assert upload(runtime).status_code == 503
    result = upload(runtime)
    assert result.status_code == 200 and result.json()["state"] == "reserved"
    assert not list(runtime.root.iterdir())
    assert runtime.provider_calls == []


@pytest.mark.parametrize("options", [{"api_key": "secret"}, {"base_url": "http://127.0.0.1"},
    {"model_profile_id": "local-profile"}, {"stt_profile_id": "local-stt"}, {"file_path": "/etc/passwd"},
    {"local_file_id": "device-id"}])
def test_client_credentials_and_paths_rejected_before_provider(runtime, options):
    assert upload(runtime, **options).status_code == 422
    assert runtime.provider_calls == []


def test_invalid_and_missing_bearer_do_not_submit_cookie_not_a_fallback(runtime):
    assert runtime.client.post("/api/generate", json={}).status_code == 401
    assert runtime.client.post("/api/generate", headers=headers("bad"), json={}).status_code == 401
    assert runtime.client.get("/api/content-service/capabilities", headers=headers("outage")).status_code == 502
    assert runtime.provider_calls == []


@pytest.mark.parametrize("url", ["http://127.0.0.1/private", "file:///etc/passwd",
    "https://user:pass@example.com", "https://bilibili.com/video/BV123", "https://example.com/movie.mp4"])
def test_urls_reject_private_targets_or_video_egress_before_model(runtime, monkeypatch, url):
    from app.routers import cloud_content
    monkeypatch.setattr(cloud_content, "_public_target", lambda u: (_ for _ in ()).throw(ValueError("private")))
    result = runtime.client.post("/api/generate", headers=headers(operation="url-op"), json={"video_url": url})
    assert result.status_code in {422, 503}
    assert runtime.provider_calls == []


def test_real_web_source_post_uses_current_pipeline_and_owner_marker(runtime, monkeypatch):
    from app.routers import cloud_content
    from app.services import source_note_job
    monkeypatch.setattr(cloud_content, "_public_target", lambda u: (u, u))
    monkeypatch.setattr(source_note_job, "webpage_text", lambda u: ("Offline webpage", "Original webpage body"))
    result = runtime.client.post("/api/generate", headers=headers(operation="web-op"),
                                 json={"video_url": "https://example.com/article"})
    assert result.status_code == 200, result.text
    task = result.json()["task_id"]
    read = runtime.client.get("/api/task/" + task, headers=headers())
    assert read.json()["status"] == "success", read.text
    assert runtime.client.get("/api/task/" + task, headers=headers("bob-token")).status_code == 404


def test_missing_owner_and_symlink_owner_are_denied(runtime):
    task = str(uuid.uuid4()); storage = worker.artifacts(); folder = storage.create_task_dir(task)
    storage.update_status(folder, "success", "legacy")
    assert runtime.client.get("/api/task/" + task, headers=headers()).status_code == 404
    (folder / "recording_owner").write_text("wrong-owner")
    assert runtime.client.get("/api/task/" + task, headers=headers()).status_code == 404


def test_mapping_freezes_subject_not_email_and_reuses_existing_cloud_binding(runtime):
    from app.db_models import UserDB, CloudAccountDB
    owner = str(uuid.uuid4())
    with db.session_scope() as session:
        session.add(UserDB(id=owner, email="unrelated@example.com", password_hash="disabled")); session.flush()
        session.add(CloudAccountDB(user_id=owner, issuer=settings.cloud_auth_url,
            subject=runtime.subjects["alice-token"], email="not-for-binding@example.com", session_encrypted="unread"))
    alice = identity.verified_user("alice-token")
    bob = identity.verified_user("bob-token")
    assert alice.user_id == owner and bob.user_id != owner
    assert identity.verified_user("bob-token").user_id == bob.user_id


def test_revoked_lease_blocks_copied_context_and_wrong_owner():
    lease = identity.CredentialLease("owner", "memory-only-token")
    scope = identity._credential.set(lease)
    try:
        copied = copy_context()
        assert copied.run(identity.content_bearer, "owner") == "memory-only-token"
        with pytest.raises(HTTPException):
            identity.content_bearer("another-owner")
        lease.active = False; lease.bearer = ""
        with pytest.raises(HTTPException):
            copied.run(identity.content_bearer, "owner")
    finally:
        identity._credential.reset(scope)


def test_new_table_imported_before_startup_and_protected_from_direct_clients(runtime):
    from app.services.workspace_bootstrap import protect_api_tables
    from sqlalchemy.dialects import postgresql
    statements = []
    table = db.Base.metadata.tables["content_cloud_identities"]
    class Connection:
        dialect = postgresql.dialect()
        def exec_driver_sql(self, sql):
            statements.append(sql)
            return SimpleNamespace(scalar_one=lambda: "vinote_private")
    protect_api_tables(Connection(), [table])
    assert statements[1:] == [
        "ALTER TABLE vinote_private.content_cloud_identities ENABLE ROW LEVEL SECURITY",
        "REVOKE ALL ON TABLE vinote_private.content_cloud_identities FROM PUBLIC, anon, authenticated"]


def test_switch_requires_workspace_and_defaults_false(monkeypatch):
    from app.config import Settings
    assert Settings.__dataclass_fields__["content_cloud_runtime"].default is False
    monkeypatch.setattr(settings, "content_cloud_runtime", True)
    monkeypatch.setattr(settings, "workspace_cloud_runtime", False)
    from app import create_app
    with pytest.raises(ValueError, match="workspace"):
        create_app()


def test_vilab_gateway_uses_bound_token_never_stored_refresh(runtime, monkeypatch):
    lease = identity.CredentialLease("caller", "context-token")
    scope = identity._credential.set(lease)
    seen = []
    from app.services.cloud_account_service import CloudAccountService
    monkeypatch.setattr(CloudAccountService, "access_token", lambda *_: pytest.fail("stored session forbidden"))
    def mock_request(method, url, **kwargs):
        seen.append(kwargs["headers"])
        return httpx.Response(200, request=httpx.Request(method, url), json={"data": []})
    monkeypatch.setattr(httpx, "request", mock_request)
    try:
        runtime.real_request(VILabCloudService(), "caller", "GET", "/v1/models")
        assert seen == [{"Authorization": "Bearer context-token"}]
    finally:
        lease.active = False; identity._credential.reset(scope)


def test_media_rejects_disguised_playlist_without_spawning_or_provider(runtime, monkeypatch, tmp_path):
    path = tmp_path / "fake.mp4"; path.write_bytes(b"#EXTM3U\nhttp://127.0.0.1/private")
    monkeypatch.setattr(worker.subprocess, "run", lambda *a, **kw: pytest.fail("must reject before ffmpeg"))
    with pytest.raises(HTTPException, match="格式"):
        worker.normalize_media(path, tmp_path / "output.wav")


def test_real_audio_post_to_pipeline_with_memory_only_asr_token(runtime, monkeypatch):
    from app.services import asr_stream_service
    from app.services.cloud_account_service import CloudAccountService
    pcm = io.BytesIO()
    with wave.open(pcm, "wb") as audio:
        audio.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
        audio.writeframes(b"\x01\x00" * 16000)
    seen = []
    def catalog(url, headers, **kwargs):
        assert url == "https://model.example/v1/models"
        assert headers == {"Authorization": "Bearer alice-token"}
        return httpx.Response(200, request=httpx.Request("GET", url), json={"data": [{
            "id": "asr-fixed", "modelType": "asr", "runtimeStatus": "available",
            "capabilities": {"recordedAudio": {"protocol": 1, "supported": True,
                "strategy": "adaptive_pause", "policySource": "service_budget",
                "maxSessionAudioBytes": 2097152}}}]})
    def recognize(origin, token, model, path, **kwargs):
        assert (origin, token, model) == ("https://model.example", "alice-token", "asr-fixed")
        seen.append(kwargs)
        return {"text": "Original audio source"}
    monkeypatch.setattr(httpx, "get", catalog)
    monkeypatch.setattr(asr_stream_service, "recognize_pcm", recognize)
    monkeypatch.setattr(CloudAccountService, "access_token", lambda *_: pytest.fail("refresh/stored token forbidden"))
    result = upload(runtime, source="audio", content=pcm.getvalue())
    assert result.status_code == 200, result.text
    read = runtime.client.get("/api/task/" + result.json()["task_id"], headers=headers())
    assert read.json()["status"] == "success", read.text
    assert len(seen) == 1
    assert read.json()["result"]["markdown"].startswith("# Offline result")
    folder = worker.artifacts().find_task_dir(result.json()["task_id"])
    assert (folder / "request.json").is_file()
    assert b"alice-token" not in (folder / "request.json").read_bytes()


def test_background_context_isolated_per_request_and_revoked_after_response(runtime):
    import anyio
    from starlette.responses import JSONResponse
    from starlette.background import BackgroundTask
    copies, observed = [], []
    async def application(scope, receive, send):
        owner = scope["state"]["content_user"].user_id
        initial = identity.content_bearer(owner)
        await asyncio.sleep(0.02)
        assert identity.content_bearer(owner) == initial
        def background():
            assert identity.content_bearer(owner) == initial
            observed.append((owner, initial))
            copies.append((copy_context(), owner))
        await JSONResponse({"ok": True}, background=BackgroundTask(background))(scope, receive, send)
    async def run():
        app = identity.ContentCredentialMiddleware(application)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://test") as client:
            return await asyncio.gather(*[client.get("/api/content-service/capabilities", headers=headers(token))
                                         for token in ("alice-token", "bob-token")])
    assert all(r.status_code == 200 for r in asyncio.run(run()))
    assert {token for _, token in observed} == {"alice-token", "bob-token"}
    for context, owner in copies:
        with pytest.raises(HTTPException):
            context.run(identity.content_bearer, owner)


def test_device_capabilities_keeps_existing_generation_auth_and_video_contract(runtime, monkeypatch):
    from app import create_app
    from app.models.auth import AuthenticatedUser
    from app.services.generation_auth_service import get_generation_user
    monkeypatch.setattr(settings, "content_cloud_runtime", False)
    monkeypatch.setattr(settings, "workspace_cloud_runtime", False)
    app = create_app()
    client = TestClient(app)
    assert client.get("/api/content-service/capabilities").status_code == 401
    app.dependency_overrides[get_generation_user] = lambda: AuthenticatedUser("device-user")
    result = client.get("/api/content-service/capabilities")
    assert result.status_code == 200
    assert result.json()["video_url"] is True
    assert result.json()["max_upload_bytes"] == 2 * 1024 * 1024 * 1024
    assert result.json()["sync"] is False and result.json()["content_service_protocol"] == 1
    assert runtime.provider_calls == []
    client.close()


def test_request_budget_prevents_unbounded_json_and_unknown_length_upload(runtime, monkeypatch):
    result = runtime.client.post("/api/generate", headers={**headers(operation="too-large"),
        "Content-Type": "application/json"}, content=b"x" * 65537)
    assert result.status_code == 413
    monkeypatch.setattr(settings, "content_upload_max_bytes", 1024)
    assert upload(runtime, content=b"x" * 1025).status_code == 413
    assert runtime.provider_calls == []


def test_video_preview_is_authenticated_read_only_and_never_dispatches_models(runtime, monkeypatch):
    from app.services import bilibili_source_service as bili
    source = SimpleNamespace(canonical_url="https://www.bilibili.com/video/BV1Pyta66EDh/?p=2",
        title="Offline video", video_id="BV1Pyta66EDh_p2", duration=60,
        audio_url="https://media.example/secret-signed-path")
    seen = []
    monkeypatch.setattr(bili, "resolve", lambda url: (seen.append(url), source)[1])
    path = "/api/content-service/video-source"
    assert runtime.client.post(path, json={"url": source.canonical_url}).status_code == 401
    result = runtime.client.post(path, headers=headers(), json={"url": source.canonical_url})
    assert result.status_code == 200
    assert result.json()["video_id"] == source.video_id
    assert "audio_url" not in result.json() and "signed" not in result.text
    assert runtime.provider_calls == []
    assert not list(runtime.root.iterdir())
    with db.session_scope() as session:
        assert session.scalar(select(func.count()).select_from(identity.ContentIdentityDB)) == 0


def test_video_preview_blocked_is_source_error_without_task_or_model(runtime, monkeypatch):
    from app.services import bilibili_source_service as bili
    def blocked(_):
        raise bili.BilibiliSourceError("VIDEO_SOURCE_BLOCKED")
    monkeypatch.setattr(bili, "resolve", blocked)
    result = runtime.client.post("/api/content-service/video-source", headers=headers(),
        json={"url": "https://www.bilibili.com/video/BV12iFezdEZS/"})
    assert result.status_code == 503
    assert result.json()["detail"]["code"] == "VIDEO_SOURCE_BLOCKED"
    assert "尚未开始转写" in result.json()["detail"]["message"]
    assert not list(runtime.root.iterdir()) and runtime.provider_calls == []


def test_bilibili_download_failure_does_not_call_asr_or_summary_or_requeue(runtime, monkeypatch):
    from app.routers import cloud_content
    from app.services import bilibili_source_service as bili
    monkeypatch.setattr(cloud_content, "_public_target", lambda u: (u, u))
    seen = []
    def unavailable(url):
        seen.append(url)
        raise ValueError("video unavailable")
    monkeypatch.setattr(bili, "resolve", unavailable)
    body = {"video_url": "https://www.bilibili.com/video/BV1Pyta66EDh"}
    result = runtime.client.post("/api/generate", headers=headers(operation="video-once"), json=body)
    assert result.status_code == 200
    task = result.json()["task_id"]
    read = runtime.client.get("/api/task/" + task, headers=headers())
    assert read.json()["status"] == "failed"
    assert read.json()["retryable"] is False
    assert all(method == "GET" for _, _, method, _ in runtime.provider_calls)
    count = len(runtime.provider_calls)
    again = runtime.client.post("/api/generate", headers=headers(operation="video-once"), json=body)
    assert again.json()["task_id"] == task
    assert seen == [body["video_url"]] and len(runtime.provider_calls) == count


def test_bilibili_download_normalize_pipeline_retains_source_and_repeated_receipt(runtime, monkeypatch):
    from app.routers import cloud_content
    from app.services import bilibili_source_service as bili
    from app.models.transcript import TranscriptResult, TranscriptSegment
    monkeypatch.setattr(cloud_content, "_public_target", lambda u: (u, u))
    source = SimpleNamespace(canonical_url="https://www.bilibili.com/video/BV1Pyta66EDh?p=2",
        title="Offline source part two", video_id="BV1Pyta66EDh_p2", duration=1)
    downloads, recognized = [], []
    monkeypatch.setattr(bili, "resolve", lambda _: source)
    def download(src, target, limit):
        assert src is source and limit == settings.content_upload_max_bytes
        downloads.append(target)
        with wave.open(str(target), "wb") as audio:
            audio.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
            audio.writeframes(b"\x01\x00" * 16000)
    monkeypatch.setattr(bili, "download_audio", download)
    def transcribe(service, context):
        assert context.source_video_url is None  # No unrestricted screenshot downloader.
        assert context.audio_meta.platform == "bilibili"
        assert context.audio_meta.video_id == source.video_id
        recognized.append(context.task_id)
        return TranscriptResult("zh", "Offline video words", [TranscriptSegment(0, 1, "Offline video words")])
    monkeypatch.setattr(worker.VideoContentService, "_transcribe_audio", transcribe)
    body = {"video_url": source.canonical_url}
    result = runtime.client.post("/api/generate", headers=headers(operation="video-success"), json=body)
    assert result.status_code == 200, result.text
    task = result.json()["task_id"]
    read = runtime.client.get("/api/task/" + task, headers=headers()).json()
    assert read["status"] == "success", read
    assert read["result"]["platform"] == "bilibili" and read["result"]["video_id"] == source.video_id
    folder = worker.artifacts().find_task_dir(task)
    assert json.loads((folder / "video_source.json").read_text())["url"] == source.canonical_url
    assert (folder / "media" / "source.m4a").is_file()
    count = len(runtime.provider_calls)
    assert runtime.client.post("/api/generate", headers=headers(operation="video-success"), json=body).json()["task_id"] == task
    assert len(downloads) == len(recognized) == 1 and len(runtime.provider_calls) == count
