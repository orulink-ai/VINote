"""Read-only playback-kind projection; no source-type migration or inference."""
from contextlib import contextmanager
import json
from unittest.mock import Mock

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db import Base
from app.models.note_library import NoteCreateRequest
from app.routers import note_library as router
from app.services.task_artifact_service import TaskArtifactService

TASK_ID = "00000000-0000-4000-8000-000000000001"

@pytest.fixture
def env(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'notes.db'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)

    @contextmanager
    def sessions():
        with Session(engine, expire_on_commit=False) as db:
            with db.begin():
                yield db

    monkeypatch.setattr("app.services.note_repository.session_scope", sessions)
    artifacts = TaskArtifactService(tmp_path / "output")
    monkeypatch.setattr(router, "_artifact_service", artifacts)
    owner = {"id": "owner"}
    from types import SimpleNamespace
    app = FastAPI()
    app.include_router(router.router, prefix="/api")
    app.dependency_overrides[router.get_current_user] = lambda: SimpleNamespace(user_id=owner["id"])
    with TestClient(app) as client:
        yield SimpleNamespace(client=client, artifacts=artifacts, owner=owner)
    engine.dispose()


def retained(env, kind="audio", *, source_type="video"):
    folder = env.artifacts.create_task_dir(TASK_ID)
    env.artifacts.update_status(folder, "success", "fixture ready")
    folder = env.artifacts.finalize_task_dir(folder, "fixture", TASK_ID)
    (folder / "recording_owner").write_text("owner", encoding="utf-8")
    media = folder / "media"
    media.mkdir()
    source = media / ("source_audio.m4a" if kind == "audio" else "source_video.mp4")
    source.write_bytes(b"original bytes")
    env.artifacts.record_source_media(folder, source, media_kind=kind)
    note = router._repository.create_note("owner", NoteCreateRequest(title="fixture", task_id=TASK_ID,
        source_type=source_type, video_url="https://www.bilibili.com/video/BV18tAnzvE9J?p=1"))
    return folder, source, note


@pytest.mark.parametrize("kind", ["audio", "video"])
def test_get_and_edit_reflect_actual_declared_track_keep_video_source_type(env, kind):
    folder, source, note = retained(env, kind)
    manifest_before = (folder / "source_media.json").read_bytes()
    for response in (env.client.get(f"/api/notes/{note.id}"),
                     env.client.patch(f"/api/notes/{note.id}", json={"content": "edited"})):
        assert response.status_code == 200, response.text
        assert response.json()["media_kind"] == kind
        assert response.json()["source_type"] == "video"
        assert "file_path" not in response.json() and str(source) not in response.text
    assert router._repository.get_note("owner", note.id).source_type == "video"
    assert (folder / "source_media.json").read_bytes() == manifest_before
    assert not (folder / "source_original.json").exists() and not (folder / "request.json").exists()
    assert source.read_bytes() == b"original bytes"


@pytest.mark.parametrize("kind", ["audio", "video"])
def test_create_response_uses_same_projection(env, kind):
    folder, _, _ = retained(env, kind)
    response = env.client.post("/api/notes", json={"title": "new saved content", "task_id": TASK_ID,
                                                "source_type": "video"})
    assert response.status_code == 201, response.text
    assert response.json()["media_kind"] == kind and response.json()["source_type"] == "video"
    assert not (folder / "source_original.json").exists()


@pytest.mark.parametrize("case", ["missing_manifest", "missing_media", "deleted", "unknown_kind", "malformed",
                                  "size_mismatch", "escape", "no_task"])
def test_missing_deleted_or_untrusted_evidence_is_unknown_not_url_guess(env, case):
    folder, source, note = retained(env)
    path = folder / "source_media.json"
    if case == "missing_manifest":
        path.unlink()
    elif case == "missing_media":
        source.unlink()
    elif case == "deleted":
        (folder / "recording_deleted").write_text("deleted")
    elif case == "malformed":
        path.write_text("{invalid")
    elif case == "no_task":
        note = router._repository.create_note("owner", NoteCreateRequest(title="source link only", source_type="video",
            video_url="https://www.bilibili.com/video/BV18tAnzvE9J"))
    else:
        manifest = json.loads(path.read_text(encoding="utf-8"))
        if case == "unknown_kind":
            manifest["media_kind"] = "file"
        elif case == "size_mismatch":
            manifest["size_bytes"] += 1
        else:
            manifest["relative_path"] = "../outside.m4a"
        path.write_text(json.dumps(manifest), encoding="utf-8")
    response = env.client.get(f"/api/notes/{note.id}")
    assert response.status_code == 200
    assert response.json()["media_kind"] is None and response.json()["source_type"] == "video"


def test_foreign_note_is_rejected_before_media_lookup(env, monkeypatch):
    _, _, note = retained(env)
    env.owner["id"] = "foreign"
    lookup = Mock(side_effect=AssertionError("must authorize before artifact access"))
    monkeypatch.setattr(env.artifacts, "find_task_dir", lookup)
    assert env.client.get(f"/api/notes/{note.id}").status_code == 404
    assert env.client.patch(f"/api/notes/{note.id}", json={"content": "other"}).status_code == 404
    lookup.assert_not_called()


def test_list_remains_unknown_and_does_not_scan_originals(env, monkeypatch):
    _, _, note = retained(env)
    monkeypatch.setattr(env.artifacts, "resolve_source_media", Mock(side_effect=AssertionError("list must not scan media")))
    response = env.client.get("/api/notes")
    assert response.status_code == 200
    row = next(item for item in response.json() if item["id"] == note.id)
    assert row["media_kind"] is None and row["source_type"] == "video"


def test_media_endpoint_permissions_and_playback_are_unchanged(env):
    _, source, note = retained(env)
    own = env.client.get(f"/api/notes/{note.id}/media")
    assert own.status_code == 200 and own.content == source.read_bytes()
    assert own.headers["content-type"].startswith("audio/")
    env.owner["id"] = "foreign"
    assert env.client.get(f"/api/notes/{note.id}/media").status_code == 404


def test_own_note_cannot_disclose_media_from_foreign_task_pointer(env):
    folder, _, note = retained(env)
    (folder / "recording_owner").write_text("foreign", encoding="utf-8")
    for response in (env.client.get(f"/api/notes/{note.id}"),
                     env.client.patch(f"/api/notes/{note.id}", json={"content": "my note"}),
                     env.client.post("/api/notes", json={"title": "another owned note", "task_id": TASK_ID})):
        assert response.status_code in {200, 201}, response.text
        assert response.json()["media_kind"] is None


@pytest.mark.parametrize("case", ["owner_missing", "mapping_missing", "mapping_wrong", "mapping_non_uuid"])
def test_absent_or_invalid_owner_uuid_evidence_stays_unknown(env, case):
    folder, _, note = retained(env)
    if case == "owner_missing":
        (folder / "recording_owner").unlink()
    elif case == "mapping_missing":
        (folder / ".task_id").unlink()
        # Direct canonical folder remains findable even without a mapping.
        folder.rename(env.artifacts.output_dir / TASK_ID)
    elif case == "mapping_wrong":
        (folder / ".task_id").write_text("00000000-0000-4000-8000-000000000002")
    else:
        (folder / ".task_id").write_text("legacy-task")
    response = env.client.get(f"/api/notes/{note.id}")
    assert response.status_code == 200 and response.json()["media_kind"] is None


@pytest.mark.parametrize("name", ["recording_owner", ".task_id"])
def test_hardlinked_identity_markers_are_not_authority(env, name):
    import os
    folder, _, note = retained(env)
    os.link(folder / name, folder / "shared-marker")
    response = env.client.get(f"/api/notes/{note.id}")
    assert response.status_code == 200 and response.json()["media_kind"] is None
