from contextlib import contextmanager

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db import Base
from app.models.workspace import Operation, PutNote
from app.routers.workspace import SelectedImport, import_local
from app.services import workspace_service as module
from app.services.workspace_migration_service import import_local_workspace


@pytest.fixture
def service(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'receipt.db'}")
    Base.metadata.create_all(engine)

    @contextmanager
    def sessions():
        with Session(engine) as db, db.begin():
            yield db

    monkeypatch.setattr(module, "session_scope", sessions)
    yield module.WorkspaceService()
    engine.dispose()


def test_exact_receipt_is_original_revision_not_newest_content(service):
    service.put("owner", "stable", PutNote(base_revision=0, operation_id="first", title="A", content="A"))
    service.put("owner", "stable", PutNote(base_revision=1, operation_id="second", title="B", content="B"))
    assert service.operation("owner", "first", "stable") == {
        "operation_id": "first", "note_key": "stable", "acknowledged_revision": 1, "status": "acknowledged"}
    assert service.get("owner", "stable")["revision"] == 2
    for owner, operation, key in [("other", "first", "stable"), ("owner", "first", "other"), ("owner", "missing", "stable")]:
        with pytest.raises(HTTPException) as error:
            service.operation(owner, operation, key)
        assert error.value.status_code == 404


def test_deleted_receipt_survives_restore_and_operation_cannot_change_input(service):
    service.put("owner", "stable", PutNote(base_revision=0, operation_id="first", title="A", content="A"))
    service.set_deleted("owner", "stable", Operation(base_revision=1, operation_id="delete"), True)
    service.set_deleted("owner", "stable", Operation(base_revision=2, operation_id="restore"), False)
    assert service.operation("owner", "delete", "stable")["acknowledged_revision"] == 2
    with pytest.raises(HTTPException) as error:
        service.put("owner", "stable", PutNote(base_revision=3, operation_id="first", title="changed", content="changed"))
    assert error.value.status_code == 409
    assert service.get("owner", "stable")["revision"] == 3


def test_bulk_import_requires_explicit_nonempty_selection_and_authorization():
    for values in [{}, {"keys": [], "sync_authorized": True}]:
        with pytest.raises(ValidationError):
            SelectedImport(**values)
    with pytest.raises(HTTPException) as error:
        import_local(SelectedImport(keys=["stable"], sync_authorized=False), ("owner", "cookie"))
    assert error.value.status_code == 409
    with pytest.raises(HTTPException) as error:
        import_local_workspace(("owner", "cookie"))
    assert error.value.status_code == 422
