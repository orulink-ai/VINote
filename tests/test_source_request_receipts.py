from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from threading import Barrier

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.db_models import SourceRequestDB
from app.models.source_request import SourceInput, SourceSubmission
from app.services.source_request_service import SourceRequestService, create_receipt_router


@pytest.fixture
def service(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'receipts.db'}",
                           connect_args={"check_same_thread": False, "timeout": 10})
    SourceRequestDB.__table__.create(engine)

    @contextmanager
    def sessions():
        with Session(engine, expire_on_commit=False) as db:
            with db.begin():
                yield db

    yield SourceRequestService(sessions), sessions
    engine.dispose()


def submission(**options):
    return SourceSubmission(source=SourceInput(kind="url", url="https://python.org/about"),
                            options={"summary_mode": "default", **options})


def test_response_loss_reuses_durable_task_after_service_restart(service):
    first, sessions = service
    receipt = first.reserve("alice", "operation-1", submission())
    first.accept("alice", "operation-1", receipt.task_id, status="preparing", source_type="file")
    restarted = SourceRequestService(sessions)
    replay = restarted.reserve("alice", "operation-1", submission())
    assert receipt.created and not replay.created
    assert replay.task_id == receipt.task_id
    assert replay.state == "accepted" and replay.status == "preparing"


def test_reserved_after_interruption_is_queryable_but_never_claimed_again(service):
    svc, _ = service
    first = svc.reserve("alice", "operation-1", submission())
    assert svc.get("alice", "operation-1").state == "reserved"
    assert not svc.reserve("alice", "operation-1", submission()).created
    assert svc.get("alice", "operation-1").task_id == first.task_id


@pytest.mark.parametrize("changed", [
    submission(output_language="zh-CN"),
    submission(model_profile_id="different-model"),
    SourceSubmission(source=SourceInput(kind="url", url="https://python.org/another")),
])
def test_operation_cannot_be_reused_for_different_input(service, changed):
    svc, _ = service
    first = svc.reserve("alice", "operation-1", submission())
    with pytest.raises(HTTPException) as error:
        svc.reserve("alice", "operation-1", changed)
    assert error.value.status_code == 409
    assert error.value.detail["code"] == "SOURCE_OPERATION_REUSED"
    assert svc.get("alice", "operation-1").task_id == first.task_id


def test_concurrent_identical_requests_have_one_dispatch_winner(service):
    svc, sessions = service
    barrier = Barrier(8)

    def reserve(_):
        barrier.wait()
        return SourceRequestService(sessions).reserve("alice", "operation-1", submission())

    with ThreadPoolExecutor(max_workers=8) as pool:
        receipts = list(pool.map(reserve, range(8)))
    assert len({row.task_id for row in receipts}) == 1
    assert sum(row.created for row in receipts) == 1


def test_competing_input_cannot_win_same_operation_twice(service):
    svc, sessions = service
    barrier = Barrier(2)

    def reserve(language):
        barrier.wait()
        try:
            return SourceRequestService(sessions).reserve("alice", "operation-1", submission(output_language=language))
        except HTTPException as error:
            return error.status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(reserve, ["en", "zh-CN"]))
    assert sum(result == 409 for result in results) == 1
    assert sum(getattr(result, "created", False) for result in results) == 1


def test_owner_isolation_and_unavailable_receipt(service):
    svc, _ = service
    first = svc.reserve("alice", "same-operation", submission())
    second = svc.reserve("bob", "same-operation", submission())
    assert first.task_id != second.task_id
    with pytest.raises(HTTPException) as error:
        svc.get("bob", "alice-only")
    assert error.value.status_code == 404
    svc.reserve("alice", "alice-only", submission())
    with pytest.raises(HTTPException) as error:
        svc.get("bob", "alice-only")
    assert error.value.status_code == 404


@pytest.mark.parametrize("field,value", [
    ("file_type", "docx"), ("size", 11), ("sha256", "b" * 64), ("filename", "other.pdf"),
])
def test_uploaded_original_identity_participates_in_fingerprint(service, field, value):
    svc, _ = service
    data = dict(kind="upload", file_type="pdf", size=10, sha256="a" * 64, filename="sample.pdf")
    svc.reserve("alice", "operation-1", SourceSubmission(source=SourceInput(**data)))
    with pytest.raises(HTTPException) as error:
        svc.reserve("alice", "operation-1", SourceSubmission(source=SourceInput(**{**data, field: value})))
    assert error.value.status_code == 409


@pytest.mark.parametrize("field,value", [("retained_file_id", "another"), ("retained_file_version", "revision-2")])
def test_retained_original_id_and_version_participate(service, field, value):
    svc, _ = service
    data = dict(kind="retained_file", retained_file_id="file-1", retained_file_version="revision-1")
    svc.reserve("alice", "operation-1", SourceSubmission(source=SourceInput(**data)))
    with pytest.raises(HTTPException) as error:
        svc.reserve("alice", "operation-1", SourceSubmission(source=SourceInput(**{**data, field: value})))
    assert error.value.status_code == 409


def test_missing_upload_digest_or_retained_version_is_rejected():
    with pytest.raises(ValidationError):
        SourceInput(kind="upload", file_type="pdf", size=10)
    with pytest.raises(ValidationError):
        SourceInput(kind="retained_file", retained_file_id="file-1")


def test_canonical_options_do_not_depend_on_object_key_order(service):
    svc, _ = service
    one = submission(metadata={"title": "计划", "tags": ["a", "b"]})
    two = submission(metadata={"tags": ["a", "b"], "title": "计划"})
    assert svc.reserve("alice", "operation-1", one).task_id == svc.reserve("alice", "operation-1", two).task_id


def test_accept_requires_bound_task_and_cannot_replace_saved_receipt(service):
    svc, _ = service
    first = svc.reserve("alice", "operation-1", submission())
    with pytest.raises(HTTPException) as error:
        svc.accept("alice", "operation-1", "another-task", status="pending")
    assert error.value.status_code == 409
    svc.accept("alice", "operation-1", first.task_id, status="preparing")
    assert svc.accept("alice", "operation-1", first.task_id, status="other").status == "preparing"


def test_receipt_does_not_store_source_url_or_options(service):
    svc, sessions = service
    svc.reserve("alice", "operation-1", submission(extras="PRIVATE SOURCE TEXT"))
    with sessions() as db:
        row = db.scalar(select(SourceRequestDB))
        assert len(row.fingerprint) == 64
        assert "PRIVATE" not in row.receipt_json and "python.org" not in row.receipt_json


def test_get_endpoint_uses_verified_owner_and_has_no_side_effects(service):
    svc, _ = service
    saved = svc.reserve("alice", "operation-1", submission())
    app = FastAPI()
    app.include_router(create_receipt_router(svc, lambda: "alice"), prefix="/api")
    with TestClient(app) as client:
        response = client.get("/api/source-requests/operation-1?owner=bob")
        assert response.status_code == 200
        assert response.json()["task_id"] == saved.task_id
        assert response.json()["state"] == "reserved"
        assert client.get("/api/source-requests/missing").status_code == 404
    assert not svc.reserve("alice", "operation-1", submission()).created


def test_failed_commit_cannot_grant_dispatch_permission(service):
    svc, sessions = service

    @contextmanager
    def failed_commit():
        with sessions() as db:
            yield db
            raise RuntimeError("durable save failed")

    with pytest.raises(RuntimeError, match="durable save failed"):
        SourceRequestService(failed_commit).reserve("alice", "operation-1", submission())
    with pytest.raises(HTTPException) as error:
        svc.get("alice", "operation-1")
    assert error.value.status_code == 404


def test_concurrent_accept_preserves_first_durable_receipt(service):
    svc, sessions = service
    task_id = svc.reserve("alice", "operation-1", submission()).task_id
    barrier = Barrier(2)

    def accept(status):
        barrier.wait()
        return SourceRequestService(sessions).accept("alice", "operation-1", task_id, status=status)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(accept, ["pending", "preparing"]))
    assert results[0].status == results[1].status == svc.get("alice", "operation-1").status


def test_receipt_get_requires_authentication(service):
    svc, _ = service

    def unauthenticated():
        raise HTTPException(401, "login required")

    app = FastAPI()
    app.include_router(create_receipt_router(svc, unauthenticated), prefix="/api")
    with TestClient(app) as client:
        assert client.get("/api/source-requests/operation-1").status_code == 401


@pytest.mark.parametrize("owner,operation", [("", "ok"), ("alice", ""), ("alice", "bad/id"), ("alice", "x" * 161)])
def test_invalid_identity_is_rejected(service, owner, operation):
    svc, _ = service
    with pytest.raises(HTTPException):
        svc.reserve(owner, operation, submission())
