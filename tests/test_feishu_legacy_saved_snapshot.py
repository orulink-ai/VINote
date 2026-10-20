"""Legacy saved bodies do not acquire a generated presentation or new authority."""
import hashlib
import json
import os
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.db_models import NoteDB, SourceRequestDB, FeishuDeliveryDB
from app.models.feishu_auto_delivery import FeishuAutoOutboxDB
from app.models.feishu_destination import FeishuDeliveryDestinationDB
from app.models.feishu_meeting_wiki import FeishuMeetingWikiContainerDB, FeishuMeetingWikiChildDB
from app.services import feishu_auto_runtime as runtime
from app.services.feishu_service import FeishuError
from test_feishu_saved_meeting_wiki_chain import OWNER, chain  # noqa: F401
from test_feishu_graphic_delivery_guard import configure_target, submit, assert_no_delivery


@pytest.fixture
def legacy_root(chain, request):
    c = chain
    if getattr(request, 'param', 'personal') == 'personal':
        configure_target(c, 'personal')
    c.task = str(uuid4())
    c.folder = c.artifacts.create_task_dir(c.task)
    for name, value in {'.task_id': c.task, 'recording_owner': OWNER, 'generation_client': 'desktop',
                        'request.json': json.dumps({'request': {'workflow': 'meeting'}}),
                        'status.json': json.dumps({'status': 'success'})}.items():
        (c.folder / name).write_text(value, encoding='utf-8')
    c.body = '# Saved original body\n\nThe words comic and 信息图 do not assign a presentation.\n'
    response = c.client.post('/api/notes', json=dict(title='Saved legacy meeting', content=c.body,
        source_type='meeting_recording', status='done', task_id=c.task))
    assert response.status_code == 201, response.text
    c.note = response.json()['id']
    c.operation = runtime.local_status(OWNER, c.note)['operation_id']
    return c


def files(c):
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in c.folder.iterdir() if p.is_file()}


@pytest.mark.parametrize('automatic', [False, True])
@pytest.mark.parametrize('ordinary_intake', [False, True])
def test_owned_completed_root_keeps_exact_snapshot_without_inventing_metadata(legacy_root, automatic, ordinary_intake):
    c = legacy_root
    if ordinary_intake:
        with c.scope() as db:
            db.add(SourceRequestDB(owner=OWNER, task_id=c.task, operation_id=str(uuid4()),
                state='accepted', fingerprint='a' * 64,
                receipt_json=json.dumps({'status': 'preparing', 'source_type': 'upload'})))
            for account, task in [('another-owner', c.task), (OWNER, str(uuid4()))]:
                db.add(SourceRequestDB(owner=account, task_id=task, operation_id=str(uuid4()),
                    state='accepted', fingerprint='b' * 64,
                    receipt_json=json.dumps({'meeting_version': {'protocol': 1}})))
    before = files(c)
    created = submit(c, c.note, c.operation, c.body, automatic)
    with c.scope() as db:
        job = db.get(FeishuDeliveryDB, created['id'])
        snapshot = json.loads(db.get(FeishuDeliveryDestinationDB, job.id).snapshot)
        assert job.content == db.get(NoteDB, c.note).content == c.body
        assert 'graphic_delivery' not in snapshot and 'presentation' not in snapshot
        assert not snapshot['format_selection']['image_source_preserved']
    assert files(c) == before
    assert not (c.folder / 'summary_presentation.json').exists()
    assert not (c.folder / 'result.json').exists()


@pytest.mark.parametrize('automatic', [False, True])
@pytest.mark.parametrize('damage', [
    'owner', 'task_marker', 'missing_task', 'non_uuid', 'incomplete', 'missing_status',
    'invalid_status', 'non_meeting', 'missing_request', 'invalid_request', 'scope', 'note_status',
    'submitted_body', 'metadata_json', 'metadata_empty', 'metadata_directory', 'owner_hardlink',
    'source_reference.json', 'summary_visual_reference.json', 'new_generation.json',
    'summary_generation_started', 'new_generation_started', 'summary_visual.json',
    'summary_snapshot_sha256', 'summary_visual_reference_sha256', 'meeting_version', 'receipt_json',
])
def test_missing_metadata_never_downgrades_unknown_damaged_or_modern_task(legacy_root, automatic, damage):
    c = legacy_root
    content = c.body
    if damage in ('scope', 'note_status', 'non_uuid', 'missing_task'):
        with c.scope() as db:
            note = db.get(NoteDB, c.note)
            if damage == 'scope': note.scope = 'team'
            elif damage == 'note_status': note.status = 'generating'
            else: note.task_id = 'not-a-uuid' if damage == 'non_uuid' else str(uuid4())
    elif damage == 'owner': (c.folder / 'recording_owner').write_text('another-owner')
    elif damage == 'task_marker': (c.folder / '.task_id').write_text(str(uuid4()))
    elif damage == 'incomplete': (c.folder / 'status.json').write_text('{"status":"failed"}')
    elif damage == 'missing_status': (c.folder / 'status.json').unlink()
    elif damage == 'invalid_status': (c.folder / 'status.json').write_text('[]')
    elif damage == 'non_meeting': (c.folder / 'request.json').write_text('{"request":{"workflow":"note"}}')
    elif damage == 'missing_request': (c.folder / 'request.json').unlink()
    elif damage == 'invalid_request': (c.folder / 'request.json').write_text('{bad')
    elif damage == 'submitted_body': content += 'Unacknowledged edit'
    elif damage == 'metadata_json': (c.folder / 'summary_presentation.json').write_text('{bad')
    elif damage == 'metadata_empty': (c.folder / 'summary_presentation.json').write_text('')
    elif damage == 'metadata_directory': (c.folder / 'summary_presentation.json').mkdir()
    elif damage == 'owner_hardlink': os.link(c.folder / 'recording_owner', c.folder / 'owner-copy')
    elif damage in ('summary_snapshot_sha256', 'summary_visual_reference_sha256', 'meeting_version', 'receipt_json'):
        with c.scope() as db:
            db.add(SourceRequestDB(owner=OWNER, task_id=c.task, operation_id=str(uuid4()),
                state='accepted', fingerprint='a' * 64,
                receipt_json='{bad' if damage == 'receipt_json' else json.dumps({damage: None})))
    else:
        (c.folder / damage).write_text('{}')
    before = files(c)
    with pytest.raises(FeishuError) as rejected:
        submit(c, c.note, c.operation, content, automatic)
    assert rejected.value.code == 'meeting_context_unverified' and rejected.value.status_code == 409
    assert not rejected.value.uncertain
    assert_no_delivery(c)
    assert files(c) == before


@pytest.mark.parametrize('legacy_root', ['grouped_wiki'], indirect=True)
def test_legacy_body_without_metadata_never_creates_grouped_wiki_nodes(legacy_root):
    c = legacy_root
    before = files(c)
    runtime.run_once()
    state = runtime.local_status(OWNER, c.note)
    assert state['job_id']
    result = c.service.delivery_by_id(OWNER, state['job_id'])
    assert result['phase'] == 'failed' and result['error_code'] == 'meeting_context_unverified'
    assert all(call[0] == 'GET' for call in c.calls)
    assert all(event[0] == 'check_edit' for event in c.events)
    with c.scope() as db:
        assert db.scalar(select(FeishuMeetingWikiContainerDB)) is None
        assert db.scalar(select(FeishuMeetingWikiChildDB)) is None
        snapshot = json.loads(db.get(FeishuDeliveryDestinationDB, state['job_id']).snapshot)
        assert snapshot['group_meeting_versions'] is True and 'presentation' not in snapshot
        assert db.get(FeishuAutoOutboxDB, c.operation).job_id == state['job_id']
    assert files(c) == before
