"""Synthetic local receipts/artifacts; provider and ASR calls are forbidden."""
import json
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from uuid import uuid4
from unittest.mock import Mock

import pytest
from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import select

from tests.test_meeting_summary_regeneration import case
from app.db_models import SourceRequestDB
from app.services.meeting_version_context import MeetingVersionService, MeetingVersionConfirmation
from app.services.task_model_source import SNAPSHOT_FILE
from app.services.vilab_cloud_service import VILabCloudService, _task_source


@pytest.fixture
def version(case, monkeypatch):
    c = case
    current = {"mode": "cloud", "configured": True, "server_url": "https://current.invalid",
               "connection_id": "synthetic-current", "connection_auth_mode": "api_key",
               "asr_model": "global-asr", "llm_model": "global-llm"}
    calls = []
    denied = set()
    def status(self, owner):
        frozen = _task_source.get()
        return dict(frozen[1]) if frozen and frozen[0] == owner else dict(current)
    monkeypatch.setattr(VILabCloudService, "status", status)
    monkeypatch.setattr(VILabCloudService, "connection_snapshot", lambda self, owner: self.status(owner))
    def models(self, owner):
        config = self.status(owner)
        calls.append((owner, config["server_url"], config.get("llm_model")))
        names = ["old-model"] if config["server_url"] == c.snapshot["server_url"] else ["chosen-other", "global-llm"]
        return ([{"id": name, "modelType": "llm", "runtimeStatus": "available"}
                for name in names if name not in denied]
                + ([{"id": "explicit-asr", "modelType": "asr", "runtimeStatus": "available"}]
                   if config["server_url"] == "https://current.invalid" else []))
    monkeypatch.setattr(VILabCloudService, "models", models)
    from app.services.vilab_connection_service import VILabConnectionService
    def validate(self, owner, snapshot):
        assert owner == "alice"
        if snapshot["server_url"] == c.snapshot["server_url"] and snapshot.get("connection_id") is None:
            return
        if snapshot.get("connection_id") != "synthetic-current" or snapshot["server_url"] != "https://current.invalid":
            raise HTTPException(409, "synthetic connection denied")
    monkeypatch.setattr(VILabConnectionService, "validate_snapshot", validate)
    service = MeetingVersionService(c.service)
    context = service.context("alice", c.parent)
    def body(**extra):
        return MeetingVersionConfirmation(operation_id=uuid4(), confirmed=True,
            context_revision=context["context_revision"], source_version=context["source"]["version"], **extra)
    return SimpleNamespace(c=c, service=service, context=context, body=body, current=current, calls=calls, denied=denied)


def accept(v, body=None):
    background = BackgroundTasks()
    receipt = v.service.accept("alice", v.c.parent, body or v.body(), background, v.c.note)
    return receipt, background


def test_default_context_is_readonly_and_exposes_original_llm_origin_not_globals(version):
    v = version
    before = {p: p.read_bytes() for p in v.c.folder.rglob("*") if p.is_file()}
    context = v.service.context("alice", v.c.parent)
    assert context["original_llm"] == {"model_name": "old-model", "server_url": v.c.snapshot["server_url"], "verified": True}
    assert context["default_asr_mode"] == "reuse" and context["default_llm_mode"] == "inherit"
    assert context["asr_modes"]["fresh"]["available"] is False
    assert v.calls == [] and before == {p: p.read_bytes() for p in v.c.folder.rglob("*") if p.is_file()}
    with v.c.sessions() as db: assert not db.scalars(select(SourceRequestDB)).all()


def test_default_creates_distinct_child_and_runs_original_frozen_llm_without_asr(version):
    v = version
    old = {p: p.read_bytes() for p in v.c.folder.rglob("*") if p.is_file()}
    receipt, background = accept(v)
    assert receipt.state == "accepted" and receipt.task_id != v.c.parent
    child = v.c.artifacts.find_task_dir(receipt.task_id)
    snapshot = json.loads((child / SNAPSHOT_FILE).read_text())
    assert snapshot["llm_model"] == "old-model" and snapshot["server_url"] == v.c.snapshot["server_url"]
    assert snapshot["needs_stt"] is False
    assert v.current["llm_model"] == "global-llm" and v.current["server_url"] == "https://current.invalid"
    def run(**kwargs):
        frozen = _task_source.get()[1]
        assert frozen["llm_model"] == "old-model" and frozen["server_url"] == v.c.snapshot["server_url"]
        assert kwargs["transcript"].full_text == v.c.transcript["full_text"]
    v.c.note.generate_from_transcript.side_effect = run
    v.current.update(mode="local", server_url="https://changed.invalid", llm_model="changed")
    for task in background.tasks: task.func(*task.args, **task.kwargs)
    assert v.c.note.generate_from_transcript.call_count == 1 and not v.c.note.generate_from_file.called
    assert all(p.read_bytes() == data for p, data in old.items())
    assert all(origin == v.c.snapshot["server_url"] for _, origin, _ in v.calls)


def test_two_confirmed_versions_are_new_tasks_without_rewriting_parent(version):
    first, _ = accept(version)
    second, _ = accept(version)
    assert first.task_id != second.task_id


def test_explicit_override_reads_current_catalog_only_on_demand_and_freezes_selection(version):
    v = version
    catalog = v.service.models("alice", v.c.parent, v.context["context_revision"])
    assert v.calls == [("alice", "https://current.invalid", None)]
    body = v.body(llm_mode="select", model_name="chosen-other", selection_revision=catalog["selection_revision"], connection_id="synthetic-current")
    receipt, _ = accept(v, body)
    snapshot = json.loads((v.c.artifacts.find_task_dir(receipt.task_id) / SNAPSHOT_FILE).read_text())
    assert snapshot["llm_model"] == "chosen-other" and snapshot["server_url"] == "https://current.invalid"
    assert snapshot["connection_id"] == "synthetic-current" and snapshot["needs_stt"] is False
    assert v.current["llm_model"] == "global-llm"


@pytest.mark.parametrize("change", ["source", "evidence", "llm", "owner", "active"])
def test_changed_source_owner_revision_or_original_llm_blocks_submission(version, change):
    v = version
    if change == "source": v.c.original.write_bytes(b"changed source")
    elif change == "evidence": v.c.artifacts.write_json(v.c.folder / "transcript.json", {**v.c.transcript, "full_text": "changed"})
    elif change == "llm": v.c.artifacts.write_json(v.c.folder / SNAPSHOT_FILE, {**v.c.snapshot, "llm_model": "different"})
    elif change == "owner": (v.c.folder / "recording_owner").write_text("other-owner")
    with pytest.raises(HTTPException):
        v.service.accept("alice", v.c.parent, v.body(), BackgroundTasks(), v.c.note, active=change == "active")
    assert not v.c.note.generate_from_transcript.called
    with v.c.sessions() as db: assert not db.scalars(select(SourceRequestDB)).all()


@pytest.mark.parametrize("choice", ["inherit", "select"])
def test_unavailable_exact_model_does_not_fall_back_or_reserve(version, choice):
    v = version
    if choice == "inherit":
        v.denied.add("old-model"); body = v.body()
    else:
        catalog = v.service.models("alice", v.c.parent, v.context["context_revision"])
        v.denied.add("chosen-other")
        body = v.body(llm_mode="select", model_name="chosen-other", connection_id="synthetic-current", selection_revision=catalog["selection_revision"])
    with pytest.raises(HTTPException): accept(v, body)
    with v.c.sessions() as db: assert not db.scalars(select(SourceRequestDB)).all()


def test_selected_catalog_connection_change_is_not_silently_rebound(version):
    v = version
    catalog = v.service.models("alice", v.c.parent, v.context["context_revision"])
    body = v.body(llm_mode="select", model_name="chosen-other", connection_id="synthetic-current", selection_revision=catalog["selection_revision"])
    v.current["server_url"] = "https://another.invalid"
    with pytest.raises(HTTPException) as error: accept(v, body)
    assert error.value.status_code == 409


def test_known_duplicate_after_source_and_global_changes_is_query_only(version, monkeypatch):
    v = version; body = v.body()
    first, _ = accept(v, body)
    v.c.original.unlink()
    monkeypatch.setattr(v.service, "_context", Mock(side_effect=AssertionError("no source/catalog replay")))
    again, background = accept(v, body)
    assert again.task_id == first.task_id and not background.tasks
    with pytest.raises(HTTPException): accept(v, body.model_copy(update={"presentation": "html"}))


def test_reserved_unknown_and_unbound_legacy_operation_never_requeue(version, monkeypatch):
    v = version; body = v.body()
    monkeypatch.setattr(v.c.artifacts, "create_task_dir", Mock(side_effect=RuntimeError("interrupted staging")))
    with pytest.raises(RuntimeError): accept(v, body)
    again, background = accept(v, body)
    assert again.state == "reserved" and not background.tasks
    with v.c.sessions() as db:
        row = db.get(SourceRequestDB, ("alice", str(body.operation_id)))
        row.receipt_json = "{}"  # Interrupted before adapter binding: GET recovery only.
    with pytest.raises(HTTPException): accept(v, body)


def test_concurrent_same_operation_queues_exactly_once(version):
    v = version; body = v.body()
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: accept(v, body), range(2)))
    assert results[0][0].task_id == results[1][0].task_id
    assert sum(len(background.tasks) for _, background in results) == 1


@pytest.mark.parametrize("damage", ["receipt", "stamp", "reference"])
def test_derived_parent_requires_original_accepted_receipt_and_source(version, damage):
    v = version
    receipt, background = accept(v)
    child = v.c.artifacts.find_task_dir(receipt.task_id)
    for task in background.tasks: task.func(*task.args, **task.kwargs)
    v.c.artifacts.update_status(child, "success", "synthetic complete")
    if damage == "receipt":
        with v.c.sessions() as db: db.get(SourceRequestDB, ("alice", receipt.operation_id)).fingerprint = "f" * 64
    elif damage == "stamp": (child / "summary_generation_started").unlink()
    else:
        reference = json.loads((child / "source_reference.json").read_text()); reference["owner"] = "other-owner"
        v.c.artifacts.write_json(child / "source_reference.json", reference)
    with pytest.raises(HTTPException): v.service.context("alice", receipt.task_id)


@pytest.mark.parametrize("damage", ["model", "connection", "digest_mismatch"])
def test_derived_parent_cannot_replace_db_bound_original_llm_or_origin(version, damage):
    v = version
    receipt, background = accept(v)
    for task in background.tasks: task.func(*task.args, **task.kwargs)
    child = v.c.artifacts.find_task_dir(receipt.task_id)
    v.c.artifacts.update_status(child, "success", "synthetic complete")
    snapshot = json.loads((child / SNAPSHOT_FILE).read_text())
    if damage == "model": snapshot["llm_model"] = "different-nonempty-model"
    elif damage == "connection": snapshot.update(server_url="https://current.invalid", connection_id="synthetic-current", connection_auth_mode="api_key")
    else:
        with v.c.sessions() as db:
            row = db.get(SourceRequestDB, ("alice", receipt.operation_id))
            meta = json.loads(row.receipt_json); meta["summary_snapshot_sha256"] = "f" * 64
            row.receipt_json = json.dumps(meta)
    v.c.artifacts.write_json(child / SNAPSHOT_FILE, snapshot)
    with pytest.raises(HTTPException) as error: v.service.context("alice", receipt.task_id)
    assert error.value.status_code == 409


def test_historical_missing_digest_keeps_reuse_but_requires_explicit_model_choice(version):
    v = version
    receipt, background = accept(v)
    for task in background.tasks: task.func(*task.args, **task.kwargs)
    child = v.c.artifacts.find_task_dir(receipt.task_id)
    v.c.artifacts.update_status(child, "success", "synthetic complete")
    with v.c.sessions() as db:
        row = db.get(SourceRequestDB, ("alice", receipt.operation_id))
        meta = json.loads(row.receipt_json); meta.pop("summary_snapshot_sha256")
        row.receipt_json = json.dumps(meta)
        old_receipt = row.receipt_json
    context = v.service.context("alice", receipt.task_id)
    assert context["asr_modes"]["reuse"]["available"] is True
    assert context["original_llm"]["verified"] is False and context["original_llm"]["reason"]
    body = MeetingVersionConfirmation(operation_id=uuid4(), confirmed=True,
        context_revision=context["context_revision"], source_version=context["source"]["version"])
    with pytest.raises(HTTPException) as error:
        v.service.accept("alice", receipt.task_id, body, BackgroundTasks(), v.c.note)
    assert error.value.detail["code"] == "meeting_version_inherit_unverified"
    catalog = v.service.models("alice", receipt.task_id, context["context_revision"])
    selected = body.model_copy(update={"llm_mode": "select", "model_name": "chosen-other",
        "connection_id": "synthetic-current", "selection_revision": catalog["selection_revision"]})
    new, background = v.service.accept("alice", receipt.task_id, selected, BackgroundTasks(), v.c.note), None
    assert new.state == "accepted" and new.task_id != receipt.task_id
    with v.c.sessions() as db:
        assert db.get(SourceRequestDB, ("alice", receipt.operation_id)).receipt_json == old_receipt
        assert json.loads(db.get(SourceRequestDB, ("alice", new.operation_id)).receipt_json)["summary_snapshot_sha256"]


@pytest.mark.parametrize("damage", [None, "origin", "parent_model", "parent_request", "modern_shape"])
def test_exact_historical_context_hash_can_prove_origin_without_trusting_child_disk(version, damage):
    from app.services.meeting_summary_regeneration import SummaryConfirmation, _digest, _submission
    from app.services.source_request_service import _fingerprint
    v = version
    receipt, background = accept(v)
    for task in background.tasks: task.func(*task.args, **task.kwargs)
    child = v.c.artifacts.find_task_dir(receipt.task_id)
    v.c.artifacts.update_status(child, "success", "synthetic complete")
    context, _, _, _, request = v.c.service._context("alice", v.c.parent)
    old = {key: context[key] for key in ("protocol", "parent_task_id", "canonical_task_id", "workflow",
        "source", "transcript_version", "requires_confirmation", "can_regenerate_summary")}
    revision = _digest({"owner": "alice", "context": old, "request": request, "snapshot": v.c.snapshot, "source_reference": None})
    link = {"contract": "meeting-summary-only-v1", "parent_task_id": v.c.parent, "operation_id": receipt.operation_id,
        "confirmed": True, "canonical_task_id": None, "context_revision": revision,
        "source_version": v.context["source"]["version"], "model_name": "old-model"}
    if damage == "modern_shape": link["presentation"] = None
    v.c.artifacts.write_json(child / "new_generation.json", link)
    with v.c.sessions() as db:
        row = db.get(SourceRequestDB, ("alice", receipt.operation_id))
        row.fingerprint = _fingerprint(_submission(v.c.parent, SummaryConfirmation(**{k: link[k] for k in SummaryConfirmation.model_fields if k in link})))
        meta = json.loads(row.receipt_json); meta.pop("summary_snapshot_sha256"); row.receipt_json = json.dumps(meta)
    snap = json.loads((child / SNAPSHOT_FILE).read_text())
    snap["asr_model"] = "unused-summary-asr-field"  # B's real legacy shape: no ASR authority is inherited.
    if damage == "origin": snap.update(server_url="https://current.invalid", connection_id="synthetic-current", connection_auth_mode="api_key")
    v.c.artifacts.write_json(child / SNAPSHOT_FILE, snap)
    if damage == "parent_model": v.c.artifacts.write_json(v.c.folder / SNAPSHOT_FILE, {**v.c.snapshot, "llm_model": "changed"})
    if damage == "parent_request": v.c.artifacts.write_json(v.c.folder / "request.json", {"request": {**request["request"], "title": "changed"}})
    result = v.service.context("alice", receipt.task_id)
    assert result["original_llm"]["verified"] is (damage is None)
    assert result["asr_modes"]["reuse"]["available"] is True


@pytest.mark.parametrize("mode", ["reuse", "fresh"])
def test_new_version_keeps_canonical_grouping_desktop_origin_and_owner(version, monkeypatch, mode):
    from datetime import datetime, timezone
    from app.models.note_library import NoteRecordResponse
    from app.routers import note_library
    v = version
    if mode == "reuse": receipt, _ = accept(v)
    else:
        from app.services.task_fresh_asr import FreshASRService
        v.service.fresh = FreshASRService(v.c.receipts)
        context = v.service.context("alice", v.c.parent)
        catalog = v.service.models("alice", v.c.parent, context["context_revision"])
        body = v.body(asr_mode="fresh", llm_mode="select", model_name="chosen-other", asr_model="explicit-asr",
            connection_id="synthetic-current", selection_revision=catalog["selection_revision"],
            fresh_context_revision=context["asr_modes"]["fresh"]["context_revision"], extra_asr_consent=True)
        receipt, _ = accept(v, body)
    child = v.c.artifacts.find_task_dir(receipt.task_id)
    assert (child / "generation_client").read_text() == "desktop"
    monkeypatch.setattr(note_library, "_artifact_service", v.c.artifacts)
    now = datetime.now(timezone.utc)
    note = NoteRecordResponse(id=str(uuid4()), title="Synthetic version", content="synthetic", task_id=receipt.task_id,
        source_type="meeting_recording", scope="personal", status="done", created_at=now, updated_at=now)
    projected = note_library._with_meeting_source(note, "alice")
    assert projected.meeting_source.owner_id == "alice"
    assert projected.meeting_source.canonical_task_id == v.c.parent
    assert note_library._with_meeting_source(note, "other-owner").meeting_source is None


def test_receipt_reservation_race_cannot_adopt_an_unbound_legacy_operation(version):
    from app.services.meeting_version_context import _VersionReceipts, _request_hash
    from app.services.meeting_summary_regeneration import SummaryConfirmation, _submission
    v = version; body = v.body()
    inner = SummaryConfirmation(operation_id=body.operation_id, confirmed=True,
        context_revision=v.c.context["context_revision"], source_version=body.source_version, model_name="old-model")
    submission = _submission(v.c.parent, inner)
    v.c.receipts.reserve("alice", str(body.operation_id), submission)
    wrapped = _VersionReceipts(v.c.receipts, v.c.parent, _request_hash(v.c.parent, body))
    with pytest.raises(HTTPException): wrapped.reserve("alice", str(body.operation_id), submission)
    with v.c.sessions() as db:
        assert "meeting_version" not in json.loads(db.get(SourceRequestDB, ("alice", str(body.operation_id))).receipt_json)


def test_receipt_tag_cas_preserves_concurrently_written_snapshot_digest(version):
    from contextlib import contextmanager
    from sqlalchemy import update
    from app.services.meeting_version_context import _VersionReceipts
    v = version; operation = str(uuid4())
    with v.c.sessions() as db:
        db.add(SourceRequestDB(owner="alice", operation_id=operation, task_id=str(uuid4()),
                               state="accepted", fingerprint="f" * 64, receipt_json="{}"))
    raced = False
    @contextmanager
    def sessions():
        with v.c.sessions() as db:
            def execute(statement, **kwargs):
                nonlocal raced
                if not raced:
                    raced = True
                    db.execute(update(SourceRequestDB).where(SourceRequestDB.operation_id == operation).values(
                        receipt_json=json.dumps({"summary_snapshot_sha256": "a" * 64})),
                        execution_options={"synchronize_session": False})
                return db.execute(statement, **kwargs)
            yield SimpleNamespace(get=db.get, execute=execute)
    receipt = _VersionReceipts(SimpleNamespace(sessions=sessions), v.c.parent, "b" * 64)
    receipt._bind("alice", operation, allow_missing=True)
    with v.c.sessions() as db:
        meta = json.loads(db.get(SourceRequestDB, ("alice", operation)).receipt_json)
        assert meta["summary_snapshot_sha256"] == "a" * 64 and meta["meeting_version"] == receipt.tag


def test_matching_receipt_tag_is_readonly_and_preserves_db_digest(version):
    from contextlib import contextmanager
    from app.services.meeting_version_context import _VersionReceipts
    v = version; operation = str(uuid4())
    tag = {"protocol": 1, "parent": v.c.parent, "request_sha256": "b" * 64}
    with v.c.sessions() as db:
        db.add(SourceRequestDB(owner="alice", operation_id=operation, task_id=str(uuid4()), state="accepted",
            fingerprint="f" * 64, receipt_json=json.dumps({"meeting_version": tag, "summary_snapshot_sha256": "a" * 64})))
    @contextmanager
    def sessions():
        with v.c.sessions() as db:
            yield SimpleNamespace(get=db.get, execute=Mock(side_effect=AssertionError("no UPDATE for existing matching tag")))
    _VersionReceipts(SimpleNamespace(sessions=sessions), v.c.parent, "b" * 64)._bind("alice", operation)


def test_injected_fresh_source_failure_does_not_block_valid_reuse(version):
    v = version
    v.service.fresh = SimpleNamespace(context=Mock(side_effect=HTTPException(409, "unavailable")))
    context = v.service.context("alice", v.c.parent)
    assert context["asr_modes"]["reuse"]["available"] is True
    assert context["asr_modes"]["fresh"]["available"] is False and v.calls == []


def test_real_fresh_adapter_acceptance_has_explicit_models_and_exact_receipt_recovery(version):
    from app.services.task_fresh_asr import FreshASRService
    v = version; fresh = FreshASRService(v.c.receipts); fresh.artifacts = v.c.artifacts
    v.service.fresh = fresh
    context = v.service.context("alice", v.c.parent)
    assert context["asr_modes"]["fresh"]["available"] is True and v.calls == []
    catalog = v.service.models("alice", v.c.parent, context["context_revision"])
    body = v.body(asr_mode="fresh", llm_mode="select", model_name="chosen-other", asr_model="explicit-asr",
        connection_id="synthetic-current", selection_revision=catalog["selection_revision"],
        fresh_context_revision=context["asr_modes"]["fresh"]["context_revision"], extra_asr_consent=True)
    receipt, background = accept(v, body)
    assert len(background.tasks) == 1 and receipt.task_id != v.c.parent
    child = v.c.artifacts.find_task_dir(receipt.task_id)
    snapshot = json.loads((child / SNAPSHOT_FILE).read_text())
    assert snapshot["asr_model"] == "explicit-asr" and snapshot["llm_model"] == "chosen-other"
    assert snapshot["needs_stt"] is True and not (child / "transcription_chunks").exists()
    calls = list(v.calls)
    again, pending = accept(v, body)
    assert again.task_id == receipt.task_id and not pending.tasks and v.calls == calls


def test_failed_parent_without_asr_can_offer_fresh_but_never_auto_select_it(version):
    from app.services.task_fresh_asr import FreshASRService
    v = version; v.service.fresh = FreshASRService(v.c.receipts)
    (v.c.folder / "transcript.json").unlink()
    context = v.service.context("alice", v.c.parent)
    assert context["default_asr_mode"] == "reuse"
    assert not context["asr_modes"]["reuse"]["available"] and context["asr_modes"]["fresh"]["available"]
    assert context["original_llm"]["model_name"] == "old-model" and v.calls == []
    body = v.body().model_copy(update={"context_revision": context["context_revision"]})
    with pytest.raises(HTTPException) as error: accept(v, body)
    assert error.value.detail["code"] == "meeting_version_reuse_unavailable"


def test_fresh_without_integration_cannot_reserve_or_dispatch(version):
    v = version
    body = v.body(asr_mode="fresh", llm_mode="select", model_name="chosen-other", asr_model="real-asr",
        selection_revision="a" * 64, fresh_context_revision="b" * 64, extra_asr_consent=True)
    with pytest.raises(HTTPException) as error: accept(v, body)
    assert error.value.detail["code"] == "meeting_version_fresh_unavailable"
    assert v.calls == []
    with v.c.sessions() as db: assert not db.scalars(select(SourceRequestDB)).all()


def test_router_auth_no_store_strict_confirmation_and_single_task(version):
    from app.routers.meeting_version_context import create_meeting_version_router
    from app.services.auth_service import get_current_user
    v = version; app = FastAPI()
    app.include_router(create_meeting_version_router(v.service, get_current_user, v.c.note), prefix="/api")
    client = TestClient(app)
    base = "/api/task/" + v.c.parent
    assert client.get(base + "/meeting-version-context").status_code == 401
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(user_id="alice")
    response = client.get(base + "/meeting-version-context")
    assert response.status_code == 200 and response.headers["cache-control"] == "private, no-store"
    body = v.body().model_dump(mode="json")
    for confirmed in [False, 1, "true"]:
        assert client.post(base + "/meeting-versions", json={**body, "confirmed": confirmed}).status_code == 422
    for extra in [{"server_url": "https://evil.invalid"}, {"asr_mode": "fresh"}, {"model_name": "global-llm"}]:
        assert client.post(base + "/meeting-versions", json={**body, **extra}).status_code == 422
    first = client.post(base + "/meeting-versions", json=body)
    assert first.status_code == 200 and first.json()["task_id"] != v.c.parent
    assert client.post(base + "/meeting-versions", json=body).json()["task_id"] == first.json()["task_id"]
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(user_id="other")
    assert client.get(base + "/meeting-version-context").status_code == 404
