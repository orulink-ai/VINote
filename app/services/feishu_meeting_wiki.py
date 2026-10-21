"""Durable per-meeting Wiki parents; no body writes, inference, or auto replay.

Integration (all hooks are server internal):
* Import models before init_db/create_all.
* Freeze group_meeting_versions: bool (default False) AND app_id with the
  existing delivery destination/connection snapshot. Never retrofit old jobs.
* Supply service.meeting_wiki_context(owner, job) -> MeetingWikiContext using
  trusted owner/task records. context_for_saved_note below reuses the existing
  single-hop relationship verifier and is suitable for device-owned notes.
* BEFORE the child's '__creating__' checkpoint, call grouped_creation and
  pass its returned destination to the existing create_at_destination path.
  Use child_title(owner, job.id) as the remote child title; its per-format
  ordinal is allocated under a database lock and persists across restarts.
  Persist/use that effective destination for child permission/recovery reads,
  separate from the immutable root destination. child_destination is read-only.

Only a fresh database INSERT may authorize the parent POST. An expired lease
becomes unknown, never a new lease. Even definite parent failures need explicit
operator resolution; ordinary process retries cannot issue another parent POST.
"""
import hashlib
import json
import re
import time
from urllib.parse import urlsplit
import uuid

from pydantic import ValidationError
from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.db import session_scope
from app.db_models import FeishuConnectionDB, FeishuDeliveryDB, NoteDB
from app.models.feishu_destination import FeishuDeliveryDestinationDB
from app.models.feishu_meeting_wiki import (
    FeishuMeetingWikiChildDB as Child,
    FeishuMeetingWikiContainerDB as Container,
    MeetingWikiContext,
)
from app.services import feishu_auto_policy
from app.services.feishu_service import FeishuError

LEASE_SECONDS = 300
FORMAT_LABELS = dict(text='文字', illustrated='图文', html='HTML', comic='漫画', infographic='信息图')
DEPTH_LABELS = dict(brief='摘要', concise='精简', detailed='详细')


def _format_label(value):
    form, separator, depth = value.partition(':')
    if separator and form in FORMAT_LABELS and depth in DEPTH_LABELS:
        return f'{FORMAT_LABELS[form]}·{DEPTH_LABELS[depth]}'
    return FORMAT_LABELS.get(value, value)


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def _digest(value):
    return hashlib.sha256(_json(value).encode('utf-8')).hexdigest()


def _error(code, message='会议归组信息尚不能核验，请保留原交付记录。', *, uncertain=False):
    return FeishuError(message, 409, uncertain=uncertain, code=code)


def _owned_job(db, owner, job):
    row = db.get(FeishuDeliveryDB, job.id)
    if not row or row.owner != owner or job.owner != owner:
        raise _error('meeting_job_not_found')
    if any(getattr(job, key) != getattr(row, key) for key in ('note_key', 'revision', 'title', 'content')):
        raise _error('meeting_context_changed')
    return row


def _snapshot(db, owner, job):
    _owned_job(db, owner, job)
    row = db.get(FeishuDeliveryDestinationDB, job.id)
    try:
        value = json.loads(row.snapshot) if row else {}
        if not isinstance(value, dict): raise ValueError()
        return value
    except (ValueError, TypeError):
        raise _error('meeting_snapshot_invalid') from None


def _binding(owner, snapshot, service):
    expected = dict(owner=owner, connection_id=snapshot.get('connection_id'),
                    sender_open_id=snapshot.get('open_id'), app_id=snapshot.get('app_id'),
                    tenant_key=snapshot.get('tenant_key'))
    if any(not isinstance(v, str) or not v or len(v) > 200 for v in expected.values()):
        raise _error('meeting_binding_missing')
    if (expected['app_id'] != service.config.feishu_app_id
            or expected['tenant_key'] != service.config.feishu_tenant_key):
        raise _error('connection_changed')
    service.assert_delivery_connection(owner, snapshot)
    with session_scope() as db:
        account = db.get(FeishuConnectionDB, owner)
        try:
            valid = (account and account.tokens and not account.expired
                     and account.open_id == expected['sender_open_id']
                     and json.loads(account.preferences)['connection_id'] == expected['connection_id'])
        except (KeyError, ValueError, TypeError):
            valid = False
        if not valid: raise _error('connection_changed')
    return expected


def context_for_saved_note(owner, job, *, recorded_at=None, meeting_topic, summary_format, version_id):
    """Build the hook result from a device note and verified task relationship.

    Format/version arguments MUST come from trusted saved task/version metadata.
    The capture clock is always read from the canonical recording; a legacy
    recorded_at argument cannot override it. No fallback uses title matching,
    generation time, old workspace sync data, or filesystem timestamps. Missing
    capture time remains None. Current
    note body must exactly match the frozen publication; historical versions
    need a separate owner-authorized hook rather than a guessed current note.
    Metadata-only relationships survive missing original media, as in the
    existing note-library helper; this grants no media or generation authority.
    """
    from app.routers.note_library import _with_meeting_source
    from app.services.note_repository import NoteRepository
    from app.services.task_artifact_service import TaskArtifactService
    from app.services.task_generation_context import _read_json

    with session_scope() as db:
        _owned_job(db, owner, job)
        note = db.get(NoteDB, job.note_key)
        if (not note or note.created_by != owner or note.scope != 'personal' or note.status != 'done'
                or note.title != job.title or note.content != job.content):
            raise _error('meeting_note_unverified')
        response = NoteRepository._to_response(note)
    related = _with_meeting_source(response, owner).meeting_source
    if not related or related.owner_id != owner:
        raise _error('meeting_source_unverified')
    artifacts = TaskArtifactService()
    folder = artifacts.find_task_dir(related.canonical_task_id)
    manifest = _read_json(folder / 'source_media.json')
    capture_time = related.recording_started_at
    return MeetingWikiContext(owner=owner, task_id=response.task_id,
        canonical_task_id=related.canonical_task_id, source_sha256=manifest.get('sha256'),
        recorded_at=capture_time.astimezone() if capture_time else None,
        meeting_topic=meeting_topic,
        summary_format=summary_format, version_id=version_id)


def _insert_once(db, model, values, primary_key):
    dialect = db.get_bind().dialect.name
    insert = sqlite_insert if dialect == 'sqlite' else pg_insert if dialect == 'postgresql' else None
    if insert is None:
        raise _error('meeting_database_unsupported')
    result = db.execute(insert(model).values(**values).on_conflict_do_nothing(index_elements=[primary_key]))
    return result.rowcount == 1


def _reserve(owner, job, scope, context, snapshot):
    key, lease, now = _digest(scope), str(uuid.uuid4()), time.time()
    title = context.recorded_at.strftime('%Y-%m-%d %H:%M:%S') if context.recorded_at else '录制时间未记录'
    if len(title) > 500: raise _error('meeting_context_unverified')
    child = dict(protocol=1, scope_key=key, **context.model_dump(mode='json'),
                 delivery_revision=job.revision, content_sha256=hashlib.sha256(job.content.encode()).hexdigest(),
                 title_sha256=hashlib.sha256(job.title.encode()).hexdigest())
    child_json = _json(child)
    with session_scope() as db:
        row = _owned_job(db, owner, job)
        if row.document_id:
            raise _error('meeting_child_already_started')
        if _snapshot(db, owner, job) != snapshot:
            raise _error('meeting_context_changed')
        created = _insert_once(db, Container, dict(scope_key=key, owner=owner, scope_json=_json(scope),
            title=title,
            state='creating', lease_id=lease, lease_until=now + LEASE_SECONDS,
            node_token='', document_id='', document_url='', error_code=''), 'scope_key')
        # PostgreSQL row lock and SQLite writer lock BEFORE max/insert. The
        # unique constraint is a second guard; no Python process-local counter.
        db.execute(update(Container).where(Container.scope_key == key).values(title=Container.title))
        saved = db.get(Child, job.id)
        if saved is None:
            ordinal = (db.scalar(select(func.max(Child.ordinal)).where(
                Child.scope_key == key, Child.summary_format == context.summary_format)) or 0) + 1
            label = _format_label(context.summary_format)
            _insert_once(db, Child, dict(delivery_id=job.id, scope_key=key, snapshot=child_json,
                summary_format=context.summary_format, ordinal=ordinal, title=f'{label}｜V{ordinal}'), 'delivery_id')
        saved = db.get(Child, job.id)
        if saved.scope_key != key or saved.snapshot != child_json or saved.summary_format != context.summary_format:
            raise _error('meeting_context_changed')
        receipt = db.get(Container, key)
        if receipt.owner != owner or receipt.scope_json != _json(scope):
            raise _error('meeting_context_changed')
        # Fully detached after commit: no network I/O under a DB transaction.
        result = {col.name: getattr(receipt, col.name) for col in Container.__table__.columns}
    return created, result


def _unknown_expired(receipt):
    with session_scope() as db:
        db.execute(update(Container).where(Container.scope_key == receipt['scope_key'],
            Container.state == 'creating', Container.lease_id == receipt['lease_id'],
            Container.lease_until <= time.time()).values(state='unknown', error_code='meeting_container_unknown'))


def _existing(receipt):
    if receipt['state'] == 'confirmed':
        return {**json.loads(receipt['scope_json'])['destination'], 'node_token': receipt['node_token']}
    if receipt['state'] == 'creating' and receipt['lease_until'] > time.time():
        raise _error('meeting_container_busy', '会议目录正在创建，请稍后查询原交付记录。')
    if receipt['state'] == 'creating':
        _unknown_expired(receipt)
    if receipt['state'] == 'failed':
        raise _error('meeting_container_failed', '会议目录创建未完成，请核验原回执后处理。')
    raise _error('meeting_container_unknown', '会议目录创建结果未确认，请核验原节点，禁止重复创建。', uncertain=True)


def _created_node(document_id, url, service):
    if not isinstance(document_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,200}', document_id):
        raise _error('meeting_container_unknown', uncertain=True)
    try:
        actual, base = urlsplit(url), urlsplit(service.config.feishu_doc_base_url)
        match = re.fullmatch(r'/wiki/([A-Za-z0-9_-]{1,200})', actual.path)
        if (actual.scheme != 'https' or actual.netloc != base.netloc or actual.username or actual.password
                or actual.query or actual.fragment or not match or len(url) > 500):
            raise ValueError()
        return match.group(1)
    except (TypeError, ValueError, AttributeError):
        raise _error('meeting_container_unknown', uncertain=True) from None


def grouped_creation(owner, job, destination, service):
    """Return a standard actual parent destination; never create a child doc.

    Only the frozen explicit True opts in. Legacy/manual jobs pass through
    without context, connection, or network reads. New grouped jobs require a
    Wiki destination and full binding. Never call after the child's create
    sentinel, and never catch an unknown parent result to fall back to root.
    """
    with session_scope() as db:
        snapshot = _snapshot(db, owner, job)
    flag = snapshot.get('group_meeting_versions', False)
    if flag is False or flag is None:
        return destination
    if flag is not True:
        raise _error('meeting_policy_invalid')
    keys = {'kind', 'folder_token', 'space_id', 'node_token'}
    target = service.normalize_destination({key: value for key, value in destination.items() if key in keys})
    frozen_target = service.normalize_destination({key: value for key, value in snapshot.get('destination', {}).items() if key in keys})
    if target['kind'] != 'wiki' or target != frozen_target:
        raise _error('meeting_destination_mismatch')
    binding = _binding(owner, snapshot, service)
    hook = getattr(service, 'meeting_wiki_context', None)
    if not callable(hook): raise _error('meeting_context_unavailable')
    try:
        raw = hook(owner, job)
        # Revalidate even a model_copy-produced instance; it bypasses validators.
        context = MeetingWikiContext.model_validate(raw.model_dump() if isinstance(raw, MeetingWikiContext) else raw)
    except (ValidationError, ValueError, TypeError):
        raise _error('meeting_context_unverified') from None
    if context.owner != owner: raise _error('meeting_context_unverified')
    scope = dict(protocol=1, owner=owner, canonical_task_id=context.canonical_task_id,
                 source_sha256=context.source_sha256, binding=binding, destination=target)
    created, receipt = _reserve(owner, job, scope, context, snapshot)
    if not created: return _existing(receipt)
    execution = feishu_auto_policy.active_delivery.set((owner, snapshot))
    try:
        _binding(owner, snapshot, service)
        if hasattr(service, '_check_automatic_delivery'):
            service._check_automatic_delivery(owner, job)
        document_id, url = service.create_at_destination(owner, receipt['title'], target)
        node = _created_node(document_id, url, service)
        with session_scope() as db:
            result = db.execute(update(Container).where(Container.scope_key == receipt['scope_key'],
                Container.owner == owner, Container.state == 'creating', Container.lease_id == receipt['lease_id'])
                .values(state='confirmed', node_token=node, document_id=document_id, document_url=url,
                        lease_until=0, error_code=''))
            if result.rowcount != 1: raise _error('meeting_container_unknown', uncertain=True)
        return {**target, 'node_token': node}
    except BaseException as exc:
        definite = isinstance(exc, FeishuError) and not exc.uncertain
        # Never serialize raw exception text, meeting body, endpoint or tokens.
        with session_scope() as db:
            db.execute(update(Container).where(Container.scope_key == receipt['scope_key'],
                Container.owner == owner, Container.state == 'creating', Container.lease_id == receipt['lease_id'])
                .values(state='failed' if definite else 'unknown', lease_until=0,
                        error_code='meeting_container_failed' if definite else 'meeting_container_unknown'))
        if not isinstance(exc, Exception): raise
        if definite: raise
        raise _error('meeting_container_unknown', '会议目录创建结果未确认，请核验原节点，禁止重复创建。', uncertain=True) from None
    finally:
        feishu_auto_policy.active_delivery.reset(execution)


def child_destination(owner, job_id):
    """Read effective parent for existing child permission/recovery, no POST."""
    with session_scope() as db:
        job = db.get(FeishuDeliveryDB, job_id)
        child = db.get(Child, job_id)
        if not job or job.owner != owner or not child:
            raise _error('meeting_job_not_found')
        receipt = db.get(Container, child.scope_key)
        if not receipt or receipt.owner != owner: raise _error('meeting_job_not_found')
        result = {col.name: getattr(receipt, col.name) for col in Container.__table__.columns}
    return _existing(result)


def child_metadata(owner, job_id):
    """Read frozen format/version and DB-allocated ordinal, never infer V1."""
    with session_scope() as db:
        job = db.get(FeishuDeliveryDB, job_id)
        child = db.get(Child, job_id)
        if not job or job.owner != owner or not child: raise _error('meeting_job_not_found')
        receipt = db.get(Container, child.scope_key)
        if not receipt or receipt.owner != owner: raise _error('meeting_job_not_found')
        return {**json.loads(child.snapshot), 'ordinal': child.ordinal,
                'revision_label': f'V{child.ordinal}', 'child_title': child.title,
                'format_label': _format_label(child.summary_format)}


def child_title(owner, job_id):
    """Use after grouped_creation, before the original child create checkpoint.

    Its value is frozen on the first grouping claim. Do not change job.title or
    the old receipt to match it; pass as the create title and use this projection
    for explicit child recovery title validation. Version ordinals count durable
    child reservations, including unknown/failed ones, and are never recycled.
    """
    return child_metadata(owner, job_id)['child_title']


def container_receipt(owner, scope_key):
    """Owner-scoped exact readback only; never rewrites a legacy receipt."""
    with session_scope() as db:
        row = db.get(Container, scope_key)
        if not row or row.owner != owner: raise _error('meeting_job_not_found')
        return dict(protocol=1, scope_key=row.scope_key, state=row.state,
                    title=row.title, node_token=row.node_token, document_id=row.document_id,
                    document_url=row.document_url, error_code=row.error_code,
                    lease_until=row.lease_until)


def recover_container(owner, scope_key, node_token, service):
    """Explicitly associate a user-selected existing node via verified GET only.

    This is not title search or an automatic recovery worker. Verify original
    bound identity, exact root/space, origin docx, title and doc object before
    CAS. A late creator cannot overwrite this association. Original write
    state/lease remain in the additive record; no legacy receipt is touched.
    """
    if not isinstance(node_token, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,200}', node_token):
        raise _error('meeting_destination_mismatch')
    with session_scope() as db:
        row = db.get(Container, scope_key)
        if not row or row.owner != owner: raise _error('meeting_job_not_found')
        receipt = {col.name: getattr(row, col.name) for col in Container.__table__.columns}
    if receipt['state'] == 'creating' and receipt['lease_until'] <= time.time():
        _unknown_expired(receipt)
        receipt['state'] = 'unknown'
    if receipt['state'] != 'unknown': raise _error('meeting_recovery_unavailable')
    scope = json.loads(receipt['scope_json'])
    bound = scope['binding']
    snapshot = dict(open_id=bound['sender_open_id'], connection_id=bound['connection_id'],
                    app_id=bound['app_id'], tenant_key=bound['tenant_key'])
    _binding(owner, snapshot, service)
    node = service.request('GET', 'wiki/v2/spaces/get_node', token=service.user_token(owner),
                           params=dict(token=node_token, obj_type='wiki')).get('node', {})
    root = scope['destination']
    if (node.get('space_id') != root['space_id'] or node.get('parent_node_token') != root['node_token']
            or node.get('node_token') != node_token or node.get('obj_type') != 'docx'
            or node.get('node_type') != 'origin' or node.get('title') != receipt['title']):
        raise _error('meeting_destination_mismatch')
    url = service.config.feishu_doc_base_url + '/wiki/' + node_token
    _created_node(node.get('obj_token'), url, service)
    _binding(owner, snapshot, service)
    with session_scope() as db:
        result = db.execute(update(Container).where(Container.scope_key == scope_key,
            Container.owner == owner, Container.state == 'unknown', Container.lease_id == receipt['lease_id'])
            .values(state='confirmed', node_token=node_token, document_id=node['obj_token'],
                    document_url=url, error_code='', lease_until=0))
        if result.rowcount != 1: raise _error('meeting_recovery_unavailable')
    return {**root, 'node_token': node_token}
