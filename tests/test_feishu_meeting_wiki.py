"""Offline container receipts; no CLI, Feishu, model, or runtime DB calls."""
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import multiprocessing
from types import SimpleNamespace
import time
import uuid

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.db import Base
from app.db_models import FeishuConnectionDB, FeishuDeliveryDB
from app.models.feishu_destination import FeishuDeliveryDestinationDB
from app.models.feishu_meeting_wiki import MeetingWikiContext, FeishuMeetingWikiContainerDB, FeishuMeetingWikiChildDB
from app.services import feishu_meeting_wiki as wiki
from app.services.feishu_service import FeishuError, FeishuService

OWNER = 'owner-a'
ROOT = dict(kind='wiki', space_id='space1', node_token='TVg0wVetniR8yikPVsAc6ejQnub')
TASK = str(uuid.uuid4())


class FakeService:
    normalize_destination = staticmethod(FeishuService.normalize_destination)
    config = SimpleNamespace(feishu_app_id='cli_app', feishu_tenant_key='tenant',
                             feishu_doc_base_url='https://company.feishu.cn')

    def __init__(self):
        self.calls = []
        self.context = MeetingWikiContext(owner=OWNER, task_id=TASK, canonical_task_id=TASK,
            source_sha256='a' * 64, recorded_at=datetime(2026, 10, 19, 9, 30, tzinfo=timezone.utc),
            meeting_topic='发布评审', summary_format='text', version_id='generated-7')

    def assert_delivery_connection(self, owner, snapshot):
        assert owner == OWNER

    def meeting_wiki_context(self, owner, job):
        return self.context

    def create_at_destination(self, owner, title, destination):
        # The durable claim AND child metadata precede the remote side effect.
        with wiki.session_scope() as db:
            row = db.scalar(select(FeishuMeetingWikiContainerDB).where(FeishuMeetingWikiContainerDB.state == 'creating'))
            assert row.state == 'creating' and row.lease_id and row.lease_until > time.time()
            assert db.scalar(select(FeishuMeetingWikiChildDB)) is not None
        self.calls.append((owner, title, destination))
        return 'document1', self.config.feishu_doc_base_url + '/wiki/container1'


@pytest.fixture
def setup(monkeypatch, tmp_path):
    path = tmp_path / 'wiki.db'
    engine = create_engine('sqlite:///' + str(path))
    Base.metadata.create_all(engine)

    @contextmanager
    def sessions():
        with Session(engine, expire_on_commit=False) as db, db.begin():
            yield db

    monkeypatch.setattr(wiki, 'session_scope', sessions)
    with sessions() as db:
        db.add(FeishuConnectionDB(owner=OWNER, tokens='synthetic', open_id='ou_sender', expired=False,
                                 preferences=json.dumps(dict(connection_id='connection1'))))
    service = FakeService()

    def job(**changes):
        identifier = str(uuid.uuid4())
        row = FeishuDeliveryDB(id=identifier, owner=OWNER, note_key='saved-' + identifier,
                              revision='r1', title='Frozen title', content='Frozen content',
                              document_id='', document_url='', status='queued')
        snapshot = dict(destination=ROOT, group_meeting_versions=True, open_id='ou_sender',
                        connection_id='connection1', app_id='cli_app', tenant_key='tenant')
        snapshot.update(changes)
        with sessions() as db:
            db.add(row)
            db.add(FeishuDeliveryDestinationDB(delivery_id=identifier, snapshot=json.dumps(snapshot)))
        return row

    yield SimpleNamespace(service=service, job=job, sessions=sessions, engine=engine, path=path)
    engine.dispose()


def test_actual_parent_and_explicit_child_metadata(setup):
    job = setup.job()
    parent = wiki.grouped_creation(OWNER, job, ROOT, setup.service)
    assert parent == dict(ROOT, node_token='container1')
    assert setup.service.calls == [(OWNER, '2026-10-19 09:30:00', ROOT)]
    with setup.sessions() as db:
        child = db.get(FeishuMeetingWikiChildDB, job.id)
        metadata = json.loads(child.snapshot)
        assert metadata['summary_format'] == 'text' and metadata['version_id'] == 'generated-7'
        assert metadata['task_id'] == TASK
        assert db.get(FeishuDeliveryDB, job.id).document_id == ''
        assert json.loads(db.get(FeishuDeliveryDestinationDB, job.id).snapshot)['destination'] == ROOT


def test_multiple_formats_and_child_tasks_reuse_one_meeting(setup):
    first = wiki.grouped_creation(OWNER, setup.job(), ROOT, setup.service)
    setup.service.context = setup.service.context.model_copy(update=dict(
        task_id=str(uuid.uuid4()), summary_format='html', version_id='generated-8', meeting_topic='另一标题'))
    assert wiki.grouped_creation(OWNER, setup.job(), ROOT, setup.service) == first
    assert len(setup.service.calls) == 1
    with setup.sessions() as db:
        assert len(db.scalars(select(FeishuMeetingWikiChildDB)).all()) == 2


@pytest.mark.parametrize('field', ['canonical_task_id', 'source_sha256', 'destination', 'connection_id', 'app_id', 'tenant_key', 'open_id'])
def test_scope_isolation_never_groups_by_title(setup, field):
    wiki.grouped_creation(OWNER, setup.job(), ROOT, setup.service)
    root, changes = dict(ROOT), {}
    if field in ('canonical_task_id', 'source_sha256'):
        value = str(uuid.uuid4()) if field == 'canonical_task_id' else 'b' * 64
        setup.service.context = setup.service.context.model_copy(update={field: value})
    elif field == 'destination':
        root['node_token'] = 'anotherRoot'
        changes['destination'] = root
    else:
        values = dict(connection_id='connection2', app_id='cli_second', tenant_key='tenant2', open_id='ou_second')
        changes[field] = values[field]
        with setup.sessions() as db:
            account = db.get(FeishuConnectionDB, OWNER)
            if field == 'connection_id': account.preferences = json.dumps(dict(connection_id=values[field]))
            if field == 'open_id': account.open_id = values[field]
        if field in ('app_id', 'tenant_key'):
            setup.service.config = SimpleNamespace(**{**vars(FakeService.config), 'feishu_' + field: values[field]})
    wiki.grouped_creation(OWNER, setup.job(**changes), root, setup.service)
    assert len(setup.service.calls) == 2


@pytest.mark.parametrize('flag', [None, False])
def test_legacy_and_manual_passthrough_never_load_context(setup, flag):
    job = setup.job(group_meeting_versions=flag)
    setup.service.meeting_wiki_context = lambda *args: pytest.fail('legacy context read')
    assert wiki.grouped_creation(OWNER, job, ROOT, setup.service) == ROOT
    assert not setup.service.calls


@pytest.mark.parametrize('damage', ['owner', 'destination', 'binding', 'old_create', 'missing_context', 'bad_flag'])
def test_fail_closed_before_any_write(setup, damage):
    job = setup.job()
    owner, root = OWNER, ROOT
    if damage == 'owner': owner = 'other'
    if damage == 'destination': root = dict(ROOT, node_token='forged')
    if damage == 'missing_context': setup.service.meeting_wiki_context = None
    with setup.sessions() as db:
        if damage == 'old_create': db.get(FeishuDeliveryDB, job.id).document_id = '__creating__'
        if damage in ('binding', 'bad_flag'):
            row = db.get(FeishuDeliveryDestinationDB, job.id)
            data = json.loads(row.snapshot)
            data['connection_id' if damage == 'binding' else 'group_meeting_versions'] = 'forged'
            row.snapshot = json.dumps(data)
    with pytest.raises(FeishuError): wiki.grouped_creation(owner, job, root, setup.service)
    assert not setup.service.calls


@pytest.mark.parametrize('failure', ['timeout', 'unexpected', 'malformed', 'definite', 'interrupt'])
def test_no_replay_after_any_dispatched_create_failure(setup, failure):
    job = setup.job()
    calls = []
    def create(*args):
        calls.append(args)
        if failure == 'timeout': raise FeishuError('synthetic', 502, uncertain=True)
        if failure == 'unexpected': raise RuntimeError('private endpoint or credentials')
        if failure == 'interrupt': raise KeyboardInterrupt()
        if failure == 'definite': raise FeishuError('denied', 403)
        return 'doc', 'https://evil.example/wiki/container'
    setup.service.create_at_destination = create
    with pytest.raises((FeishuError, KeyboardInterrupt)):
        wiki.grouped_creation(OWNER, job, ROOT, setup.service)
    with pytest.raises(FeishuError): wiki.grouped_creation(OWNER, setup.job(), ROOT, setup.service)
    assert len(calls) == 1
    with setup.sessions() as db:
        row = db.scalar(select(FeishuMeetingWikiContainerDB))
        assert row.state == ('failed' if failure == 'definite' else 'unknown')
        assert 'private' not in row.error_code


def test_live_lease_blocks_and_expired_lease_becomes_unknown(setup):
    job = setup.job()
    def create(*args):
        with pytest.raises(FeishuError) as error:
            wiki.grouped_creation(OWNER, setup.job(), ROOT, setup.service)
        assert error.value.code == 'meeting_container_busy'
        with setup.sessions() as db:
            db.scalar(select(FeishuMeetingWikiContainerDB)).lease_until = 1
        with pytest.raises(FeishuError) as error:
            wiki.grouped_creation(OWNER, setup.job(), ROOT, setup.service)
        assert error.value.code == 'meeting_container_unknown'
        return 'doc', 'https://company.feishu.cn/wiki/late'
    setup.service.create_at_destination = create
    with pytest.raises(FeishuError): wiki.grouped_creation(OWNER, job, ROOT, setup.service)
    with setup.sessions() as db:
        assert db.scalar(select(FeishuMeetingWikiContainerDB)).state == 'unknown'


def test_job_metadata_cannot_be_rebound_to_another_version(setup):
    job = setup.job()
    wiki.grouped_creation(OWNER, job, ROOT, setup.service)
    setup.service.context = setup.service.context.model_copy(update={'version_id': 'different'})
    with pytest.raises(FeishuError) as error: wiki.grouped_creation(OWNER, job, ROOT, setup.service)
    assert error.value.code == 'meeting_context_changed'
    assert len(setup.service.calls) == 1


def _race_worker(path, identifier, task, gate, results):
    engine = create_engine('sqlite:///' + str(path))
    @contextmanager
    def sessions():
        with Session(engine, expire_on_commit=False) as db, db.begin(): yield db
    wiki.session_scope = sessions
    service = FakeService()
    service.context = service.context.model_copy(update=dict(task_id=task, canonical_task_id=task))
    def create(*args):
        results.put('POST')
        time.sleep(0.3)
        return 'doc', 'https://company.feishu.cn/wiki/raceParent'
    service.create_at_destination = create
    with sessions() as db:
        job = db.get(FeishuDeliveryDB, identifier)
        db.expunge(job)
    gate.wait(15)
    try:
        wiki.grouped_creation(OWNER, job, ROOT, service)
        results.put('confirmed')
    except FeishuError as error:
        results.put(error.code)
    finally: engine.dispose()


def test_independent_processes_dispatch_exactly_one_container(setup):
    jobs = [setup.job(), setup.job()]
    mp = multiprocessing.get_context('spawn')
    gate, results = mp.Event(), mp.Queue()
    workers = [mp.Process(target=_race_worker, args=(setup.path, j.id, TASK, gate, results)) for j in jobs]
    for worker in workers: worker.start()
    gate.set()
    for worker in workers:
        worker.join(25)
        if worker.is_alive(): worker.terminate(); worker.join(); pytest.fail('worker did not finish')
        assert worker.exitcode == 0
    messages = [results.get(timeout=5) for _ in range(3)]
    assert messages.count('POST') == 1
    assert all(item in ('POST', 'confirmed', 'meeting_container_busy') for item in messages)
    with setup.sessions() as db:
        assert sorted(db.scalars(select(FeishuMeetingWikiChildDB.ordinal)).all()) == [1, 2]


def test_context_rejects_unknown_time_and_implicit_version():
    values = FakeService().context.model_dump()
    assert MeetingWikiContext(**{**values, 'recorded_at': None}).recorded_at is None
    for patch in (dict(recorded_at=datetime(2026, 1, 1)),
                  dict(version_id=''), dict(summary_format=''), dict(source_sha256='wrong')):
        with pytest.raises(ValueError): MeetingWikiContext(**{**values, **patch})


def test_known_parent_readback_does_not_call_service_or_change_old_receipts(setup):
    job = setup.job()
    parent = wiki.grouped_creation(OWNER, job, ROOT, setup.service)
    with setup.sessions() as db:
        key = db.get(FeishuMeetingWikiChildDB, job.id).scope_key
        original = db.get(FeishuDeliveryDestinationDB, job.id).snapshot
    assert wiki.child_destination(OWNER, job.id) == parent
    assert wiki.container_receipt(OWNER, key)['document_id'] == 'document1'
    with pytest.raises(FeishuError): wiki.child_destination('another-owner', job.id)
    with pytest.raises(FeishuError): wiki.container_receipt('another-owner', key)
    with setup.sessions() as db:
        assert db.get(FeishuDeliveryDestinationDB, job.id).snapshot == original
    assert len(setup.service.calls) == 1


@pytest.mark.parametrize('damage', [None, 'space_id', 'parent_node_token', 'title', 'obj_type', 'node_type', 'node_token', 'obj_token'])
def test_unknown_parent_explicit_get_recovery_checks_real_root_and_object(setup, damage):
    job = setup.job()
    def timeout(*args): raise FeishuError('timeout', 502, uncertain=True)
    setup.service.create_at_destination = timeout
    with pytest.raises(FeishuError): wiki.grouped_creation(OWNER, job, ROOT, setup.service)
    with setup.sessions() as db:
        receipt = db.scalar(select(FeishuMeetingWikiContainerDB))
        key, title = receipt.scope_key, receipt.title
        frozen_job_receipt = db.get(FeishuDeliveryDestinationDB, job.id).snapshot
    node = dict(space_id=ROOT['space_id'], parent_node_token=ROOT['node_token'],
                node_token='recovered', obj_type='docx', node_type='origin', obj_token='realDoc', title=title)
    if damage: node[damage] = 'wrong' if damage != 'obj_token' else ''
    calls = []
    def request(method, path, **kwargs):
        calls.append((method, path, kwargs))
        assert method == 'GET'
        return dict(node=node)
    setup.service.request = request
    setup.service.user_token = lambda owner: 'synthetic'
    if damage:
        with pytest.raises(FeishuError): wiki.recover_container(OWNER, key, 'recovered', setup.service)
        assert wiki.container_receipt(OWNER, key)['state'] == 'unknown'
    else:
        parent = wiki.recover_container(OWNER, key, 'recovered', setup.service)
        assert parent == dict(ROOT, node_token='recovered')
        assert wiki.child_destination(OWNER, job.id) == parent
        assert wiki.grouped_creation(OWNER, setup.job(), ROOT, setup.service) == parent
        with pytest.raises(FeishuError): wiki.recover_container(OWNER, key, 'recovered', setup.service)
    assert len(calls) == 1
    with setup.sessions() as db:
        assert db.get(FeishuDeliveryDestinationDB, job.id).snapshot == frozen_job_receipt


def test_confirmed_parent_cannot_be_used_with_old_binding(setup):
    wiki.grouped_creation(OWNER, setup.job(), ROOT, setup.service)
    with setup.sessions() as db:
        db.get(FeishuConnectionDB, OWNER).preferences = json.dumps(dict(connection_id='reconnected'))
    with pytest.raises(FeishuError) as error: wiki.grouped_creation(OWNER, setup.job(), ROOT, setup.service)
    assert error.value.code == 'connection_changed'
    assert len(setup.service.calls) == 1


def test_context_is_revalidated_even_for_pydantic_model_copy(setup):
    setup.service.context = setup.service.context.model_copy(update={'recorded_at': datetime(2026, 1, 1)})
    with pytest.raises(FeishuError): wiki.grouped_creation(OWNER, setup.job(), ROOT, setup.service)
    assert not setup.service.calls


@pytest.mark.parametrize('damage', [None, 'owner', 'hash', 'chain', 'workflow', 'body'])
def test_saved_note_context_reuses_owner_bound_single_hop_helper(setup, monkeypatch, tmp_path, damage):
    from app.config import settings
    from app.db_models import NoteDB
    from app.routers import note_library
    from app.services.task_artifact_service import TaskArtifactService

    root = tmp_path / 'output'
    root.mkdir()
    parent, child = str(uuid.uuid4()), str(uuid.uuid4())
    original, derivative = root / parent, root / child
    original.mkdir()
    derivative.mkdir()
    for folder, identifier in ((original, parent), (derivative, child)):
        (folder / '.task_id').write_text(identifier, encoding='utf-8')
        (folder / 'recording_owner').write_text(OWNER, encoding='utf-8')
    (original / 'source_media.json').write_text(json.dumps(dict(sha256='a' * 64)), encoding='utf-8')
    (original / 'request.json').write_text(json.dumps(dict(request=dict(workflow='meeting'))), encoding='utf-8')
    reference = dict(version=1, owner=OWNER, parent_task_id=parent, source_version='a' * 64)
    if damage == 'owner': reference['owner'] = 'someone-else'
    if damage == 'hash': reference['source_version'] = 'b' * 64
    if damage == 'chain': (original / 'source_reference.json').write_text('{}', encoding='utf-8')
    if damage == 'workflow':
        (original / 'request.json').write_text(json.dumps(dict(request=dict(workflow='note_organization'))), encoding='utf-8')
    (derivative / 'source_reference.json').write_text(json.dumps(reference), encoding='utf-8')
    monkeypatch.setattr(settings, 'output_dir', root)
    monkeypatch.setattr(note_library, '_artifact_service', TaskArtifactService(root))
    job = setup.job()
    with setup.sessions() as db:
        db.add(NoteDB(id=job.note_key, created_by=OWNER, task_id=child, title=job.title,
                      content=job.content if damage != 'body' else 'edited', source_type='meeting_video',
                      scope='personal', status='done', generation_client='desktop'))
    values = dict(recorded_at=FakeService().context.recorded_at, meeting_topic='可信主题',
                  summary_format='html', version_id='saved-version-9')
    if damage:
        with pytest.raises(FeishuError): wiki.context_for_saved_note(OWNER, job, **values)
    else:
        # No media is created or required for metadata-only grouping evidence.
        context = wiki.context_for_saved_note(OWNER, job, **values)
        assert context.canonical_task_id == parent and context.task_id == child
        assert context.source_sha256 == 'a' * 64 and context.summary_format == 'html'


def test_owner_scope_isolation_with_identical_title_and_source(setup):
    wiki.grouped_creation(OWNER, setup.job(), ROOT, setup.service)
    with setup.sessions() as db:
        db.add(FeishuConnectionDB(owner='owner-b', tokens='synthetic', open_id='ou_sender', expired=False,
                                 preferences=json.dumps(dict(connection_id='connection1'))))
    job = setup.job()
    with setup.sessions() as db:
        db.get(FeishuDeliveryDB, job.id).owner = 'owner-b'
    job.owner = 'owner-b'
    setup.service.context = setup.service.context.model_copy(update=dict(owner='owner-b'))
    setup.service.assert_delivery_connection = lambda *args: None
    wiki.grouped_creation('owner-b', job, ROOT, setup.service)
    assert len(setup.service.calls) == 2


def test_no_recording_time_cannot_use_a_summary_title_as_a_date(setup):
    setup.service.context = setup.service.context.model_copy(update=dict(
        recorded_at=None, meeting_topic='2026-10-18 16:20｜用户保存的会议主题'))
    wiki.grouped_creation(OWNER, setup.job(), ROOT, setup.service)
    assert setup.service.calls[0][1] == '录制时间未记录'


def test_full_length_summary_title_does_not_name_the_meeting(setup):
    topic = '主' * 500
    setup.service.context = setup.service.context.model_copy(update=dict(recorded_at=None, meeting_topic=topic))
    wiki.grouped_creation(OWNER, setup.job(), ROOT, setup.service)
    assert setup.service.calls[0][1] == '录制时间未记录'


def test_format_ordinals_are_real_stable_separate_and_not_title_based(setup):
    jobs = []
    for form in ('text', 'text', 'html', 'illustrated', 'text'):
        job = setup.job()
        setup.service.context = setup.service.context.model_copy(update=dict(
            summary_format=form, version_id=str(uuid.uuid4())))
        wiki.grouped_creation(OWNER, job, ROOT, setup.service)
        jobs.append(job)
    assert [wiki.child_title(OWNER, job.id) for job in jobs] == [
        '文字｜V1', '文字｜V2', 'HTML｜V1', '图文｜V1', '文字｜V3']
    for job in jobs:
        assert wiki.child_title(OWNER, job.id) == wiki.child_title(OWNER, job.id)
        assert wiki.child_metadata(OWNER, job.id)['version_id']
    assert len(setup.service.calls) == 1
    with pytest.raises(FeishuError): wiki.child_title('another-owner', jobs[0].id)


@pytest.mark.parametrize('form,label', list(wiki.FORMAT_LABELS.items()))
@pytest.mark.parametrize('depth,depth_label', [('brief', '摘要'), ('concise', '精简'), ('detailed', '详细')])
def test_actual_service_format_depth_hook_produces_readable_child_labels(setup, monkeypatch, tmp_path, form, label, depth, depth_label):
    """Exercise the production host hook with its real owner/task sidecar read."""
    from app.db_models import NoteDB
    from app.services import feishu_service, task_artifact_service
    artifacts = task_artifact_service.TaskArtifactService(tmp_path / 'artifacts')
    folder = artifacts.create_task_dir(TASK)
    (folder / 'recording_owner').write_text(OWNER, encoding='utf-8')
    (folder / '.task_id').write_text(TASK, encoding='utf-8')
    artifacts.write_json(folder / 'status.json', {'status': 'success'})
    artifacts.write_json(folder / 'summary_presentation.json', dict(
        protocol=1, task_id=TASK, presentation=form, content_depth=depth))
    job = setup.job()
    with setup.sessions() as db:
        db.add(NoteDB(id=job.note_key, created_by=OWNER, task_id=TASK, title=job.title,
                      content=job.content, scope='personal', status='done', source_type='meeting_video'))
    monkeypatch.setattr(feishu_service, 'session_scope', setup.sessions)
    monkeypatch.setattr(task_artifact_service, 'TaskArtifactService', lambda: artifacts)

    def saved_context(owner, frozen_job, **metadata):
        assert owner == OWNER and frozen_job.id == job.id
        assert metadata['version_id'] == TASK
        return setup.service.context.model_copy(update={
            'summary_format': metadata['summary_format'], 'version_id': metadata['version_id']})

    monkeypatch.setattr(wiki, 'context_for_saved_note', saved_context)
    context = FeishuService.meeting_wiki_context(setup.service, OWNER, job)
    assert context.summary_format == f'{form}:{depth}'
    setup.service.context = context
    wiki.grouped_creation(OWNER, job, ROOT, setup.service)
    assert wiki.child_title(OWNER, job.id) == f'{label}·{depth_label}｜V1'
    metadata = wiki.child_metadata(OWNER, job.id)
    assert metadata['format_label'] == f'{label}·{depth_label}'
    assert metadata['summary_format'] == f'{form}:{depth}' and metadata['version_id'] == TASK
    assert len(setup.service.calls) == 1  # Synthetic parent adapter, no CLI/network.


@pytest.mark.parametrize('damage', [
    'missing', 'malformed', 'foreign_task', 'wrong_protocol', 'foreign_owner',
    'missing_form', 'missing_depth', 'invalid_form', 'invalid_depth', 'non_string_form',
    'protocol_true', 'protocol_false', 'protocol_float', 'protocol_string',
])
def test_actual_grouping_hook_never_guesses_missing_or_unverified_presentation(setup, monkeypatch, tmp_path, damage):
    from app.db_models import NoteDB
    from app.services import feishu_service, task_artifact_service
    artifacts = task_artifact_service.TaskArtifactService(tmp_path / 'artifacts')
    folder = artifacts.create_task_dir(TASK)
    (folder / 'recording_owner').write_text('another-owner' if damage == 'foreign_owner' else OWNER,
                                          encoding='utf-8')
    (folder / '.task_id').write_text(TASK, encoding='utf-8')
    payload = dict(protocol=1, task_id=TASK, presentation='html', content_depth='concise')
    if damage == 'foreign_task': payload['task_id'] = str(uuid.uuid4())
    if damage == 'wrong_protocol': payload['protocol'] = 9
    invalid_protocols = dict(protocol_true=True, protocol_false=False, protocol_float=1.0, protocol_string='1')
    if damage in invalid_protocols: payload['protocol'] = invalid_protocols[damage]
    if damage == 'missing_form': payload.pop('presentation')
    if damage == 'missing_depth': payload.pop('content_depth')
    if damage == 'invalid_form': payload['presentation'] = 'guessed'
    if damage == 'invalid_depth': payload['content_depth'] = None
    if damage == 'non_string_form': payload['presentation'] = []
    if damage != 'missing':
        (folder / 'summary_presentation.json').write_text(
            '{' if damage == 'malformed' else json.dumps(payload), encoding='utf-8')
    job = setup.job()
    with setup.sessions() as db:
        db.add(NoteDB(id=job.note_key, created_by=OWNER, task_id=TASK, title=job.title,
                      content=job.content, scope='personal', status='done', source_type='meeting_video'))
    monkeypatch.setattr(feishu_service, 'session_scope', setup.sessions)
    monkeypatch.setattr(task_artifact_service, 'TaskArtifactService', lambda: artifacts)
    monkeypatch.setattr(wiki, 'context_for_saved_note', lambda owner, job, **metadata:
                        setup.service.context.model_copy(update=metadata))
    monkeypatch.setattr(setup.service, 'meeting_wiki_context', lambda owner, job:
                        FeishuService.meeting_wiki_context(setup.service, owner, job))
    with pytest.raises(FeishuError) as caught:
        wiki.grouped_creation(OWNER, job, ROOT, setup.service)
    assert caught.value.code == 'meeting_context_unverified'
    assert setup.service.calls == []
    with setup.sessions() as db:
        assert db.query(FeishuMeetingWikiContainerDB).count() == 0
        assert db.query(FeishuMeetingWikiChildDB).count() == 0


@pytest.mark.parametrize('form,label', list(wiki.FORMAT_LABELS.items()))
def test_legacy_single_format_labels_remain_compatible(setup, form, label):
    setup.service.context = setup.service.context.model_copy(update={'summary_format': form})
    job = setup.job()
    wiki.grouped_creation(OWNER, job, ROOT, setup.service)
    assert wiki.child_title(OWNER, job.id) == f'{label}｜V1'
    assert wiki.child_metadata(OWNER, job.id)['format_label'] == label


def test_format_label_fix_never_renames_existing_remote_or_frozen_child_titles(setup):
    setup.service.context = setup.service.context.model_copy(update={'summary_format': 'text:concise'})
    job = setup.job()
    parent = wiki.grouped_creation(OWNER, job, ROOT, setup.service)
    with setup.sessions() as db:
        child = db.get(FeishuMeetingWikiChildDB, job.id)
        child.title = 'text:concise｜V1'  # A pre-fix remote/frozen title.
        original_snapshot = child.snapshot
    calls = list(setup.service.calls)
    assert wiki.grouped_creation(OWNER, job, ROOT, setup.service) == parent
    assert wiki.child_title(OWNER, job.id) == 'text:concise｜V1'
    assert wiki.child_metadata(OWNER, job.id)['format_label'] == '文字·精简'
    assert setup.service.calls == calls
    with setup.sessions() as db:
        assert db.get(FeishuMeetingWikiChildDB, job.id).snapshot == original_snapshot
