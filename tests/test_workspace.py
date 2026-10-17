from contextlib import contextmanager

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db import Base
from app.models.workspace import PutNote, Operation
from app.services import workspace_service as module


@pytest.fixture
def service(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'workspace.db'}")
    Base.metadata.create_all(engine)
    @contextmanager
    def sessions():
        with Session(engine) as db, db.begin():
            yield db
    monkeypatch.setattr(module, "session_scope", sessions)
    from app.services import workspace_generation
    monkeypatch.setattr(workspace_generation, "session_scope", sessions)
    yield module.WorkspaceService()
    engine.dispose()


def payload(operation="one", revision=0, **kwargs):
    return PutNote(base_revision=revision, operation_id=operation,
                   title="会议", content="原文", **kwargs)


def test_retry_is_idempotent_and_old_operation_does_not_revert_newer_text(service):
    first = payload()
    a = service.put("owner", "note", first)
    assert service.put("owner", "note", first)["revision"] == a["revision"]
    second = payload("two", a["revision"])
    second.content = "第二版"
    b = service.put("owner", "note", second)
    replay = service.put("owner", "note", first)
    assert replay["content"] == "第二版"
    assert replay["revision"] == b["revision"]
    assert replay["version_count"] == b["version_count"]


def test_conflict_keeps_both_versions_and_isolates_owners(service):
    first = service.put("a", "note", payload())
    stale = payload("two", 0)
    stale.content = "未覆盖的冲突草稿"
    with pytest.raises(HTTPException) as error:
        service.put("a", "note", stale)
    assert error.value.status_code == 409
    assert error.value.detail["current"]["content"] == "原文"
    assert service.get("a", "note")["revision"] == first["revision"]
    with pytest.raises(HTTPException) as hidden:
        service.get("b", "note")
    assert hidden.value.status_code == 404
    assert service.list("b")["items"] == []


def test_deletion_is_tombstone_and_restore_preserves_history(service):
    first = service.put("a", "note", payload())
    deleted = service.set_deleted("a", "note", Operation(base_revision=first["revision"], operation_id="delete"), True)
    assert deleted["deleted"]
    assert service.list("a")["items"] == []
    assert len(service.list("a", include_deleted=True)["items"]) == 1
    with pytest.raises(HTTPException):
        service.put("a", "note", payload("stale", first["revision"]))
    restored = service.set_deleted("a", "note", Operation(base_revision=deleted["revision"], operation_id="restore"), False)
    assert restored["content"] == "原文"
    assert restored["version_count"] == first["version_count"]


def test_immutable_history_and_duplicate_operation_payload_rejected(service):
    version = dict(id="v1", title="纪要", content="历史", created_at="2026-10-11T00:00:00Z")
    first = service.put("a", "note", payload(versions=[version]))
    with pytest.raises(HTTPException):
        service.put("a", "note", payload(versions=[{**version, "content": "偷换"}]))
    with pytest.raises(HTTPException):
        service.put("a", "note", payload("new", first["revision"], versions=[{**version, "content": "偷换"}]))
    assert any(v["content"] == "历史" for v in service.get("a", "note")["versions"])


def test_versions_paginate_without_dropping_older_ones(service):
    versions = [dict(id=f"v{i}", title=str(i), content=str(i), created_at="2026-10-11T00:00:00Z") for i in range(65)]
    service.put("a", "note", payload(versions=versions))
    result = service.get("a", "note", versions_limit=50)
    assert len(result["versions"]) == 50
    rest = service.get("a", "note", versions_offset=result["next_versions_offset"])
    assert len({v["id"] for v in result["versions"] + rest["versions"]}) == result["version_count"]


def test_media_files_and_unknown_metadata_are_not_sync_payload():
    with pytest.raises(ValueError):
        payload(metadata={"file_path": "C:/private/recording.m4a"})
    with pytest.raises(ValueError):
        payload(transcript={"full_text": "", "segments": [{"start": 9, "end": 2, "text": "bad"}]})


def test_generation_failure_retries_without_damaging_original(service, monkeypatch):
    from app.services import workspace_generation as generation
    from app.models.workspace import GenerateVersion
    first = service.put("a", "note", payload())
    calls = []
    class Model:
        model = "test-model"
        def summarize(self, *args, **kwargs):
            calls.append(1)
            if len(calls) == 1:
                raise RuntimeError("provider failed")
            return "新纪要"
    @contextmanager
    def fake_model(*args):
        yield Model()
    monkeypatch.setattr(generation, "summarizer", fake_model)
    worker = generation.WorkspaceGeneration()
    request = GenerateVersion(base_revision=first["revision"], operation_id="generate-one")
    with pytest.raises(HTTPException):
        worker.generate(("a", "user"), "note", request)
    assert service.get("a", "note")["content"] == "原文"
    assert worker.jobs("a")[0]["status"] == "failed"
    result = worker.generate(("a", "user"), "note", request)
    assert result["content"] == "新纪要"
    assert worker.generate(("a", "user"), "note", request)["revision"] == result["revision"]
    assert len(calls) == 2


def test_generation_recovers_committed_result_after_lost_acknowledgement(service, monkeypatch):
    from app.services import workspace_generation as generation
    from app.models.workspace import GenerateVersion, WorkspaceGenerationDB
    first = service.put("a", "note", payload())
    request = GenerateVersion(base_revision=first["revision"], operation_id="generate-crash")
    generation_id = "generated-" + module.digest(["a", "note", request.operation_id])[:40]
    body = payload(generation_id, first["revision"])
    body.content = "已提交结果"
    saved = service.put("a", "note", body)
    with module.session_scope() as db:
        db.add(WorkspaceGenerationDB(owner="a", operation_id=request.operation_id, note_key="note",
            digest=module.digest({"key": "note", **request.model_dump()}),
            base_revision=first["revision"], output="已提交结果", status="running"))
    def never_call(*args):
        pytest.fail("committed work must not call the provider again")
    monkeypatch.setattr(generation, "summarizer", never_call)
    worker = generation.WorkspaceGeneration()
    result = worker.generate(("a", "user"), "note", request)
    assert result["revision"] == saved["revision"]
    assert result["content"] == "已提交结果"
    assert worker.jobs("a")[0]["status"] == "completed"


def test_generation_conflict_retains_generated_content(service, monkeypatch):
    from app.services import workspace_generation as generation
    from app.models.workspace import GenerateVersion
    first = service.put("a", "note", payload())
    class Model:
        model = "test"
        def summarize(self, *args, **kwargs):
            edit = payload("concurrent", first["revision"])
            edit.content = "另一设备的编辑"
            service.put("a", "note", edit)
            return "不能覆盖的生成结果"
    @contextmanager
    def fake_model(*args):
        yield Model()
    monkeypatch.setattr(generation, "summarizer", fake_model)
    with pytest.raises(HTTPException) as error:
        generation.WorkspaceGeneration().generate(("a", "user"), "note",
            GenerateVersion(base_revision=first["revision"], operation_id="concurrent-gen"))
    assert error.value.status_code == 409
    assert error.value.detail["generated_content"] == "不能覆盖的生成结果"
    assert service.get("a", "note")["content"] == "另一设备的编辑"


def test_evidence_history_is_immutable_and_missing_field_preserves_transcript(service):
    a = service.put("owner", "note", payload(transcript={"full_text": "旧证据", "aliases": {"speaker_1": "甲"}}))
    b = service.put("owner", "note", payload("edit", a["revision"]))
    assert b["transcript"]["full_text"] == "旧证据"
    c = service.put("owner", "note", payload("evidence", b["revision"], transcript={"full_text": "新证据"}))
    assert c["transcript"]["full_text"] == "新证据"
    assert service.evidence("owner", "note", a["revision"])["transcript"]["aliases"] == {"speaker_1": "甲"}
    with pytest.raises(HTTPException):
        service.evidence("another", "note", a["revision"])


def test_reserved_auto_version_ids_cannot_block_later_saves(service):
    version = dict(id="current-2", title="导入", content="内容", created_at="2026-10-11T00:00:00Z")
    a = service.put("a", "note", payload(versions=[version]))
    b = service.put("a", "note", payload("next", a["revision"]))
    assert b["revision"] == 2
    with pytest.raises(HTTPException) as error:
        service.put("a", "note", payload("malicious", b["revision"], versions=[{**version, "id": "__vinote:current:20"}]))
    assert error.value.status_code == 422


def test_omitted_and_null_transcript_have_distinct_operation_fingerprints(service):
    a = service.put("a", "note", payload(transcript={"full_text": "保留"}))
    request = payload("same-id", a["revision"])
    service.put("a", "note", request)
    with pytest.raises(HTTPException) as error:
        service.put("a", "note", payload("same-id", a["revision"], transcript=None))
    assert error.value.status_code == 409
    assert service.get("a", "note")["transcript"]["full_text"] == "保留"
