"""Real saved-note/service/outbox paths; only the CLI boundary is simulated.

The shared chain fixture forbids subprocesses and HTTP transports. Graphical
assets are opaque local fixtures: no renderer, model, ASR or image writer runs.
"""
import hashlib
import json
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.db_models import FeishuDeliveryDB, NoteDB, SourceRequestDB
from app.models.feishu_auto_delivery import FeishuAutoOutboxDB
from app.models.feishu_destination import (
    FeishuDeliveryDestinationDB, FeishuPublishReceiptDB, FeishuWriteBatchDB,
)
from app.models.feishu_meeting_wiki import FeishuMeetingWikiContainerDB, FeishuMeetingWikiChildDB
from app.services import feishu_auto_runtime as runtime, summary_presentation_artifact
from app.services.feishu_service import FeishuError, FeishuService
from test_feishu_saved_meeting_wiki_chain import OWNER, ROOT, chain, save  # noqa: F401


def saved_source(c, form='comic'):
    note, operation, body = save(c, form=form)
    with c.scope() as db:
        task = db.get(NoteDB, note).task_id
    folder = c.artifacts.find_task_dir(task)
    (folder / 'result.json').write_text(json.dumps({'markdown': body}), encoding='utf-8')
    if form in ('comic', 'infographic'):
        (folder / 'summary_visual.json').write_bytes(b'opaque retained sidecar fixture')
    (folder / 'original.wav').write_bytes(b'opaque retained original fixture')
    return note, operation, body, folder


def artifact_hashes(folder):
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in folder.iterdir() if p.is_file()}


def assert_no_delivery(c):
    assert all(call[0] == 'GET' for call in c.calls)
    assert all(event[0] == 'check_edit' for event in c.events)
    with c.scope() as db:
        for model in (FeishuDeliveryDB, FeishuDeliveryDestinationDB, FeishuPublishReceiptDB,
                      FeishuWriteBatchDB, FeishuMeetingWikiContainerDB, FeishuMeetingWikiChildDB):
            assert db.scalar(select(model)) is None, model.__name__


def configure_target(c, target):
    if target == 'grouped_wiki':
        return
    chosen = c.client.get('/api/feishu/contacts', params={'query': 'Synthetic'}).json()['items'][0]
    response = c.client.put('/api/feishu/preferences', json=dict(
        notify_self=False, groups=[], auto_publish=True, automatic_delivery_consent=True,
        group_meeting_versions=False,
        contacts=[{key: chosen[key] for key in ('open_id', 'selection_token')}],
        destination_config=ROOT if target == 'wiki' else {'kind': 'personal'},
        permission_policy='inherit' if target == 'wiki' else 'private'))
    assert response.status_code == 200, response.text


def submit(c, note, operation, body, automatic):
    if automatic:
        with c.scope() as db:
            payload = json.loads(db.get(FeishuAutoOutboxDB, operation).payload)
        payload['content'] = body
        return c.service.enqueue_automatic(OWNER, **payload)
    return c.service.enqueue(OWNER, note, 'Synthetic saved meeting', body,
                             operation_id=str(uuid4()), source_mode='local_snapshot')


@pytest.mark.parametrize('form', ['comic', 'infographic'])
@pytest.mark.parametrize('automatic', [False, True])
@pytest.mark.parametrize('target', ['grouped_wiki', 'wiki', 'personal'])
def test_new_graphic_operation_refused_before_any_remote_or_wiki_allocation(chain, form, automatic, target):
    c = chain
    configure_target(c, target)
    note, operation, body, folder = saved_source(c, form)
    before = artifact_hashes(folder)
    with pytest.raises(FeishuError) as rejected:
        submit(c, note, operation, body, automatic)
    assert rejected.value.code == 'unsupported_graphic_delivery'
    assert rejected.value.status_code == 422 and rejected.value.uncertain is False
    assert '已保留' in rejected.value.detail and '尚未创建文档或通知' in rejected.value.detail
    assert_no_delivery(c)
    with c.scope() as db:
        saved = db.get(NoteDB, note)
        assert saved.content == body and saved.task_id == folder.name and saved.status == 'done'
    assert artifact_hashes(folder) == before


@pytest.mark.parametrize('form', ['comic', 'infographic'])
def test_real_save_outbox_dispatch_fails_actionably_without_automatic_resubmission(chain, form):
    c = chain
    note, operation, body, folder = saved_source(c, form)
    before = artifact_hashes(folder)
    with c.scope() as db:
        frozen = db.get(FeishuAutoOutboxDB, operation).payload
    runtime.run_once()
    current = runtime.local_status(OWNER, note)
    assert current['status'] == 'failed' and current['job_id'] is None and not current['can_check']
    assert current['operation_id'] == operation
    assert '暂不支持漫画或信息图的飞书交付' in current['error']
    assert '桌面导出' in current['error'] and '尚未创建文档或通知' in current['error']
    calls = list(c.calls)
    runtime.run_once()
    runtime.run_once()
    assert runtime.check_local(OWNER, note) == current and c.calls == calls
    assert_no_delivery(c)
    with c.scope() as db:
        row = db.get(FeishuAutoOutboxDB, operation)
        assert row.payload == frozen and row.status == 'failed' and not row.job_id
        assert db.get(NoteDB, note).content == body
    assert artifact_hashes(folder) == before


@pytest.mark.parametrize('form', ['comic', 'infographic'])
@pytest.mark.parametrize('automatic', [False, True])
@pytest.mark.parametrize('change', [
    'submitted_body', 'saved_body', 'result_body', 'newline', 'missing_result',
    'invalid_result', 'non_object_result', 'large_result', 'boolean_protocol',
])
def test_identified_graphic_with_unbound_body_fails_closed(chain, form, automatic, change):
    c = chain
    note, operation, body, folder = saved_source(c, form)
    submitted = body
    if change == 'submitted_body':
        submitted += '\nEdited publication'
    elif change == 'saved_body':
        with c.scope() as db:
            db.get(NoteDB, note).content += '\nEdited saved note'
    elif change in {'result_body', 'newline'}:
        original = body + '\nChanged task result' if change == 'result_body' else body.replace('\n', '\r\n')
        (folder / 'result.json').write_bytes(json.dumps({'markdown': original}).encode())
        # A matching note.md must never substitute for the exact JSON body.
        (folder / 'note.md').write_bytes(body.encode())
    elif change == 'missing_result':
        (folder / 'result.json').unlink()
    elif change == 'invalid_result':
        (folder / 'result.json').write_bytes(b'\xffinvalid JSON')
    elif change == 'non_object_result':
        (folder / 'result.json').write_bytes(b'[]')
    elif change == 'large_result':
        (folder / 'result.json').write_bytes(b' ' * (4 * 1024 * 1024 + 1))
    else:
        metadata = json.loads((folder / 'summary_presentation.json').read_text())
        metadata['protocol'] = True
        (folder / 'summary_presentation.json').write_text(json.dumps(metadata))
    before = artifact_hashes(folder)
    with pytest.raises(FeishuError) as rejected:
        submit(c, note, operation, submitted, automatic)
    assert rejected.value.code == 'meeting_context_unverified'
    assert rejected.value.status_code == 409 and not rejected.value.uncertain
    assert_no_delivery(c)
    assert artifact_hashes(folder) == before


def test_manual_http_rejection_keeps_note_and_originals(chain):
    c = chain
    note, _, body, folder = saved_source(c)
    before = artifact_hashes(folder)
    response = c.client.post('/api/feishu/deliveries', json=dict(
        note_key=note, title='Synthetic saved meeting', content=body,
        source_mode='local_snapshot', operation_id=str(uuid4())))
    assert response.status_code == 422
    assert '尚未创建文档或通知' in response.json()['detail']
    assert_no_delivery(c)
    assert artifact_hashes(folder) == before
    with c.scope() as db:
        assert db.get(NoteDB, note).content == body


def test_final_transaction_rechecks_note_edited_during_destination_preflight(chain, monkeypatch):
    c = chain
    note, operation, body, _ = saved_source(c)
    original = c.service.check_destination

    def edit_after_preflight(*args):
        result = original(*args)
        with c.scope() as db:
            db.get(NoteDB, note).content = 'Concurrent edit, keep this saved body'
        return result

    monkeypatch.setattr(c.service, 'check_destination', edit_after_preflight)
    with pytest.raises(FeishuError) as rejected:
        submit(c, note, operation, body, False)
    assert rejected.value.code == 'meeting_context_unverified'
    assert_no_delivery(c)
    with c.scope() as db:
        assert db.get(NoteDB, note).content == 'Concurrent edit, keep this saved body'


def damage_presentation(folder, change):
    metadata = folder / 'summary_presentation.json'
    if change == 'foreign_task':
        (folder / 'recording_owner').write_text('bob')
    elif change == 'no_metadata':
        metadata.unlink()
    elif change == 'invalid_json':
        metadata.write_text('{bad metadata', encoding='utf-8')
    elif change == 'non_object':
        metadata.write_text('[]', encoding='utf-8')
    else:
        value = json.loads(metadata.read_text())
        key, replacement = {
            'wrong_task': ('task_id', str(uuid4())),
            'invalid_protocol': ('protocol', 2),
            'float_protocol': ('protocol', 1.0),
            'boolean_protocol': ('protocol', True),
            'unknown_form': ('presentation', 'unavailable'),
            'non_string_form': ('presentation', []),
            'missing_form': ('presentation', None),
        }[change]
        value[key] = replacement
        if change == 'missing_form':
            value.pop(key)
        metadata.write_text(json.dumps(value), encoding='utf-8')


@pytest.mark.parametrize('automatic', [False, True])
@pytest.mark.parametrize('change', [
    'foreign_task', 'wrong_task', 'invalid_protocol', 'float_protocol', 'boolean_protocol',
    'no_metadata', 'invalid_json', 'non_object', 'unknown_form', 'non_string_form', 'missing_form',
])
def test_bound_task_with_unverifiable_form_refuses_new_delivery(chain, automatic, change):
    c = chain
    configure_target(c, 'wiki')  # No grouping checks may hide an admission bug.
    note, operation, body, folder = saved_source(c)
    damage_presentation(folder, change)
    before = artifact_hashes(folder)
    with pytest.raises(FeishuError) as rejected:
        submit(c, note, operation, body, automatic)
    assert rejected.value.code == 'meeting_context_unverified'
    assert rejected.value.status_code == 409 and not rejected.value.uncertain
    assert '尚未创建文档或通知' in rejected.value.detail
    assert_no_delivery(c)
    assert artifact_hashes(folder) == before
    with c.scope() as db:
        assert db.get(NoteDB, note).content == body


@pytest.mark.parametrize('change', ['no_metadata', 'invalid_json', 'invalid_protocol', 'unknown_form'])
def test_unverifiable_bound_form_outbox_fails_without_remote_write_or_repeated_attempt(chain, change):
    c = chain
    configure_target(c, 'wiki')
    note, operation, body, folder = saved_source(c)
    damage_presentation(folder, change)
    before = artifact_hashes(folder)
    with c.scope() as db:
        payload = db.get(FeishuAutoOutboxDB, operation).payload
    runtime.run_once()
    state = runtime.local_status(OWNER, note)
    assert state['status'] == 'failed' and not state['job_id'] and not state['can_check']
    assert '纪要形式' in state['error'] and '尚未创建文档或通知' in state['error']
    calls = list(c.calls)
    runtime.run_once()
    assert runtime.check_local(OWNER, note) == state and c.calls == calls
    assert_no_delivery(c)
    assert artifact_hashes(folder) == before
    with c.scope() as db:
        assert db.get(NoteDB, note).content == body
        assert db.get(FeishuAutoOutboxDB, operation).payload == payload


@pytest.mark.parametrize('grouped', [False, True])
def test_another_owners_note_cannot_supply_graphic_identity_for_text_snapshot(chain, grouped):
    c = chain
    if not grouped:
        configure_target(c, 'wiki')
    note, operation, body, _ = saved_source(c)
    with c.scope() as db:
        db.get(NoteDB, note).created_by = 'bob'
    if grouped:
        with pytest.raises(FeishuError) as rejected:
            submit(c, note, operation, body, False)
        assert rejected.value.code == 'meeting_source_unverified'
        assert_no_delivery(c)
        return
    result = submit(c, note, operation, body, False)
    assert result['_dispatch_required'] is True
    assert all(call[0] == 'GET' for call in c.calls)


@pytest.mark.parametrize('form', ['text', 'html', 'illustrated'])
@pytest.mark.parametrize('ordinary_intake_receipt', [False, True])
def test_existing_supported_forms_complete_through_unchanged_service(chain, form, ordinary_intake_receipt):
    c = chain
    note, _, body, folder = saved_source(c, form)
    if ordinary_intake_receipt:
        with c.scope() as db:
            db.add(SourceRequestDB(owner=OWNER, operation_id=str(uuid4()), task_id=folder.name,
                fingerprint='a' * 64, state='accepted',
                receipt_json=json.dumps({'status': 'preparing', 'source_type': 'upload'})))
            # Neither another owner's task nor another task's modern receipt
            # can turn this ordinary intake into a meeting-version operation.
            for account, task in [('other-owner', folder.name), (OWNER, str(uuid4()))]:
                db.add(SourceRequestDB(owner=account, operation_id=str(uuid4()), task_id=task,
                    fingerprint='b' * 64, state='accepted',
                    receipt_json=json.dumps({'summary_snapshot_sha256': 'c' * 64})))
    # These forms acquire no new result/sidecar proof requirement.
    (folder / 'result.json').unlink()
    runtime.run_once()
    local = runtime.local_status(OWNER, note)
    receipt = c.service.delivery_by_id(OWNER, local['job_id'])
    assert receipt['status'] == receipt['phase'] == 'completed'
    assert [e[0] for e in c.events].count('create_parent') == 1
    assert [e[0] for e in c.events].count('create_child') == 1
    assert [e[0] for e in c.events].count('body') == 1
    assert [e[0] for e in c.events].count('notify') == 1
    with c.scope() as db:
        assert db.get(NoteDB, note).content == body


@pytest.mark.parametrize('automatic', [False, True])
def test_graphic_words_in_title_body_and_nearby_task_do_not_trigger_guard(chain, automatic):
    c = chain
    note, operation, _, _ = saved_source(c)
    body = 'comic infographic 漫画 信息图 are ordinary words here.'
    with c.scope() as db:
        db.get(NoteDB, note).task_id = None
        db.get(NoteDB, note).source_type = 'text'
        db.get(NoteDB, note).title = '漫画 infographic'
        db.get(NoteDB, note).content = body
    result = (submit(c, note, operation, body, True) if automatic else
              c.service.enqueue(OWNER, note, '漫画 infographic', body,
                                operation_id=str(uuid4()), source_mode='local_snapshot'))
    assert result['_dispatch_required'] is True
    assert all(call[0] == 'GET' for call in c.calls)


@pytest.mark.parametrize('form', ['comic', 'infographic'])
@pytest.mark.parametrize('grouped', [False, True])
def test_publish_alias_cannot_bypass_owned_graphic_source_guard(chain, form, grouped):
    c = chain
    if not grouped:
        configure_target(c, 'wiki')
    note, _, body, folder = saved_source(c, form)
    before = artifact_hashes(folder)
    with pytest.raises(FeishuError) as rejected:
        c.service.enqueue(OWNER, 'publish:' + note, 'Synthetic saved meeting', body,
                          operation_id=str(uuid4()), source_mode='local_snapshot')
    assert rejected.value.code == 'unsupported_graphic_delivery'
    assert_no_delivery(c)
    assert artifact_hashes(folder) == before


def database_receipts(c):
    with c.scope() as db:
        return {model.__tablename__: [
            {column.name: getattr(row, column.name) for column in model.__table__.columns}
            for row in db.scalars(select(model)).all()]
            for model in (FeishuDeliveryDB, FeishuDeliveryDestinationDB, FeishuPublishReceiptDB)}


@pytest.mark.parametrize('automatic', [False, True])
@pytest.mark.parametrize('state', ['accepted', 'unknown'])
def test_original_operations_and_gets_keep_frozen_receipts_without_source_resolution(chain, monkeypatch, automatic, state):
    c = chain
    note, operation, body, folder = saved_source(c, 'text')
    if automatic:
        with c.scope() as db:
            payload = json.loads(db.get(FeishuAutoOutboxDB, operation).payload)
        created = c.service.enqueue_automatic(OWNER, **payload)
        replay = lambda: c.service.enqueue_automatic(OWNER, **payload)
    else:
        operation = str(uuid4())
        payload = dict(note_key=note, title='Synthetic saved meeting', content=body,
                       operation_id=operation, source_mode='local_snapshot')
        created = c.service.enqueue(OWNER, **payload)
        replay = lambda: c.service.enqueue(OWNER, **payload)
    with c.scope() as db:
        job = db.get(FeishuDeliveryDB, created['id'])
        job.status = 'processing' if state == 'accepted' else 'failed'
        job.lease_until = '99999999999'
        if state == 'unknown':
            job.document_id = '__creating__'
            db.get(FeishuDeliveryDestinationDB, job.id).phase = 'unknown'
        item = db.scalar(select(FeishuAutoOutboxDB))
        item.status = state if automatic else 'cancelled'
        item.job_id = job.id if automatic else ''
        # A later edit or unreadable graphical source cannot rewrite history.
        db.get(NoteDB, note).content = 'Later saved edit'
    metadata = json.loads((folder / 'summary_presentation.json').read_text())
    metadata['presentation'] = 'comic'
    (folder / 'summary_presentation.json').write_text(json.dumps(metadata))
    (folder / 'result.json').unlink()
    original = c.service.delivery_by_operation(OWNER, operation)
    before, calls = database_receipts(c), list(c.calls)

    def forbidden(*args, **kwargs):
        pytest.fail('Historical receipt must return before new source/graphic guard')

    monkeypatch.setattr(FeishuService, '_guard_graphic_delivery', staticmethod(forbidden))
    monkeypatch.setattr(FeishuService, 'resolve_content', staticmethod(forbidden))
    monkeypatch.setattr(summary_presentation_artifact, 'read_presentation', forbidden)
    again = replay()
    assert again.pop('_dispatch_required') is False
    assert again == original
    assert c.client.get('/api/feishu/deliveries/by-operation/' + operation).json() == original
    by_id = dict(original)
    by_id.pop('operation_id')
    assert c.client.get('/api/feishu/deliveries/by-id/' + created['id']).json() == by_id
    if automatic:
        assert runtime.check_local(OWNER, note)['status'] == 'accepted'
    runtime.run_once()
    assert database_receipts(c) == before and c.calls == calls


def test_existing_revision_reuse_precedes_new_graphic_guard(chain, monkeypatch):
    c = chain
    note, operation, body, folder = saved_source(c, 'text')
    created = submit(c, note, operation, body, False)
    metadata = json.loads((folder / 'summary_presentation.json').read_text())
    metadata['presentation'] = 'infographic'
    (folder / 'summary_presentation.json').write_text(json.dumps(metadata))
    monkeypatch.setattr(FeishuService, '_guard_graphic_delivery', staticmethod(
        lambda *args: pytest.fail('Existing revision must reuse its receipt')))
    again = submit(c, note, operation, body, False)
    assert again['id'] == created['id'] and again['_dispatch_required'] is False
    assert all(call[0] == 'GET' for call in c.calls)
