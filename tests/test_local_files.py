from contextlib import contextmanager
from io import BytesIO
from types import SimpleNamespace
from zipfile import ZipFile

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db import Base
from app.services import local_file_service as module


def test_existing_local_files_gain_purpose_without_losing_originals(tmp_path, monkeypatch):
    from app import db as database
    from sqlalchemy import inspect, text

    legacy = create_engine(f"sqlite:///{tmp_path / 'legacy.db'}")
    with legacy.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE local_files (id VARCHAR(36) PRIMARY KEY, owner VARCHAR(128), filename VARCHAR(250), category VARCHAR(16), path TEXT, size_bytes INTEGER, task_id VARCHAR(160), created_at TIMESTAMP)")
        connection.exec_driver_sql("INSERT INTO local_files (id, owner, filename, category, path, size_bytes, task_id) VALUES ('source-1', 'alice', 'meeting.m4a', 'recording', 'untouched.m4a', 42, '')")
    monkeypatch.setattr(database, 'engine', legacy)
    database._ensure_local_file_purpose_column()
    assert 'purpose' in {column['name'] for column in inspect(legacy).get_columns('local_files')}
    with legacy.connect() as connection:
        assert connection.execute(text("SELECT filename, path, size_bytes, purpose FROM local_files WHERE id='source-1'")).one() == ('meeting.m4a', 'untouched.m4a', 42, 'unassigned')
    legacy.dispose()


@pytest.fixture
def files(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'files.db'}")
    Base.metadata.create_all(engine)

    @contextmanager
    def sessions():
        with Session(engine) as db, db.begin():
            yield db

    monkeypatch.setattr(module, "session_scope", sessions)
    monkeypatch.setattr(module.settings, "data_dir", tmp_path)
    monkeypatch.setattr(module.settings, "output_dir", tmp_path / 'output')
    yield module.LocalFileService()
    engine.dispose()


def saved(files, owner='alice'):
    identifier, name, target = files.new_target(owner, 'notes.md')
    target.write_bytes(b'# Notes')
    return files.register(owner, identifier, name, target)


def test_import_retains_original_without_starting_generation_and_isolates_owners(files):
    item = saved(files)
    assert not item['task_id']
    assert files.list('alice')['items'][0]['id'] == item['id']
    assert files.list('bob')['items'] == []
    assert files.list('alice')['originals_sync'] is False
    for action in (files.get, files.delete):
        with pytest.raises(HTTPException) as denied:
            action('bob', item['id'])
        assert denied.value.status_code == 404


def test_file_purpose_is_owned_and_separate_from_format(files):
    identifier, name, target = files.new_target('alice', 'discussion.mp4')
    target.write_bytes(b'video bytes')
    item = files.register('alice', identifier, name, target, 'note')
    assert item['category'] == 'video'
    assert item['purpose'] == 'note'
    assert files.list('alice')['items'][0]['purpose'] == 'note'
    with pytest.raises(HTTPException) as denied:
        files.set_purpose('bob', identifier, 'meeting')
    assert denied.value.status_code == 404
    assert files.set_purpose('alice', identifier, 'meeting')['purpose'] == 'meeting'
    assert files.get('alice', identifier)[0]['purpose'] == 'meeting'
    with pytest.raises(HTTPException) as invalid:
        files.set_purpose('alice', identifier, 'other')
    assert invalid.value.status_code == 422


def test_generation_intent_classifies_legacy_source(files):
    item = saved(files)
    assert item['purpose'] == 'unknown'
    files.attach_task('alice', item['id'], 'meeting-task', 'meeting')
    assert files.get('alice', item['id'])[0]['purpose'] == 'meeting'


def test_submission_lease_prevents_duplicate_pipeline_and_deletion(files):
    item = saved(files)
    with files.generation_lease('alice', item['id']):
        with pytest.raises(HTTPException) as duplicate:
            with files.generation_lease('alice', item['id']):
                pytest.fail('duplicate submission entered')
        assert duplicate.value.status_code == 409
        with pytest.raises(HTTPException) as busy:
            files.delete('alice', item['id'])
        assert busy.value.status_code == 409
    assert files.get('alice', item['id'])[0]['available']


def test_deletion_can_recover_after_file_was_removed_before_index_commit(files):
    item = saved(files)
    files.get('alice', item['id'])[1].unlink()
    files.delete('alice', item['id'])
    assert files.list('alice')['items'] == []


def test_owned_index_cannot_delete_another_accounts_path(files):
    alice, bob = saved(files), saved(files, 'bob')
    from app.models.local_file import LocalFileDB
    bob_path = files.get('bob', bob['id'])[1]
    with module.session_scope() as db:
        db.get(LocalFileDB, alice['id']).path = str(bob_path)
    with pytest.raises(HTTPException):
        files.delete('alice', alice['id'])
    assert bob_path.exists()


def test_note_deletion_preserves_verified_original_in_independent_library(files, tmp_path, monkeypatch):
    from app.db_models import NoteDB
    from app.services import note_repository
    from app.services.task_artifact_service import TaskArtifactService
    monkeypatch.setattr(note_repository, 'session_scope', module.session_scope)
    artifacts = TaskArtifactService(module.settings.output_dir)
    folder = artifacts.create_task_dir('retained-task')
    artifacts.update_status(folder, 'success', 'Complete')
    original = tmp_path / 'original.m4a'
    original.write_bytes(b'original audio bytes')
    source = artifacts.stage_source_media(folder, str(original), media_kind='audio')
    (folder / 'recording_owner').write_text('alice', encoding='utf-8')
    with module.session_scope() as db:
        db.add(NoteDB(id='retained-note', created_by='alice', title='Meeting', task_id='retained-task',
                      content='Summary', source_type='meeting_recording'))
    assert note_repository.NoteRepository().delete_note('alice', 'retained-note')
    rows = files.list('alice')['items']
    assert len(rows) == 1 and 'note_id' not in rows[0]
    assert files.get('alice', rows[0]['id'])[1].read_bytes() == original.read_bytes()
    assert source.read_bytes() == original.read_bytes()
    assert files.list('bob')['items'] == []


def test_unverified_task_media_is_not_granted_new_file_access(files, tmp_path):
    from app.services.task_artifact_service import TaskArtifactService
    artifacts = TaskArtifactService(module.settings.output_dir)
    folder = artifacts.create_task_dir('foreign-task')
    artifacts.update_status(folder, 'success', 'Complete')
    original = tmp_path / 'foreign.m4a'
    original.write_bytes(b'foreign audio')
    source = artifacts.stage_source_media(folder, str(original), media_kind='audio')
    (folder / 'recording_owner').write_text('bob', encoding='utf-8')
    assert files.retain_note_original('alice', SimpleNamespace(created_by='alice', task_id='foreign-task')) is None
    assert files.list('alice')['items'] == []
    assert source.exists()


def test_cloud_service_does_not_expose_original_upload_or_local_auth(monkeypatch):
    from app import create_app
    from app.config import settings
    monkeypatch.setattr(settings, 'workspace_cloud_runtime', True)
    paths = {route.path for route in create_app().routes}
    assert '/api/workspace/attachments' in paths
    assert '/api/workspace/status' in paths
    assert '/api/files' not in paths
    assert '/api/generate_from_upload' not in paths
    assert '/api/auth/sign-in' not in paths


def document_bytes(extension):
    output = BytesIO()
    if extension == 'docx':
        with ZipFile(output, 'w') as archive:
            archive.writestr('word/document.xml',
                '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                '<w:body><w:p><w:r><w:t>Retain the original and retry the same task.</w:t>'
                '</w:r></w:p></w:body></w:document>')
    else:
        from pypdf import PdfWriter
        from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject
        writer = PdfWriter()
        page = writer.add_blank_page(width=300, height=200)
        font = DictionaryObject({NameObject('/Type'): NameObject('/Font'),
                                 NameObject('/Subtype'): NameObject('/Type1'),
                                 NameObject('/BaseFont'): NameObject('/Helvetica')})
        page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'): DictionaryObject({
            NameObject('/F1'): writer._add_object(font)})})
        stream = DecodedStreamObject()
        stream.set_data(b'BT /F1 12 Tf 20 100 Td (Retain the original and retry the same task.) Tj ET')
        page[NameObject('/Contents')] = writer._add_object(stream)
        writer.write(output)
    return output.getvalue()


@pytest.fixture
def file_api(files, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.models.auth import AuthenticatedUser
    from app.routers import files as file_routes, note as note_routes
    from app.services.task_artifact_service import TaskArtifactService

    artifacts = TaskArtifactService(module.settings.output_dir)
    monkeypatch.setattr(file_routes, 'service', files)
    monkeypatch.setattr(note_routes, '_note_service', SimpleNamespace(artifact_service=artifacts))
    # Original-file API tests must not resolve real account model profiles.
    monkeypatch.setattr(note_routes, 'ensure_source', lambda *args, **kwargs: {})
    calls = []

    def worker(task_id, job, owner):
        calls.append((task_id, job, owner))
        folder = artifacts.find_task_dir(task_id)
        artifacts.update_status(folder, 'failed' if len(calls) == 1 else 'success',
                                'Synthetic local worker result', retryable=True)
        note_routes._ACTIVE_FILE_TASKS.discard(task_id)

    monkeypatch.setattr(note_routes, '_run_source_job', worker)
    app = FastAPI()
    app.include_router(file_routes.router, prefix='/api')
    app.include_router(note_routes.router, prefix='/api')
    app.dependency_overrides[file_routes.get_current_user] = lambda: AuthenticatedUser('alice')
    app.dependency_overrides[note_routes.get_optional_current_user] = lambda: AuthenticatedUser('alice')
    app.dependency_overrides[note_routes.get_current_user] = lambda: AuthenticatedUser('alice')
    with TestClient(app) as client:
        yield client, artifacts, calls


def test_file_api_keeps_note_video_separate_from_meeting_video(file_api):
    client, _, _ = file_api
    note_video = client.post('/api/files', data={'purpose': 'note'}, files={'file': ('source.mp4', b'video')})
    assert note_video.status_code == 200
    identifier = note_video.json()['id']
    assert note_video.json()['purpose'] == 'note'
    assert client.get('/api/files').json()['items'][0]['purpose'] == 'note'
    moved = client.patch(f'/api/files/{identifier}', json={'purpose': 'meeting'})
    assert moved.status_code == 200
    assert moved.json()['purpose'] == 'meeting'


@pytest.mark.parametrize('extension', ['pdf', 'docx'])
@pytest.mark.parametrize('entry', ['upload', 'library'])
def test_document_original_generation_retry_link_and_independent_deletion(files, file_api, extension, entry):
    import json
    from app.db_models import NoteDB
    client, artifacts, calls = file_api
    name, data = f'original.{extension}', document_bytes(extension)
    registered = client.post('/api/files', files={'file': (name, data)}).json()
    identifier = registered['id']
    assert registered['can_generate'] and not registered['task_id']

    def generate():
        if entry == 'library':
            return client.post(f'/api/files/{identifier}/generate', json={'meeting': False})
        # The registered original is authoritative, not this different upload.
        return client.post('/api/generate_from_upload',
            data={'source_type': 'document', 'local_file_id': identifier},
            files={'file': ('different.docx', b'invalid replacement')})

    first = generate()
    assert first.status_code == 200, first.text
    task_id = first.json()['task_id']
    assert first.json()['source_type'] == 'file'
    assert files.get('alice', identifier)[0]['task_id'] == task_id
    folder = artifacts.find_task_dir(task_id)
    checkpoint = json.loads((folder / 'document_text.json').read_text(encoding='utf-8'))
    assert 'Retain the original' in checkpoint['text']
    assert (folder / 'recording_owner').read_text(encoding='utf-8') == 'alice'

    # The failed task leaves the exact original available for export.
    exported = client.get(f'/api/files/{identifier}/content?download=true')
    assert exported.status_code == 200 and exported.content == data
    assert 'attachment' in exported.headers['content-disposition']
    retry = generate()
    assert retry.status_code == 200, retry.text
    assert retry.json()['task_id'] == task_id and retry.json()['source_type'] == 'file'
    assert [call[0] for call in calls] == [task_id, task_id]

    # Success and in-flight status reuse the receipt without another worker.
    for status in ('preparing', 'success'):
        artifacts.update_status(folder, status, 'Synthetic status')
        reused = generate()
        assert reused.json()['task_id'] == task_id
        assert reused.json()['source_type'] == 'file'
        assert len(calls) == 2

    with module.session_scope() as db:
        db.add(NoteDB(id='saved-note', created_by='alice', title='Summary',
                      content='Saved text remains', task_id=task_id, source_type='file'))
    listing = client.get('/api/files').json()['items']
    assert len(listing) == 1 and listing[0]['note_id'] == 'saved-note'
    assert client.delete(f'/api/files/{identifier}').json()['notes_preserved'] is True
    assert client.get('/api/files').json()['items'] == []
    with module.session_scope() as db:
        assert db.get(NoteDB, 'saved-note').content == 'Saved text remains'
    assert (folder / 'document_text.json').exists()


def test_registered_document_id_requires_owner_and_document_type(files, file_api):
    client, _, calls = file_api
    foreign = saved(files, 'bob')
    own_text = saved(files)
    for item, expected in ((foreign, 404), (own_text, 422)):
        response = client.post('/api/generate_from_upload',
            data={'source_type': 'document', 'local_file_id': item['id']},
            files={'file': ('decoy.docx', document_bytes('docx'))})
        assert response.status_code == expected, response.text
    assert client.post(f"/api/files/{foreign['id']}/generate", json={}).status_code == 404
    assert calls == []


def test_invalid_document_retains_exportable_original_without_task(files, file_api):
    client, _, calls = file_api
    registered = client.post('/api/files', files={'file': ('broken.docx', b'broken document')}).json()
    identifier = registered['id']
    result = client.post(f'/api/files/{identifier}/generate', json={})
    assert result.status_code == 400 and '损坏' in result.text
    assert not files.get('alice', identifier)[0]['task_id']
    assert client.get(f'/api/files/{identifier}/content?download=true').content == b'broken document'
    assert calls == []


def test_document_upload_without_registered_id_remains_compatible(file_api):
    client, _, calls = file_api
    result = client.post('/api/generate_from_upload', data={'source_type': 'document'},
                         files={'file': ('legacy.docx', document_bytes('docx'))})
    assert result.status_code == 200, result.text
    assert result.json()['source_type'] == 'file' and len(calls) == 1


@pytest.fixture
def source_receipts(files, monkeypatch):
    from app.routers import note as routes
    from app.services.source_request_service import SourceRequestService
    monkeypatch.setattr(routes, '_source_requests', SourceRequestService(module.session_scope))


def test_operation_receipt_upload_replay_query_and_conflicting_bytes(file_api, source_receipts):
    client, _, calls = file_api
    options = {'source_type': 'document'}
    headers = {'X-VINote-Operation-Id': 'upload-once'}
    data = document_bytes('docx')
    first = client.post('/api/generate_from_upload', headers=headers, data=options,
                        files={'file': ('source.docx', data)})
    assert first.status_code == 200, first.text
    replay = client.post('/api/generate_from_upload', headers=headers, data=options,
                         files={'file': ('source.docx', data)})
    assert replay.json()['task_id'] == first.json()['task_id']
    assert len(calls) == 1  # Failed background generation is not implicitly retried.
    receipt = client.get('/api/source-requests/upload-once')
    assert receipt.status_code == 200 and receipt.json()['state'] == 'accepted'
    assert receipt.headers['cache-control'] == 'no-store'
    conflict = client.post('/api/generate_from_upload', headers=headers,
                           data={**options, 'title': 'Changed title'},
                           files={'file': ('source.docx', data)})
    assert conflict.status_code == 409
    assert len(calls) == 1


def test_operation_receipt_registered_original_retains_existing_task(files, file_api, source_receipts):
    client, _, calls = file_api
    registered = client.post('/api/files', files={'file': ('source.docx', document_bytes('docx'))}).json()
    headers = {'X-VINote-Operation-Id': 'retained-once'}
    form = {'source_type': 'document', 'local_file_id': registered['id']}

    def submit():
        return client.post('/api/generate_from_upload', headers=headers, data=form,
                           files={'file': ('decoy.docx', b'NOT THE RETAINED ORIGINAL')})

    first = submit()
    assert first.status_code == 200, first.text
    assert submit().json()['task_id'] == first.json()['task_id']
    assert len(calls) == 1
    assert files.get('alice', registered['id'])[0]['task_id'] == first.json()['task_id']
    assert client.get('/api/source-requests/retained-once').json()['task_id'] == first.json()['task_id']


def test_operation_receipt_web_url_reuses_task_and_rejects_different_url(file_api, source_receipts):
    client, _, calls = file_api
    headers = {'X-VINote-Operation-Id': 'web-once'}
    body = {'video_url': 'https://python.org/about', 'workflow': 'note_organization'}
    first = client.post('/api/generate', headers=headers, json=body)
    assert first.status_code == 200, first.text
    assert client.post('/api/generate', headers=headers, json=body).json()['task_id'] == first.json()['task_id']
    assert len(calls) == 1
    assert client.post('/api/generate', headers=headers,
                       json={**body, 'video_url': 'https://python.org/different'}).status_code == 409


# Failed uploads retain their source independently from any saved note.
def retained_task(files, owner='alice', workflow='meeting', task_id=None):
    import json
    import uuid
    from app.services.task_original_service import TaskOriginalService
    task_id = task_id or str(uuid.uuid4())
    artifacts = module.TaskArtifactService(module.settings.output_dir)
    folder = artifacts.create_task_dir(task_id)
    (folder / 'recording_owner').write_text(owner, encoding='utf-8')
    (folder / 'request.json').write_text(json.dumps({'request': {'workflow': workflow, 'title': '讨论视频.webm'}}), encoding='utf-8')
    media = folder / 'media'; media.mkdir()
    source = media / 'source_video.webm'; source.write_bytes(b'original-video')
    artifacts.record_source_media(folder, source, media_kind='video')
    artifacts.update_status(folder, 'failed', 'unknown', error_code='unknown_result', retryable=False)
    return TaskOriginalService(), artifacts, folder, source, task_id


def test_failed_upload_registered_without_copy_or_note_and_owner_isolated(files, monkeypatch):
    original, _, folder, source, task_id = retained_task(files)
    monkeypatch.setattr(module.shutil, 'copyfile', lambda *args: pytest.fail('must not copy media'))
    before = source.read_bytes()
    original.register('alice', folder, 'discussion.webm')
    assert (folder / 'source_original.json').is_file()
    item = files.list('alice')['items'][0]
    assert item['purpose'] == 'meeting' and item['task_id'] == task_id
    assert item['processing_status'] == 'failed' and item['error_code'] == 'unknown_result'
    assert item['retryable'] is False and 'path' not in item
    assert item['can_delete'] is False and item['can_generate'] is False
    assert files.get('alice', item['id'])[1] == source
    assert files.list('bob')['items'] == []
    with pytest.raises(HTTPException):
        files.get('bob', item['id'])
    assert source.read_bytes() == before


def test_legacy_failed_source_recovers_explicit_workflow_without_writing_artifacts(files):
    _, _, folder, _, _ = retained_task(files)
    assert files.list('alice')['items'][0]['purpose'] == 'meeting'
    assert not (folder / 'source_original.json').exists()


def test_missing_workflow_does_not_guess_meeting_from_video(files):
    _, _, _, _, _ = retained_task(files, workflow=None)
    assert files.list('alice')['items'] == []


def test_registered_source_and_task_copy_are_deduplicated(files):
    _, _, _, _, task_id = retained_task(files)
    item = saved(files)
    files.attach_task('alice', item['id'], task_id, 'meeting')
    assert [row['id'] for row in files.list('alice')['items']] == [item['id']]


def test_source_manifest_mismatch_and_deleted_source_fail_closed(files):
    import json
    original, _, folder, _, _ = retained_task(files)
    original.register('alice', folder, 'discussion.webm')
    manifest = folder / 'source_original.json'
    body = json.loads(manifest.read_text(encoding='utf-8')); body['owner'] = 'bob'
    manifest.write_text(json.dumps(body), encoding='utf-8')
    assert files.list('alice')['items'] == []
    manifest.unlink(); (folder / 'recording_deleted').touch()
    assert files.list('alice')['items'] == []


def test_task_source_cannot_be_deleted_via_library(files):
    _, _, _, source, task_id = retained_task(files)
    with pytest.raises(HTTPException):
        files.delete('alice', 'task:' + task_id)
    assert source.is_file()


def test_registered_manifest_is_frozen_and_preserves_source_time(files):
    import json
    original, _, folder, source, _ = retained_task(files)
    original.register('alice', folder, 'first.webm')
    before = (folder / 'source_original.json').read_bytes()
    original.register('alice', folder, 'new.webm')
    assert (folder / 'source_original.json').read_bytes() == before
    assert json.loads(before)['filename'] == 'first.webm'
    assert original.info('alice', folder)[0]['size_bytes'] == source.stat().st_size


def test_persist_request_registers_owner_workflow_before_worker_and_survives_rename(files, monkeypatch):
    import uuid
    from app.routers import note
    from app.models.note import LocalFileRequest
    from app.services.task_original_service import TaskOriginalService
    artifacts = module.TaskArtifactService(module.settings.output_dir)
    task_id = str(uuid.uuid4()); folder = artifacts.create_task_dir(task_id)
    media = folder / 'media'; media.mkdir()
    source = media / 'source_video.webm'; source.write_bytes(b'original')
    artifacts.record_source_media(folder, source, media_kind='video')
    monkeypatch.setattr(note, '_note_service', SimpleNamespace(artifact_service=artifacts))
    monkeypatch.setattr(note, 'ensure_source', lambda *args, **kwargs: {})
    req = LocalFileRequest(file_path=str(source), workflow='meeting', title='讨论.webm')
    note._persist_file_request(folder, req, 'alice', None)
    assert (folder / 'source_original.json').is_file()
    assert files.list('alice')['items'][0]['id'] == 'task:' + task_id
    renamed = artifacts.finalize_task_dir(folder, '纪要尚未完成', task_id)
    item, original = TaskOriginalService().get('alice', 'task:' + task_id)
    assert original == renamed / 'media' / 'source_video.webm'
    assert item['filename'] == '讨论.webm'


def test_malformed_source_index_does_not_fallback_or_hide_other_good_sources(files):
    original, _, folder, _, _ = retained_task(files)
    original.register('alice', folder, 'bad.webm')
    (folder / 'source_original.json').write_text('{}', encoding='utf-8')
    _, _, _, _, good_task = retained_task(files)
    assert [item['task_id'] for item in files.list('alice')['items']] == [good_task]


@pytest.mark.parametrize('extension', ['webm', 'md'])
def test_file_generate_cannot_bypass_unknown_task_retry_guard(file_api, extension):
    client, artifacts, calls = file_api
    item = client.post('/api/files', data={'purpose': 'meeting'}, files={'file': ('discussion.' + extension, b'original')}).json()
    service = module.LocalFileService()
    task_id = 'unknown-retained-task'
    service.attach_task('alice', item['id'], task_id, 'meeting')
    folder = artifacts.create_task_dir(task_id)
    artifacts.update_status(folder, 'failed', 'unsafe', error_code='unknown_result', retryable=True)
    before = list(calls)
    response = client.post('/api/files/' + item['id'] + '/generate', json={'meeting': True})
    assert response.status_code == 409
    assert response.json()['detail']['code'] == 'unknown_result'
    assert calls == before
