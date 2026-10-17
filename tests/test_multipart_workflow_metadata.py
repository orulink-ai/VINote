"""Multipart workflow regression against current source; no live model calls."""
import ast
from contextlib import nullcontext
import json
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.models.note import LocalFileRequest
from app.services.task_artifact_service import TaskArtifactService


def isolated_router(path):
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    # Do not initialize global service instances: route functions get test doubles.
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id in {"_note_service", "_source_requests"} for t in node.targets):
            node.value = ast.Constant(None)
    ast.fix_missing_locations(tree)
    module = ModuleType("workflow_staged_router")
    exec(compile(tree, str(path), "exec"), module.__dict__)
    return module


def fields(workflow="note_organization"):
    return dict(file_path="source.wav", title="synthetic", style="meeting", summary_mode="default",
                extras=None, output_language="zh-CN", model_profile_id=None, stt_profile_id=None,
                model_name=None, api_key=None, base_url=None, workflow=workflow)


def test_omitted_workflow_retains_legacy_default_without_private_data():
    original = isolated_router(ROOT / "app/routers/note.py")
    values = fields()
    values.pop("workflow")
    assert original._build_note_request_fields(**values).workflow == "note_organization"
    assert original._build_note_request_fields(**values).style == "meeting"


@pytest.fixture
def environment(tmp_path, monkeypatch):
    note = isolated_router(ROOT / "app/routers/note.py")
    artifacts = TaskArtifactService(output_dir=tmp_path / "output")
    result = SimpleNamespace(audio_meta=SimpleNamespace(title="synthetic", duration=1, platform="local", video_id="synthetic"),
                             markdown="# meeting", summary_mode="default")
    generate = Mock(return_value=result)
    note._note_service = SimpleNamespace(artifact_service=artifacts, generate_from_file=generate)
    note.ensure_source = Mock()
    note.normalize_audio_for_transcription = lambda path: path
    run = Mock()
    note._run_task_from_file = run
    note.desktop_trace = lambda context: nullcontext()
    # Still compute actual trace context from staged route/header/form values.
    monkeypatch.setattr(note.settings, "app_release_channel", "development", raising=False)
    app = FastAPI()
    app.include_router(note.router, prefix="/api")
    owner = SimpleNamespace(user_id="staged-owner")
    app.dependency_overrides[note.get_optional_current_user] = lambda: owner
    app.dependency_overrides[note.get_current_user] = lambda: owner
    with TestClient(app) as client:
        yield SimpleNamespace(note=note, artifacts=artifacts, client=client, run=run, generate=generate,
                              owner=owner, output=tmp_path / "output")


@pytest.mark.parametrize("workflow,expected", [("meeting", "meeting"), ("note_organization", "note_organization"), ("invalid", "note_organization")])
def test_helper_normalizes_like_trace(workflow, expected):
    note = isolated_router(ROOT / "app/routers/note.py")
    req = note._build_note_request_fields(**fields(workflow))
    assert req.workflow == expected and req.style == "meeting"


@pytest.mark.parametrize("source,filename", [("audio", "recording.wav"), ("video", "recording.mp4")])
@pytest.mark.parametrize("desktop", [False, True])
@pytest.mark.parametrize("workflow,expected", [("meeting", "meeting"), ("note_organization", "note_organization"), ("invalid", "note_organization")])
def test_async_upload_persists_selected_workflow(environment, monkeypatch, source, filename, desktop, workflow, expected):
    env = environment
    monkeypatch.setattr(env.note, "_is_desktop_request", lambda request: desktop)
    response = env.client.post("/api/generate_from_upload",
        headers={"X-VINote-Client": "desktop"} if desktop else {},
        data={"source_type": source, "workflow": workflow, "style": "meeting"},
        files={"file": (filename, b"synthetic-media", "application/octet-stream")})
    assert response.status_code == 200, response.text
    folder = env.output / response.json()["task_id"]
    saved = json.loads((folder / "request.json").read_text(encoding="utf-8"))
    assert saved["request"]["workflow"] == expected
    assert saved["request"]["style"] == "meeting"
    assert env.run.call_args.kwargs["req"].workflow == expected
    if desktop:
        assert saved["trace"]["workflow"] == expected
    else:
        assert saved["trace"] is None


def test_omitted_workflow_keeps_existing_default(environment):
    response = environment.client.post("/api/generate_from_upload", data={"source_type": "audio"},
        files={"file": ("recording.wav", b"synthetic", "audio/wav")})
    assert response.status_code == 200, response.text
    assert environment.run.call_args.kwargs["req"].workflow == "note_organization"


def test_sync_upload_passes_workflow_to_helper_without_changing_summary_style(environment):
    note = environment.note
    original = note._build_note_request_fields
    seen = []
    def capture(**kwargs):
        req = original(**kwargs)
        seen.append(req)
        return req
    note._build_note_request_fields = capture
    response = environment.client.post("/api/generate_from_upload_sync", data={"source_type": "video", "workflow": "meeting", "style": "meeting"},
        files={"file": ("recording.mp4", b"synthetic", "video/mp4")})
    assert response.status_code == 200, response.text
    assert seen[0].workflow == "meeting"
    assert environment.generate.call_args.kwargs["style"] == "meeting"
    assert "workflow" not in environment.generate.call_args.kwargs


def test_new_saved_request_retry_keeps_workflow_and_trace(environment):
    env = environment
    response = env.client.post("/api/generate_from_upload", headers={"X-VINote-Client": "desktop"},
        data={"source_type": "video", "workflow": "meeting", "style": "meeting"},
        files={"file": ("recording.mp4", b"synthetic", "video/mp4")})
    assert response.status_code == 200
    task_id = response.json()["task_id"]
    folder = env.output / task_id
    original = (folder / "request.json").read_bytes()
    env.note._ACTIVE_FILE_TASKS.discard(task_id)
    env.artifacts.update_status(folder, "failed", "synthetic failure")
    env.run.reset_mock()
    retry = env.client.post(f"/api/task/{task_id}/retry")
    assert retry.status_code == 200, retry.text
    assert env.run.call_args.args[1].workflow == "meeting"
    assert env.run.call_args.args[3].workflow == "meeting"
    assert (folder / "request.json").read_bytes() == original


def test_legacy_mismatch_retry_keeps_style_trace_and_receipt_immutable(environment):
    env = environment
    folder = env.artifacts.create_task_dir("legacy")
    (folder / "media").mkdir(exist_ok=True)
    source = folder / "media/source_video.mp4"
    source.write_bytes(b"synthetic")
    env.artifacts.record_source_media(folder, source, media_kind="video")
    request = LocalFileRequest(**fields())
    context = env.note._desktop_trace_context(
        SimpleNamespace(headers={"X-VINote-Client": "desktop"}), workflow="meeting", source="local_file", media_type="video")
    env.note._persist_file_request(folder, request, env.owner.user_id, context)
    original = (folder / "request.json").read_bytes()
    env.artifacts.update_status(folder, "failed", "synthetic failure")
    response = env.client.post("/api/task/legacy/retry")
    assert response.status_code == 200, response.text
    req = env.run.call_args.args[1]
    trace = env.run.call_args.args[3]
    assert req.workflow == "note_organization" and req.style == "meeting"
    assert trace.workflow == "meeting"
    env.note._persist_file_request(folder, LocalFileRequest(**fields("meeting")), env.owner.user_id, trace)
    assert (folder / "request.json").read_bytes() == original
