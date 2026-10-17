"""Media POST must be pollable before a delayed worker, with no replay."""
import ast
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import json
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock

from fastapi import BackgroundTasks, HTTPException
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from starlette.requests import Request

from app.db_models import SourceRequestDB
from app.models.note import NoteRequest
from app.models.source_request import SourceInput, SourceSubmission
from app.services.source_request_service import SourceRequestService
from app.services.task_artifact_service import TaskArtifactService

ROOT = Path(__file__).resolve().parents[1]
URL = "https://www.bilibili.com/video/BV12iFezdEZS?p=1"


def isolated_router():
    path = ROOT / "app/routers/note.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id in {
                "_note_service", "_source_requests"} for t in node.targets):
            node.value = ast.Constant(None)
    ast.fix_missing_locations(tree)
    module = ModuleType("media_submission_router")
    exec(compile(tree, str(path), "exec"), module.__dict__)
    return module


def request(operation=None, desktop=False):
    headers = []
    if operation is not None:
        headers.append((b"x-vinote-operation-id", operation.encode()))
    if desktop:
        headers.append((b"x-vinote-client", b"desktop"))
    return Request({"type": "http", "method": "POST", "path": "/api/generate", "headers": headers})


@pytest.fixture
def env(tmp_path, monkeypatch):
    module = isolated_router()
    artifacts = TaskArtifactService(tmp_path / "output")
    forbidden = Mock(side_effect=AssertionError("submission must not call worker/model/network"))
    module._note_service = SimpleNamespace(artifact_service=artifacts, get_status=artifacts.get_status,
                                            get_result=artifacts.get_result, generate=forbidden)
    module._run_task = forbidden
    module.ensure_source = forbidden
    from app.services.note_repository import NoteRepository
    monkeypatch.setattr(NoteRepository, "can_access_task", lambda *a, **k: False)
    engine = create_engine(f"sqlite:///{tmp_path / 'receipts.db'}", connect_args={
        "check_same_thread": False, "timeout": 10})
    SourceRequestDB.__table__.create(engine)

    @contextmanager
    def sessions():
        with Session(engine, expire_on_commit=False) as db:
            with db.begin():
                yield db

    module._source_requests = SourceRequestService(sessions)
    yield SimpleNamespace(note=module, artifacts=artifacts, sessions=sessions, forbidden=forbidden,
                          owner=SimpleNamespace(user_id="media-owner"), output=tmp_path / "output")
    engine.dispose()


def submit(env, operation=None, *, desktop=False, user="owner", **changes):
    values = {"video_url": URL, **changes}
    tasks = BackgroundTasks()
    result = env.note.generate_note_async(NoteRequest(**values), tasks,
        request(operation, desktop), user=env.owner if user == "owner" else user)
    return result, tasks


@pytest.mark.parametrize("operation", [None, "once-media"])
def test_immediately_pollable_with_owner_before_worker_or_model_catalog(env, operation):
    result, tasks = submit(env, operation, desktop=True, workflow="meeting", style=None, speaker_count=2)
    task = result["task_id"]
    folder = env.artifacts.find_task_dir(task)
    assert (folder / "recording_owner").read_text(encoding="utf-8") == env.owner.user_id
    assert not (folder / "request.json").exists()  # frozen model guard still captures in worker
    status = env.note.get_task_status(task, user=env.owner)
    assert status.status == "pending" and status.retryable is False
    assert result["source_type"] == "video"
    if operation:
        receipt = env.note._source_requests.get(env.owner.user_id, operation)
        assert receipt.source_type == "video" and receipt.status == "pending"
    assert len(tasks.tasks) == 1
    queued = tasks.tasks[0].kwargs
    assert queued["task_id"] == task and queued["user_id"] == env.owner.user_id
    assert queued["req"].diarize and queued["req"].speaker_count is None
    assert queued["req"].style == "detailed"
    assert queued["trace_context"] is not None
    env.forbidden.assert_not_called()
    with pytest.raises(HTTPException) as exc:
        env.note.get_task_status(task, user=SimpleNamespace(user_id="other-owner"))
    assert exc.value.status_code == 404
    with pytest.raises(HTTPException) as exc:
        env.note.get_task_status(task, user=None)
    assert exc.value.status_code == 404


def test_accepted_duplicate_survives_service_restart_without_queue_or_state_reset(env):
    first, tasks = submit(env, "once-media")
    folder = env.artifacts.find_task_dir(first["task_id"])
    env.artifacts.update_status(folder, "transcribing", "existing in-flight ASR")
    before = (folder / "status.json").read_bytes()
    env.note._source_requests = SourceRequestService(env.sessions)
    second, repeated = submit(env, "once-media")
    assert second["task_id"] == first["task_id"] and second["state"] == "accepted"
    assert second["source_type"] == "video"
    assert len(tasks.tasks) == 1 and not repeated.tasks
    assert (folder / "status.json").read_bytes() == before
    assert env.note.source_receipt("once-media", response=SimpleNamespace(headers={}),
                                    user=env.owner).task_id == first["task_id"]
    env.forbidden.assert_not_called()


def test_unknown_reserved_claim_is_read_only_not_recreated_or_requeued(env):
    req = NoteRequest(video_url=URL)
    claim = env.note._source_requests.reserve(env.owner.user_id, "unknown-media",
        SourceSubmission(source=SourceInput(kind="url", url=URL), options=req.model_dump(exclude={"video_url", "asr_model"})))
    result, tasks = submit(env, "unknown-media")
    assert result["state"] == "reserved" and result["task_id"] == claim.task_id
    assert not tasks.tasks and not env.output.exists()
    env.forbidden.assert_not_called()


@pytest.mark.parametrize("change", [{"video_url": URL.replace("p=1", "p=2")}, {"workflow": "meeting"},
                                   {"style": "meeting"}, {"diarize": True}, {"output_language": "en"},
                                   {"model_profile_id": "different"}, {"stt_profile_id": "different"}])
def test_operation_binds_source_and_all_effective_options(env, change):
    first, _ = submit(env, "once-media")
    with pytest.raises(HTTPException) as exc:
        submit(env, "once-media", **change)
    assert exc.value.status_code == 409
    assert len(list(env.output.iterdir())) == 1
    assert env.artifacts.get_status(first["task_id"])["status"] == "pending"


def test_fingerprint_uses_normalized_worker_options(env):
    first, _ = submit(env, "desktop-options", desktop=True, workflow="meeting", style=None, diarize=False, speaker_count=2)
    repeated, tasks = submit(env, "desktop-options", desktop=True, workflow="meeting", style="detailed", diarize=True, speaker_count=5)
    assert first["task_id"] == repeated["task_id"] and not tasks.tasks


def test_concurrent_same_operation_queues_exactly_once(env):
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: submit(env, "race-media"), range(2)))
    assert len({result[0]["task_id"] for result in results}) == 1
    assert sum(len(result[1].tasks) for result in results) == 1
    assert len(list(env.output.iterdir())) == 1
    env.forbidden.assert_not_called()


def test_anonymous_without_operation_remains_pollable_without_invented_owner(env):
    result, tasks = submit(env, user=None)
    folder = env.artifacts.find_task_dir(result["task_id"])
    assert not (folder / "recording_owner").exists()
    assert env.note.get_task_status(result["task_id"], user=None).status == "pending"
    assert len(tasks.tasks) == 1 and tasks.tasks[0].kwargs["user_id"] is None


@pytest.mark.parametrize("operation", ["anon-once", ""])
def test_anonymous_operation_cannot_create_durable_claim_or_task(env, operation):
    with pytest.raises(HTTPException) as exc:
        submit(env, operation, user=None)
    assert exc.value.status_code == 401 and not env.output.exists()


@pytest.mark.parametrize("url", ["https://www.bilibili.com/video/BVbad", URL + "&p=2",
                                 "https://user:private@www.bilibili.com/video/BV12iFezdEZS"])
def test_invalid_media_input_does_not_reserve_create_or_queue(env, url):
    with pytest.raises(HTTPException) as exc:
        submit(env, "bad-media", video_url=url)
    assert exc.value.status_code == 400 and not env.output.exists()
    with pytest.raises(HTTPException) as missing:
        env.note._source_requests.get(env.owner.user_id, "bad-media")
    assert missing.value.status_code == 404
    env.forbidden.assert_not_called()


def test_operation_rejects_temporary_secret_before_task_creation(env):
    with pytest.raises(HTTPException) as exc:
        submit(env, "secret-media", api_key="test-fixture-not-a-key")
    assert exc.value.status_code == 400 and not env.output.exists()


def test_receipt_accept_failure_does_not_queue_and_reserved_retry_remains_get_only(env, monkeypatch):
    original = env.note._source_requests.accept
    monkeypatch.setattr(env.note._source_requests, "accept", Mock(side_effect=RuntimeError("db unavailable")))
    with pytest.raises(RuntimeError):
        submit(env, "interrupted-media")
    monkeypatch.setattr(env.note._source_requests, "accept", original)
    result, tasks = submit(env, "interrupted-media")
    assert result["state"] == "reserved" and not tasks.tasks
    env.forbidden.assert_not_called()


@pytest.mark.parametrize("explicit", [False, True])
def test_desktop_video_note_does_not_implicitly_enable_speaker_analysis(env, explicit):
    result, tasks = submit(env, "note-options", desktop=True, workflow="note_organization",
                           diarize=explicit, speaker_count=2)
    queued = tasks.tasks[0].kwargs
    assert queued["req"].diarize is explicit
    assert queued["req"].speaker_count == 2
    assert queued["trace_context"].workflow == "note_organization"
    assert env.note.get_task_status(result["task_id"], user=env.owner).status == "pending"
    env.forbidden.assert_not_called()


@pytest.mark.parametrize("workflow,explicit,expected", [
    ("note_organization", False, False), ("note_organization", True, True), ("meeting", False, True)])
def test_sync_media_entry_has_same_workflow_boundary(env, monkeypatch, workflow, explicit, expected):
    from contextlib import nullcontext
    generated = Mock(return_value=SimpleNamespace(
        audio_meta=SimpleNamespace(title="fixture", duration=1, platform="bilibili", video_id="fixture_p1"),
        markdown="fixture", summary_mode="default"))
    env.note._note_service.generate = generated
    monkeypatch.setattr(env.note, "desktop_trace", lambda *a: nullcontext())
    env.note.generate_note_sync(NoteRequest(video_url=URL, workflow=workflow, diarize=explicit),
                                  request(desktop=True), user=env.owner)
    assert generated.call_args.kwargs["diarize"] is expected


def test_old_forced_diarization_receipt_is_not_rewritten_to_new_note_options(env):
    old = NoteRequest(video_url=URL, workflow="note_organization", diarize=True, speaker_count=None)
    old_claim = env.note._source_requests.reserve(env.owner.user_id, "old-desktop-note",
        SourceSubmission(source=SourceInput(kind="url", url=URL), options=old.model_dump(exclude={"video_url", "asr_model"})))
    folder = env.artifacts.create_task_dir(old_claim.task_id)
    (folder / "recording_owner").write_text(env.owner.user_id, encoding="utf-8")
    frozen = folder / "task_model_source.json"
    frozen.write_bytes(b'{"diarize":true,"historical-fixture":true}')
    env.artifacts.update_status(folder, "transcribing", "old accepted execution")
    env.note._source_requests.accept(env.owner.user_id, old_claim.operation_id, old_claim.task_id, status="pending")
    before = (folder / "status.json").read_bytes(), frozen.read_bytes()
    with pytest.raises(HTTPException) as exc:
        submit(env, "old-desktop-note", desktop=True, workflow="note_organization", diarize=False)
    assert exc.value.status_code == 409
    assert before == ((folder / "status.json").read_bytes(), frozen.read_bytes())
    # Explicitly retaining the old selection only reads the old receipt.
    result, tasks = submit(env, "old-desktop-note", desktop=True,
                           workflow="note_organization", diarize=True)
    assert result["task_id"] == old_claim.task_id and not tasks.tasks
    assert "source_type" not in result
    assert env.note._source_requests.get(env.owner.user_id, "old-desktop-note").source_type is None
    env.forbidden.assert_not_called()


def test_explicit_pair_participates_in_media_operation_identity(env):
    pair = {"asr_model": "chosen-asr", "model_name": "chosen-llm"}
    first, queued = submit(env, "paired-media", **pair)
    repeated, no_queue = submit(env, "paired-media", **pair)
    assert first["task_id"] == repeated["task_id"]
    assert len(queued.tasks) == 1 and not no_queue.tasks
    with pytest.raises(HTTPException) as exc:
        submit(env, "paired-media", **{**pair, "asr_model": "different-asr"})
    assert exc.value.status_code == 409
    env.forbidden.assert_not_called()
