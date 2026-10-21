"""Actual accepted sidecars and service/image journals; external CLI is fake."""
from copy import deepcopy
from io import BytesIO
import json
import shutil
from types import SimpleNamespace
from uuid import uuid4

from PIL import Image
import pytest
from sqlalchemy import select

from app.db_models import NoteDB, SourceRequestDB, FeishuDeliveryDB
from app.models.feishu_destination import FeishuDeliveryDestinationDB, FeishuWriteBatchDB
from app.models.feishu_native_images import FeishuNativeImagePlanDB, FeishuNativeImageStepDB
from app.services import feishu_graphic_delivery as graphics, feishu_native_images as images
from app.services import feishu_auto_runtime as runtime, feishu_cli as cli
from app.services import summary_visual_artifact as visual
from app.services.feishu_service import FeishuError
from test_feishu_saved_meeting_wiki_chain import OWNER, chain  # noqa: F401
from test_feishu_graphic_delivery_guard import configure_target
from test_summary_visual_artifact import case as visual_case, save as save_visual, final_ledger_case  # noqa: F401


@pytest.fixture(params=['comic', 'infographic'])
def graphic(chain, visual_case, monkeypatch, request):
    c, v = chain, visual_case
    form, target = request.param if isinstance(request.param, tuple) else (request.param, 'grouped_wiki')
    configure_target(c, target)
    v.markdown, v.wire, _, _ = final_ledger_case(v, form)
    save_visual(v)
    folder = c.artifacts.create_task_dir(v.task)
    if v.folder.resolve() != folder.resolve():
        shutil.copytree(v.folder, folder, dirs_exist_ok=True)
    (folder / 'generation_client').write_text('desktop')
    (folder / 'request.json').write_text(json.dumps(dict(request=dict(workflow='meeting'))))
    from hashlib import sha256
    (folder / 'source_reference.json').write_text(json.dumps(dict(version=1, owner=OWNER,
        parent_task_id=c.canonical, source_version=sha256(b'synthetic original').hexdigest())))
    with v.sessions() as db:
        source = db.get(SourceRequestDB, (OWNER, str(v.body.operation_id)))
        values = {column.name: getattr(source, column.name) for column in SourceRequestDB.__table__.columns}
    with c.scope() as db:
        db.add(SourceRequestDB(**values))
    response = c.client.post('/api/notes', json=dict(title='Synthetic graphic', content=v.markdown,
        source_type='meeting_recording', status='done', task_id=v.task))
    assert response.status_code == 201, response.text
    c.note, c.body, c.folder, c.task = response.json()['id'], v.markdown, folder, v.task
    c.form = form
    c.operation = runtime.local_status(OWNER, c.note)['operation_id']
    c.native, c.root, c.blocks, c.failure = [], [], {}, None
    original_run = cli.run
    monkeypatch.setattr(c.service.__class__, 'granted_scopes', staticmethod(lambda row: {
        'contact:user:search', 'docx:document', 'wiki:wiki', 'drive:drive', 'im:message',
        images.REQUIRED_UPLOAD_SCOPE, 'docx:document.block:convert'}))

    def journal():
        with c.scope() as db:
            dispatching = db.scalars(select(FeishuWriteBatchDB).where(
                FeishuWriteBatchDB.state == 'dispatching')).all()
            assert len(dispatching) == 1

    def run(owner, args, *, body=None, **kwargs):
        if args[:1] != ['api']:
            return original_run(owner, args, body=body, **kwargs)
        method, path = args[1:3]
        if method == 'POST' and '/wiki/v2/spaces/' in path and path.endswith('/nodes'):
            with c.scope() as db:
                job = db.scalar(select(FeishuDeliveryDB))
                snapshot = json.loads(db.get(FeishuDeliveryDestinationDB, job.id).snapshot)
                assert snapshot.get('graphic_manifest')
                graphics.delivery_parts(c.artifacts, OWNER, job, snapshot)
                grouped = snapshot.get('group_meeting_versions') is True
            from app.services.feishu_auto_policy import active_delivery
            execution = active_delivery.get()
            if not grouped or not (execution and execution[1].get('automatic_policy_id')):
                parent = body['parent_node_token']
                kind = 'create_parent' if grouped and parent == 'synthetic_root' else 'create_child'
                node_id = kind + '_' + str(len(c.nodes))
                document = kind + '_doc_' + str(len(c.nodes))
                node = dict(node_token=node_id, space_id='synthetic_space', node_type='origin',
                            obj_type='docx', obj_token=document, parent_node_token=parent, title=body['title'])
                c.nodes[node_id] = node
                c.events.append((kind, document, parent, body['title']))
                return dict(ok=True, identity='user', data=dict(node=deepcopy(node)))
        if method == 'POST' and path.endswith('/docx/v1/documents'):
            document = 'create_child_doc_personal'
            c.nodes[document] = dict(obj_token=document)
            c.events.append(('create_child', document, '', body['title']))
            return dict(ok=True, identity='user', data=dict(document=dict(document_id=document)))
        if method == 'PATCH' and '/permissions/' in path and path.endswith('/public'):
            c.events.append(('permission_write', path))
            return dict(ok=True, identity='user', data={})
        from app.services.feishu_auto_policy import active_delivery
        execution = active_delivery.get()
        if not (execution and execution[1].get('automatic_policy_id')) and method == 'POST':
            if '/permissions/' in path and path.endswith('/members'):
                document = path.split('/permissions/')[1].split('/')[0]
                assert any(e[0] == 'body' and e[1] == document for e in c.events)
                c.readable.add((document, body['member_id']))
                c.events.append(('grant_view', document, body['member_id']))
                return dict(ok=True, identity='user', data={})
            if path.endswith('/im/v1/messages'):
                url = json.loads(body['content'])['zh_cn']['content'][1][0]['href']
                document = c.nodes[url.rsplit('/', 1)[-1]]['obj_token']
                assert (document, body['receive_id']) in c.readable
                c.events.append(('notify', document, body['uuid']))
                return dict(ok=True, identity='user', data=dict(message_id='synthetic_manual_message'))
        if '/docx/v1/documents/' not in path or '/blocks/' not in path:
            return original_run(owner, args, body=body, **kwargs)
        block = path.rsplit('/', 1)[-1]
        if method == 'GET':
            data = dict(block=deepcopy(c.blocks[block]) if block in c.blocks else
                        dict(block_id=block, block_type=1, children=list(c.root)))
        else:
            journal()
            if path.endswith('/descendant'):
                mapping = {node['block_id']: f'text_{len(c.root)}_{i}' for i, node in enumerate(body['descendants'])}
                c.root.extend(mapping[i] for i in body['children_id'])
                c.native.append(('text', deepcopy(body)))
                document = path.split('/documents/')[1].split('/')[0]
                c.events.append(('body', document, deepcopy(body)))
                data = dict(block_id_relations=[dict(temporary_block_id=k, block_id=v) for k, v in mapping.items()])
            elif method == 'POST':
                document = path.split('/documents/')[1].split('/')[0]
                ident = 'image_' + str(len(c.root))
                c.root.append(ident)
                c.blocks[ident] = dict(block_id=ident, parent_id=document, block_type=27, image={})
                c.native.append(('create', ident))
                data = dict(children=[deepcopy(c.blocks[ident])])
            else:
                item = body['requests'][0]
                c.blocks[item['block_id']]['image'] = deepcopy(item['replace_image'])
                c.native.append(('bind', item['block_id']))
                data = {}
            if c.failure == c.native[-1][0]:
                raise TimeoutError('synthetic lost acknowledgment')
        return dict(ok=True, identity='user', data=data)

    def upload(owner, binding, doc, block, asset, data):
        journal()
        assert graphics._hash(data) == asset['sha256'] and asset['mime'] == 'image/png'
        c.native.append(('upload', asset['sha256']))
        if c.failure == 'upload':
            raise TimeoutError('synthetic ambiguous upload')
        return dict(file_token='token_' + block)

    def checked_run(*args, **kwargs):
        try:
            return run(*args, **kwargs)
        except Exception as exc:
            print('synthetic CLI boundary failure:', type(exc).__name__, str(exc))
            raise
    monkeypatch.setattr(cli, 'run', checked_run)
    monkeypatch.setattr(images, 'upload_cli', upload)
    return c


def current(c):
    local = runtime.local_status(OWNER, c.note)
    return c.service.delivery_by_id(OWNER, local['job_id']) if local['job_id'] else local


def _automatic_payload(c):
    from app.models.feishu_auto_delivery import FeishuAutoOutboxDB
    with c.scope() as db:
        return json.loads(db.get(FeishuAutoOutboxDB, c.operation).payload)


def _assert_no_allocation(c):
    from app.models.feishu_destination import FeishuPublishReceiptDB
    from app.models.feishu_meeting_wiki import FeishuMeetingWikiContainerDB, FeishuMeetingWikiChildDB
    assert not c.native and all(event[0] == 'check_edit' for event in c.events)
    assert all(call[0] == 'GET' for call in c.calls)
    with c.scope() as db:
        for model in (FeishuDeliveryDB, FeishuDeliveryDestinationDB, FeishuPublishReceiptDB,
                      FeishuWriteBatchDB, FeishuNativeImagePlanDB, FeishuNativeImageStepDB,
                      FeishuMeetingWikiContainerDB, FeishuMeetingWikiChildDB):
            assert db.scalar(select(model)) is None, model.__name__


@pytest.mark.parametrize('form', ['text', 'html', 'illustrated'])
@pytest.mark.parametrize('entry', ['manual', 'automatic', 'outbox'])
def test_metadata_cannot_downgrade_accepted_graphics_before_any_allocation(graphic, form, entry):
    c = graphic
    path = c.folder / 'summary_presentation.json'
    metadata = json.loads(path.read_text())
    metadata['presentation'] = form
    path.write_text(json.dumps(metadata))
    if entry == 'outbox':
        runtime.run_once()
        result = runtime.local_status(OWNER, c.note)
        assert result['status'] == 'failed' and not result['job_id']
        assert '尚未创建文档或通知' in result['error']
        calls = deepcopy(c.calls)
        runtime.run_once()
        assert runtime.local_status(OWNER, c.note) == result and c.calls == calls
    else:
        with pytest.raises(FeishuError) as rejected:
            if entry == 'automatic':
                c.service.enqueue_automatic(OWNER, **_automatic_payload(c))
            else:
                c.service.enqueue(OWNER, c.note, 'Synthetic graphic', c.body,
                                  operation_id=str(uuid4()), source_mode='local_snapshot')
        assert rejected.value.code == 'meeting_context_unverified'
        assert rejected.value.status_code == 409 and rejected.value.uncertain is False
    _assert_no_allocation(c)
    with c.scope() as db:
        assert db.get(NoteDB, c.note).content == c.body


@pytest.mark.parametrize('retained', ['receipt', 'sidecar', 'both', 'null_snapshot'])
@pytest.mark.parametrize('entry', ['manual', 'automatic', 'outbox'])
def test_stripping_disk_identity_cannot_erase_modern_authority(graphic, retained, entry):
    c = graphic
    path = c.folder / 'summary_presentation.json'
    metadata = json.loads(path.read_text())
    metadata['presentation'] = 'text'
    for key in ('operation_id', 'parent_task_id', 'source_version'):
        metadata.pop(key, None)
    path.write_text(json.dumps(metadata))
    for name in ('new_generation.json', 'summary_generation_started', 'new_generation_started'):
        (c.folder / name).unlink(missing_ok=True)
    if retained in ('receipt', 'null_snapshot'):
        (c.folder / 'summary_visual.json').unlink()
    if retained in ('sidecar', 'null_snapshot'):
        with c.scope() as db:
            row = db.scalar(select(SourceRequestDB).where(SourceRequestDB.owner == OWNER,
                                                         SourceRequestDB.task_id == c.task))
            if retained == 'sidecar':
                db.delete(row)
            else:
                row.receipt_json = json.dumps({'summary_snapshot_sha256': None})
    if entry == 'outbox':
        runtime.run_once()
        result = runtime.local_status(OWNER, c.note)
        assert result['status'] == 'failed' and result['job_id'] is None
        calls = deepcopy(c.calls)
        runtime.run_once()
        assert runtime.local_status(OWNER, c.note) == result and c.calls == calls
    else:
        with pytest.raises(FeishuError) as rejected:
            if entry == 'automatic':
                c.service.enqueue_automatic(OWNER, **_automatic_payload(c))
            else:
                c.service.enqueue(OWNER, c.note, 'Synthetic graphic', c.body,
                                  operation_id=str(uuid4()), source_mode='local_snapshot')
        assert rejected.value.code == 'meeting_context_unverified'
    _assert_no_allocation(c)


def _accepted_supported_form(c, form):
    """Create a synthetic supported-form receipt, not just a display relabel."""
    from app.services.meeting_summary_regeneration import SummaryConfirmation, _submission
    from app.services.source_request_service import _fingerprint
    path = c.folder / 'new_generation.json'
    link = json.loads(path.read_text())
    link['presentation'] = form
    body = SummaryConfirmation(**{key: link[key] for key in SummaryConfirmation.model_fields if key in link})
    with c.scope() as db:
        row = db.get(SourceRequestDB, (OWNER, link['operation_id']))
        row.fingerprint = _fingerprint(_submission(link['parent_task_id'], body))
    path.write_text(json.dumps(link))
    path = c.folder / 'summary_presentation.json'
    metadata = json.loads(path.read_text())
    metadata['presentation'] = form
    path.write_text(json.dumps(metadata))
    (c.folder / 'summary_visual.json').unlink()


def _accepted_fresh_version(c, form):
    """Stage only the real fresh submission/receipt protocol; never run its worker."""
    from app.services.meeting_version_context import (
        MeetingVersionConfirmation, _VersionReceipts, _request_hash,
    )
    from app.services.task_fresh_asr import _body, _digest, _submission
    from app.services.source_request_service import SourceRequestService
    metadata = json.loads((c.folder / 'summary_presentation.json').read_text())
    previous = json.loads((c.folder / 'new_generation.json').read_text())
    snapshot = json.loads((c.folder / 'model_source_snapshot.json').read_text())
    body = MeetingVersionConfirmation(operation_id=uuid4(), confirmed=True,
        context_revision=previous['context_revision'], source_version=previous['source_version'],
        asr_mode='fresh', llm_mode='select', model_name=snapshot['llm_model'],
        asr_model='synthetic-fresh-asr', selection_revision='a' * 64,
        fresh_context_revision='b' * 64, extra_asr_consent=True,
        content_depth=metadata['content_depth'], presentation=form)
    snapshot.update(needs_stt=True, asr_model=body.asr_model)
    link = dict(contract='meeting-fresh-asr-v1', parent_task_id=previous['parent_task_id'],
                canonical_task_id=c.canonical, snapshot_sha256=_digest(snapshot),
                **_body(body).model_dump(mode='json'))
    with c.scope() as db:
        for row in db.scalars(select(SourceRequestDB).where(
                SourceRequestDB.owner == OWNER, SourceRequestDB.task_id == c.task)):
            db.delete(row)
    receipts = _VersionReceipts(SourceRequestService(c.scope), link['parent_task_id'],
                               _request_hash(link['parent_task_id'], body))
    operation = str(body.operation_id)
    receipts.reserve(OWNER, operation, _submission(link), task_id=c.task)
    receipts.accept(OWNER, operation, c.task, status='preparing', source_type='meeting_recording')
    with c.scope() as db:
        saved = json.loads(db.get(SourceRequestDB, (OWNER, operation)).receipt_json)
        assert set(saved) == {'status', 'source_type', 'meeting_version'}
        assert saved['meeting_version'] == receipts.tag
    metadata.update(operation_id=operation, presentation=form)
    for name, value in [('new_generation.json', link), ('model_source_snapshot.json', snapshot),
                        ('summary_presentation.json', metadata)]:
        (c.folder / name).write_text(json.dumps(value))
    (c.folder / 'summary_generation_started').unlink()
    (c.folder / 'new_generation_started').write_text('claimed')
    # Verify the genuine accepted fresh contract before the test damages files.
    from app.services.summary_visual_artifact import _authorization
    assert _authorization(c.folder, OWNER, c.task, form, c.scope)['operation_id'] == operation
    return operation


@pytest.mark.parametrize('tag_shape', ['real', 'null', 'empty'])
@pytest.mark.parametrize('entry', ['manual', 'automatic', 'outbox'])
def test_nested_fresh_version_receipt_survives_complete_disk_stripping(graphic, tag_shape, entry):
    c = graphic
    operation = _accepted_fresh_version(c, c.form)
    if tag_shape != 'real':
        with c.scope() as db:
            row = db.get(SourceRequestDB, (OWNER, operation))
            saved = json.loads(row.receipt_json)
            saved['meeting_version'] = None if tag_shape == 'null' else {}
            row.receipt_json = json.dumps(saved)
    path = c.folder / 'summary_presentation.json'
    metadata = json.loads(path.read_text())
    metadata['presentation'] = 'text'
    for key in ('operation_id', 'parent_task_id', 'source_version'):
        metadata.pop(key, None)
    path.write_text(json.dumps(metadata))
    for name in ('new_generation.json', 'summary_generation_started', 'new_generation_started',
                 'summary_visual.json'):
        (c.folder / name).unlink(missing_ok=True)
    if entry == 'outbox':
        runtime.run_once()
        result = runtime.local_status(OWNER, c.note)
        assert result['status'] == 'failed' and result['job_id'] is None
        calls = deepcopy(c.calls)
        runtime.run_once()
        assert runtime.local_status(OWNER, c.note) == result and c.calls == calls
    else:
        with pytest.raises(FeishuError) as rejected:
            if entry == 'automatic':
                c.service.enqueue_automatic(OWNER, **_automatic_payload(c))
            else:
                c.service.enqueue(OWNER, c.note, 'Synthetic graphic', c.body,
                                  operation_id=str(uuid4()), source_mode='local_snapshot')
        assert rejected.value.code == 'meeting_context_unverified'
    _assert_no_allocation(c)


@pytest.mark.parametrize('form', ['text', 'html', 'illustrated'])
def test_intact_fresh_version_supported_forms_remain_accepted(graphic, form):
    c = graphic
    _accepted_fresh_version(c, form)
    (c.folder / 'summary_visual.json').unlink()
    created = c.service.enqueue_automatic(OWNER, **_automatic_payload(c))
    with c.scope() as db:
        job = db.get(FeishuDeliveryDB, created['id'])
        snapshot = json.loads(db.get(FeishuDeliveryDestinationDB, job.id).snapshot)
        assert job.content == c.body and 'graphic_delivery' not in snapshot


@pytest.mark.parametrize('form', ['text', 'html', 'illustrated'])
def test_accepted_supported_forms_keep_their_own_non_graphic_snapshot(graphic, form):
    c = graphic
    _accepted_supported_form(c, form)
    created = c.service.enqueue_automatic(OWNER, **_automatic_payload(c))
    with c.scope() as db:
        job = db.get(FeishuDeliveryDB, created['id'])
        snapshot = json.loads(db.get(FeishuDeliveryDestinationDB, job.id).snapshot)
        assert job.content == c.body and 'graphic_delivery' not in snapshot
    assert not c.native and all(event[0] == 'check_edit' for event in c.events)


@pytest.mark.parametrize('damage', ['missing_link', 'missing_claim', 'fingerprint', 'snapshot_hash', 'link_only_relabel'])
def test_supported_form_still_requires_its_accepted_authority(graphic, damage):
    c = graphic
    _accepted_supported_form(c, 'text')
    if damage == 'missing_link':
        (c.folder / 'new_generation.json').unlink()
    elif damage == 'missing_claim':
        (c.folder / 'summary_generation_started').unlink()
    elif damage in ('fingerprint', 'snapshot_hash'):
        link = json.loads((c.folder / 'new_generation.json').read_text())
        with c.scope() as db:
            row = db.get(SourceRequestDB, (OWNER, link['operation_id']))
            if damage == 'fingerprint':
                row.fingerprint = '0' * 64
            else:
                row.receipt_json = json.dumps({'summary_snapshot_sha256': '0' * 64})
    else:
        # Matching mutable files cannot replace the original DB fingerprint.
        for name in ('new_generation.json', 'summary_presentation.json'):
            path = c.folder / name
            value = json.loads(path.read_text())
            value['presentation'] = 'html'
            path.write_text(json.dumps(value))
    with pytest.raises(FeishuError) as rejected:
        c.service.enqueue_automatic(OWNER, **_automatic_payload(c))
    assert rejected.value.code == 'meeting_context_unverified'
    _assert_no_allocation(c)


@pytest.mark.parametrize('form', ['comic', 'infographic'])
def test_supported_receipt_cannot_be_relabelled_as_graphics(graphic, form):
    c = graphic
    _accepted_supported_form(c, 'text')
    path = c.folder / 'summary_presentation.json'
    metadata = json.loads(path.read_text())
    metadata['presentation'] = form
    path.write_text(json.dumps(metadata))
    with pytest.raises(FeishuError) as rejected:
        c.service.enqueue_automatic(OWNER, **_automatic_payload(c))
    assert rejected.value.code == 'unsupported_graphic_delivery'
    _assert_no_allocation(c)


def test_real_graphic_service_freezes_png_before_create_and_preserves_exact_body(graphic):
    c = graphic
    runtime.run_once()
    result = current(c)
    assert result['phase'] == 'completed', json.dumps(dict(result=result, events=c.events, native=c.native), ensure_ascii=False)
    assert result['formatting']['images_embedded'] is True
    kinds = [e[0] for e in c.native]
    assert kinds[-1] == 'text' and kinds[:-1] == ['create', 'upload', 'bind'] * kinds.count('create')
    assert [e[0] for e in c.events].count('notify') == 1
    with c.scope() as db:
        job = db.get(FeishuDeliveryDB, result['id'])
        snapshot = json.loads(db.get(FeishuDeliveryDestinationDB, job.id).snapshot)
        assert job.content == db.get(NoteDB, c.note).content == c.body
        assert snapshot['graphic_delivery']['body_sha256'] == graphics._hash(c.body.encode())
        manifest = snapshot['graphic_manifest']
        assert manifest['parts'][-1] == dict(kind='text', content=c.body)
        assert manifest['renderer'] == snapshot['graphic_delivery']['renderer']
        assert graphics.delivery_parts(c.artifacts, OWNER, job, snapshot) == manifest['parts']
        assert db.get(FeishuNativeImagePlanDB, job.id) is not None
    before = deepcopy(c.native), deepcopy(c.events)
    runtime.run_once()
    assert (c.native, c.events) == before


@pytest.mark.parametrize('graphic', [(form, target) for form in ('comic', 'infographic')
                                   for target in ('grouped_wiki', 'wiki', 'personal')], indirect=True)
@pytest.mark.parametrize('automatic', [False, True])
def test_manual_and_automatic_graphics_across_destinations(graphic, automatic):
    c = graphic
    if automatic:
        runtime.run_once()
        result = current(c)
    else:
        from app.services.feishu_recipient_access import POLICY
        chosen = c.client.get('/api/feishu/contacts', params={'query': 'Synthetic'}).json()['items'][0]
        response = c.client.post('/api/feishu/deliveries', json=dict(note_key=c.note,
            title='Synthetic graphic', content=c.body, source_mode='local_snapshot', operation_id=str(uuid4()),
            contacts=[{key: chosen[key] for key in ('open_id', 'selection_token')}],
            recipient_access_policy=POLICY))
        assert response.status_code == 200, response.text
        result = c.service.delivery_by_id(OWNER, response.json()['id'])
    assert result['phase'] == 'completed', json.dumps(dict(result=result, events=c.events, native=c.native), ensure_ascii=False)
    assert result['formatting']['images_embedded'] is True
    assert any(e[0] == 'upload' for e in c.native)
    assert any(e[0] == 'notify' for e in c.events)


@pytest.mark.parametrize('phase', ['create', 'upload', 'bind', 'text'])
def test_graphic_unknown_step_does_not_complete_notify_or_replay(graphic, phase):
    c = graphic
    c.failure = phase
    runtime.run_once()
    result = current(c)
    assert result['phase'] == 'unknown', result
    assert result['formatting']['images_embedded'] is False
    assert not any(e[0] == 'notify' for e in c.events)
    before = deepcopy(c.native), deepcopy(c.events)
    runtime.run_once()
    assert (c.native, c.events) == before
    with c.scope() as db:
        assert any(row.state == 'unknown' for row in db.scalars(select(FeishuWriteBatchDB)))


@pytest.mark.parametrize('damage', ['sidecar', 'screenshot', 'accepted_receipt', 'body'])
def test_untrusted_source_refused_before_delivery_or_remote_create(graphic, damage):
    c = graphic
    if damage == 'sidecar':
        (c.folder / 'summary_visual.json').write_text('{}')
    elif damage == 'screenshot':
        if c.form != 'comic':
            pytest.skip('Infographic wire has no screenshots; unrelated files are not authority')
        Image.new('RGB', (32, 24), 'red').save(c.folder / 'screenshots/summary-source-0.jpg')
    elif damage == 'accepted_receipt':
        with c.scope() as db:
            db.scalar(select(SourceRequestDB)).state = 'unknown'
    else:
        with c.scope() as db:
            db.get(NoteDB, c.note).content += 'changed'
    runtime.run_once()
    assert current(c)['status'] == 'failed'
    assert not c.native and not any(e[0].startswith('create') for e in c.events)
    with c.scope() as db:
        assert db.scalar(select(FeishuDeliveryDB)) is None


def test_render_failure_creates_no_remote_and_snapshot_does_not_gain_partial_pages(graphic, monkeypatch):
    c = graphic
    from app.services import summary_visual_png
    def fail(*a, **kw):
        raise ValueError('synthetic render failure')
    monkeypatch.setattr(summary_visual_png, 'render_summary_visual_png', fail)
    runtime.run_once()
    result = current(c)
    assert result['phase'] == 'failed' and result['error_code'] == 'graphic_render_unavailable'
    assert not c.native and not any(e[0].startswith('create') for e in c.events)
    with c.scope() as db:
        snapshot = json.loads(db.get(FeishuDeliveryDestinationDB, result['id']).snapshot)
        assert 'graphic_delivery' in snapshot and 'graphic_manifest' not in snapshot


def test_original_graphic_operation_and_unknown_get_do_not_rerender_or_enrich_snapshot(graphic, monkeypatch):
    c = graphic
    with c.scope() as db:
        from app.models.feishu_auto_delivery import FeishuAutoOutboxDB
        payload = json.loads(db.get(FeishuAutoOutboxDB, c.operation).payload)
    created = c.service.enqueue_automatic(OWNER, **payload)
    with c.scope() as db:
        job = db.get(FeishuDeliveryDB, created['id'])
        job.document_id = '__creating__'
        job.status = 'failed'
        db.get(FeishuDeliveryDestinationDB, job.id).phase = 'unknown'
        before = db.get(FeishuDeliveryDestinationDB, job.id).snapshot
    def forbidden(*a, **kw):
        pytest.fail('Historical operation must not resolve sources or render')
    monkeypatch.setattr(graphics, 'capture', forbidden)
    monkeypatch.setattr(graphics, 'prepare', forbidden)
    monkeypatch.setattr(visual, 'read_summary_visual', forbidden)
    again = c.service.enqueue_automatic(OWNER, **payload)
    assert again['_dispatch_required'] is False and again['phase'] == 'unknown'
    assert c.service.delivery_by_operation(OWNER, c.operation)['phase'] == 'unknown'
    with c.scope() as db:
        assert db.get(FeishuDeliveryDestinationDB, created['id']).snapshot == before
    assert not c.native and not any(e[0].startswith('create') for e in c.events)


@pytest.mark.parametrize('change', ['sidecar', 'renderer', 'saved_body'])
def test_changed_source_after_acceptance_refuses_before_remote_allocation(graphic, monkeypatch, change):
    c = graphic
    from app.models.feishu_auto_delivery import FeishuAutoOutboxDB
    with c.scope() as db:
        payload = json.loads(db.get(FeishuAutoOutboxDB, c.operation).payload)
    created = c.service.enqueue_automatic(OWNER, **payload)
    if change == 'sidecar':
        (c.folder / 'summary_visual.json').write_text('{}')
    elif change == 'saved_body':
        with c.scope() as db:
            db.get(NoteDB, c.note).content += '\nConcurrent edit'
    else:
        original = graphics._renderer
        def changed():
            module, identity = original()
            return module, {**identity, 'font_sha256': '0' * 64}
        monkeypatch.setattr(graphics, '_renderer', changed)
    c.service.process(OWNER, created['id'])
    assert c.service.delivery_by_id(OWNER, created['id'])['phase'] == 'failed'
    assert not c.native and not any(e[0].startswith('create') for e in c.events)


def test_manual_account_changed_during_render_never_creates_under_new_connection(graphic, monkeypatch):
    c = graphic
    from app.db_models import FeishuConnectionDB
    from app.services import summary_visual_png
    identity = summary_visual_png.renderer_identity()
    original = graphics._publish_png
    published = []
    def reconnect(*args, **kwargs):
        result = original(*args, **kwargs)
        if not published:
            # Real rendering has finished; change accounts before remote allocation.
            # Patching the renderer itself changes its accepted implementation identity.
            published.append(result['asset']['sha256'])
            with c.scope() as db:
                account = db.get(FeishuConnectionDB, OWNER)
                prefs = json.loads(account.preferences)
                account.preferences = json.dumps({**prefs, 'connection_id': 'changed_during_render'})
        return result
    monkeypatch.setattr(graphics, '_publish_png', reconnect)
    response = c.client.post('/api/feishu/deliveries', json=dict(note_key=c.note,
        title='Synthetic graphic', content=c.body, source_mode='local_snapshot', operation_id=str(uuid4())))
    assert response.status_code == 200, response.text
    result = c.service.delivery_by_id(OWNER, response.json()['id'])
    assert len(published) == 1 and len(published[0]) == 64
    assert summary_visual_png.renderer_identity() == identity
    assert result['phase'] == 'failed' and result['error_code'] == 'connection_changed'
    assert not c.native and not any(e[0].startswith('create') for e in c.events)


def test_frozen_pages_missing_never_regenerate_or_fallback_to_text(graphic, monkeypatch):
    c = graphic
    original = c.service.prepare_native_body
    def prepare(owner, job):
        result = original(owner, job)
        with c.scope() as db:
            snapshot = json.loads(db.get(FeishuDeliveryDestinationDB, job.id).snapshot)
        if not job.document_id:
            image = snapshot['graphic_manifest']['parts'][0]['asset']['file_name']
            (c.folder / 'screenshots' / image).unlink()
            # A second preflight must reuse frozen bytes or refuse; no rerender.
            return original(owner, job)
        return result
    monkeypatch.setattr(c.service.__class__, 'prepare_native_body', lambda self, owner, job: prepare(owner, job))
    runtime.run_once()
    assert current(c)['phase'] == 'failed'
    assert not c.native and not any(e[0].startswith('create') for e in c.events)
