from contextlib import contextmanager
from io import BytesIO

import pytest
from fastapi import HTTPException
from PIL import Image
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db import Base


@pytest.fixture
def attachments(tmp_path, monkeypatch):
    from app.services import workspace_attachment_service as module
    engine = create_engine(f"sqlite:///{tmp_path / 'attachments.db'}")
    Base.metadata.create_all(engine)

    @contextmanager
    def sessions():
        with Session(engine) as db, db.begin():
            yield db

    monkeypatch.setattr(module, "session_scope", sessions)
    monkeypatch.setattr(module.settings, "data_dir", tmp_path)
    monkeypatch.setattr(module.settings, "workspace_cloud_runtime", False)
    monkeypatch.setattr(module.settings, "workspace_storage_key", "")
    yield module.WorkspaceAttachmentService()
    engine.dispose()


def image_bytes():
    output = BytesIO()
    Image.new("RGB", (8, 8), "white").save(output, "PNG")
    return output.getvalue()


def test_retries_reuse_private_attachment_without_cross_account_access(attachments):
    a = attachments.upload("alice", image_bytes())
    b = attachments.upload("alice", image_bytes())
    assert a["id"] == b["id"]
    assert a["reference"] == "attachment://" + a["id"]
    assert attachments.read("alice", a["id"])[0] == image_bytes()
    with pytest.raises(HTTPException) as hidden:
        attachments.read("bob", a["id"])
    assert hidden.value.status_code == 404


def test_only_actual_bounded_images_are_accepted(attachments):
    for data in (b"video", b"<svg><script/></svg>", b"", b"a" * (5 * 1024 * 1024 + 1)):
        with pytest.raises(HTTPException):
            attachments.upload("alice", data)


def test_shared_text_cannot_reference_another_accounts_attachment(attachments):
    a = attachments.upload("alice", image_bytes())
    attachments.validate_references("alice", [f'![截图]({a["reference"]})'])
    with pytest.raises(HTTPException) as hidden:
        attachments.validate_references("bob", [f'![截图]({a["reference"]})'])
    assert hidden.value.status_code == 422


def test_cloud_mode_never_falls_back_to_local_files(attachments, monkeypatch):
    from app.services.workspace_attachment_service import settings
    monkeypatch.setattr(settings, "workspace_cloud_runtime", True)
    with pytest.raises(HTTPException) as missing:
        attachments.upload("alice", image_bytes())
    assert missing.value.status_code == 503


def test_cloud_images_use_private_bucket_and_signed_owner_path(attachments, monkeypatch):
    import httpx
    from app.services import workspace_attachment_service as module
    monkeypatch.setattr(module.settings, 'workspace_storage_url', 'https://storage.test')
    monkeypatch.setattr(module.settings, 'workspace_storage_key', 'fixture-only')
    requests = []

    def respond(request):
        requests.append(request)
        if '/bucket/' in request.url.path:
            return httpx.Response(200, json={'public': False})
        if '/object/sign/' in request.url.path:
            return httpx.Response(200, json={'signedURL': request.url.path.replace('/storage/v1', '') + '?token=fixture'})
        return httpx.Response(200, json={'Key': 'stored'})

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        monkeypatch.setattr(module.httpx, 'stream', client.stream)
        item = attachments.upload('alice', image_bytes())
        access = attachments.access('alice', item['id'])
        assert access['expires_in'] == 300 and not access['authenticated']
        assert access['url'].startswith('https://storage.test/storage/v1/object/sign/vinote-content/')
        assert requests[1].method == 'POST'
        assert requests[1].content == image_bytes()
        count = len(requests)
        with pytest.raises(HTTPException):
            attachments.access('bob', item['id'])
        assert len(requests) == count  # Reject before asking storage for a URL.


def test_public_bucket_or_failed_upload_does_not_acknowledge_attachment(attachments, monkeypatch):
    import httpx
    from app.services import workspace_attachment_service as module
    monkeypatch.setattr(module.settings, 'workspace_storage_url', 'https://storage.test')
    monkeypatch.setattr(module.settings, 'workspace_storage_key', 'fixture-only')
    identifier = __import__('hashlib').sha256(image_bytes()).hexdigest()
    for public in (True, False):
        def respond(request):
            return httpx.Response(200, json={'public': public}) if '/bucket/' in request.url.path else httpx.Response(503)
        with httpx.Client(transport=httpx.MockTransport(respond)) as client:
            monkeypatch.setattr(module.httpx, 'stream', client.stream)
            with pytest.raises(HTTPException):
                attachments.upload('alice', image_bytes())
            with pytest.raises(HTTPException) as missing:
                attachments.access('alice', identifier)
            assert missing.value.status_code == 404
