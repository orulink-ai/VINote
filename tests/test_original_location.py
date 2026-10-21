"""Cookie/owner isolation and original-only locations; no provider or OS reveal."""
from contextlib import contextmanager
import json
from pathlib import Path
import subprocess
from types import SimpleNamespace
import uuid

from fastapi import FastAPI
from fastapi.testclient import TestClient
import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.config import settings
from app.db import Base
from app.db_models import NoteDB
from app.models.auth import UserResponse
from app.routers import original_location as router
from app.services import local_file_service, note_repository, original_location
from app.services.auth_service import create_access_token
from app.services.original_location import local_file
from app.services.task_artifact_service import TaskArtifactService


@pytest.fixture
def location(tmp_path, monkeypatch):
    def forbidden(*a, **kw):
        raise AssertionError("Location reads must not run subprocesses or call providers")
    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", forbidden)
    for key, value in dict(desktop_runtime=True, workspace_cloud_runtime=False, content_cloud_runtime=False,
                           cloud_auth_url="", data_dir=tmp_path / "data", output_dir=tmp_path / "output").items():
        monkeypatch.setattr(settings, key, value)
    engine = create_engine("sqlite:///" + str(tmp_path / "state.db"))
    Base.metadata.create_all(engine)

    @contextmanager
    def scope():
        with Session(engine, expire_on_commit=False) as db, db.begin():
            yield db

    monkeypatch.setattr(local_file_service, "session_scope", scope)
    monkeypatch.setattr(note_repository, "session_scope", scope)
    monkeypatch.setattr(original_location, "session_scope", scope)
    files = local_file_service.LocalFileService()
    identifier, name, imported = files.new_target("alice", "会议录屏.webm")
    imported.write_bytes(b"owned imported original")
    files.register("alice", identifier, name, imported)
    artifacts = TaskArtifactService(settings.output_dir)
    task = str(uuid.uuid4())
    folder = artifacts.create_task_dir(task)
    (folder / ".task_id").write_text(task)
    (folder / "recording_owner").write_text("alice")
    (folder / "request.json").write_text(json.dumps({"request": {"workflow": "meeting", "title": "source"}}))
    source = tmp_path / "input.webm"
    source.write_bytes(b"retained original bytes")
    retained = artifacts.stage_source_media(folder, str(source), media_kind="video")
    with scope() as db:
        db.add(NoteDB(id="saved", title="meeting", content="saved content", task_id=task,
                      source_type="meeting_video", created_by="alice"))
    context = SimpleNamespace(scope=scope, imported=imported, retained=retained, folder=folder, task=task,
                              artifacts=artifacts, host="127.0.0.1", identifier=identifier)
    context.urls = [f"/api/files/{identifier}/local-path", "/api/notes/saved/media/local-path",
                    f"/api/task/{task}/original/local-path", f"/api/files/task:{task}/local-path"]
    app = FastAPI()

    @app.middleware("http")
    async def client_address(request, call_next):
        # Installed TestClient predates its client= argument; supply ASGI peer.
        request.scope["client"] = (context.host, 12345)
        return await call_next(request)

    app.include_router(router.router, prefix="/api")
    with TestClient(app) as client:
        client.cookies.set(settings.auth_cookie_name, create_access_token(UserResponse(id="alice", email="alice@example.invalid")))
        context.client = client
        yield context
    engine.dispose()


def _snapshot(c):
    return {str(path): path.read_bytes() for root in (settings.data_dir, settings.output_dir)
            for path in root.rglob("*") if path.is_file()}


@pytest.mark.parametrize("index", range(4))
def test_each_owned_source_returns_existing_original_without_changing_any_file(location, index):
    c = location
    before = _snapshot(c)
    response = c.client.get(c.urls[index])
    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, no-store"
    result = response.json()
    assert set(result) == {"local_path_protocol", "absolute_path", "filename"}
    assert result["local_path_protocol"] == 1
    assert Path(result["absolute_path"]) == (c.imported if index == 0 else c.retained).resolve()
    assert _snapshot(c) == before


@pytest.mark.parametrize("authorization", ["Bearer synthetic", "", "Basic synthetic"])
def test_rejects_any_authorization_header_even_with_a_valid_cookie(location, authorization):
    for url in location.urls:
        response = location.client.get(url, headers={"Authorization": authorization})
        assert response.status_code == 401 and response.headers["cache-control"] == "private, no-store"
        assert "absolute_path" not in response.text


def test_bearer_alone_and_missing_cookie_cannot_read_os_paths(location):
    location.client.cookies.clear()
    for headers in ({}, {"Authorization": "Bearer " + create_access_token(UserResponse(id="alice", email="a@example.invalid"))}):
        response = location.client.get(location.urls[0], headers=headers)
        assert response.status_code == 401


def test_cross_owner_never_discloses_any_location(location):
    location.client.cookies.set(settings.auth_cookie_name, create_access_token(UserResponse(id="bob", email="bob@example.invalid")))
    for url in location.urls:
        response = location.client.get(url)
        assert response.status_code == 404 and "absolute_path" not in response.text
        assert response.headers["cache-control"] == "private, no-store"


@pytest.mark.parametrize("flag", ["desktop_runtime", "workspace_cloud_runtime", "content_cloud_runtime"])
def test_browser_or_cloud_never_proxies_or_discloses_paths(location, monkeypatch, flag):
    monkeypatch.setattr(settings, flag, flag != "desktop_runtime")
    for url in location.urls:
        assert location.client.get(url).status_code == 404


def test_non_loopback_client_cannot_use_forwarded_headers_to_read_paths(location):
    location.host = "192.0.2.7"
    response = location.client.get(location.urls[0], headers={"X-Forwarded-For": "127.0.0.1"})
    assert response.status_code == 403


@pytest.mark.parametrize("query", ["?path=C:/private.webm", "?source_url=https://example.invalid/file", "?playback=true"])
def test_rejects_path_url_and_playback_parameters(location, query):
    response = location.client.get(location.urls[0] + query)
    assert response.status_code == 422 and response.headers["cache-control"] == "private, no-store"


@pytest.mark.parametrize("damage", ["deleted", "missing", "owner", "mapping", "manifest"])
def test_missing_or_unverified_task_never_falls_back_to_other_media(location, damage):
    c = location
    if damage == "deleted": (c.folder / "recording_deleted").write_text("deleted")
    if damage == "missing": c.retained.unlink()
    if damage == "owner": (c.folder / "recording_owner").write_text("bob")
    if damage == "mapping": (c.folder / ".task_id").write_text(str(uuid.uuid4()))
    if damage == "manifest": (c.folder / "source_media.json").unlink()
    (c.folder / "media" / "another.webm").write_bytes(b"must not guess this file")
    for url in c.urls[1:]:
        assert c.client.get(url).status_code == 404


def test_owned_note_alone_does_not_authorize_another_owners_task(location):
    c = location
    (c.folder / "recording_owner").write_text("bob")
    assert c.client.get("/api/notes/saved/media/local-path").status_code == 404


def test_capture_only_source_needs_no_generation_request_and_returns_no_preview(location):
    c = location
    (c.folder / "request.json").unlink()
    preview = c.folder / "media" / ".playback-preview"
    preview.mkdir()
    (preview / "cached.webm").write_bytes(b"playback derivative")
    for url in c.urls[1:3]:
        response = c.client.get(url)
        assert response.status_code == 200 and Path(response.json()["absolute_path"]) == c.retained.resolve()


def test_independent_child_resolves_only_verified_canonical_original(location):
    c = location
    child = str(uuid.uuid4())
    folder = c.artifacts.create_task_dir(child)
    (folder / ".task_id").write_text(child)
    (folder / "recording_owner").write_text("alice")
    version = json.loads((c.folder / "source_media.json").read_text())["sha256"]
    reference = {"version": 1, "owner": "alice", "parent_task_id": c.task, "source_version": version}
    (folder / "source_reference.json").write_text(json.dumps(reference))
    with c.scope() as db:
        db.add(NoteDB(id="child-note", title="child", task_id=child, created_by="alice"))
    before = _snapshot(c)
    for url in (f"/api/task/{child}/original/local-path", "/api/notes/child-note/media/local-path"):
        response = c.client.get(url)
        assert response.status_code == 200 and Path(response.json()["absolute_path"]) == c.retained.resolve()
    assert before == _snapshot(c)
    reference["source_version"] = "0" * 64
    (folder / "source_reference.json").write_text(json.dumps(reference))
    assert c.client.get(f"/api/task/{child}/original/local-path").status_code == 404


def test_links_and_directories_cannot_be_revealed_as_original_files(location):
    c = location
    original = c.retained.with_name("other.webm")
    c.retained.rename(original)
    try:
        c.retained.symlink_to(original)
    except OSError:
        pytest.skip("Host does not allow synthetic symlinks")
    assert c.client.get(c.urls[2]).status_code == 404
    c.imported.unlink()
    c.imported.mkdir()
    assert c.client.get(c.urls[0]).status_code == 404


@pytest.mark.parametrize("path", ["relative.webm", "../file.webm", "file:///C:/a.webm", "https://example.invalid/a", "\\\\server\\share\\a.webm", "//server/share/a.webm"])
def test_os_location_validator_rejects_nonlocal_inputs_without_reading_them(path):
    with pytest.raises(Exception) as error:
        local_file(Path(path))
    assert error.value.status_code == 404
