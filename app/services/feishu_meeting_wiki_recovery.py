"""Exact delivery-bound recovery of an existing Wiki container, never dispatch."""
import hashlib
import json
import re
import time
from urllib.parse import urlsplit

from app.db import session_scope
from app.db_models import FeishuDeliveryDB
from app.models.feishu_destination import FeishuDeliveryDestinationDB
from app.models.feishu_meeting_wiki import FeishuMeetingWikiChildDB as Child
from app.models.feishu_meeting_wiki import FeishuMeetingWikiContainerDB as Container
from app.services import feishu_meeting_wiki as wiki
from app.services.feishu_service import FeishuError


def _error(message='原会议目录记录无法核验，请查询原交付记录', status=409):
    return FeishuError(message, status, code='meeting_recovery_unavailable')


def _bound(service, owner, delivery_id):
    with session_scope() as db:
        job = db.get(FeishuDeliveryDB, delivery_id)
        child = db.get(Child, delivery_id)
        metadata = db.get(FeishuDeliveryDestinationDB, delivery_id)
        if not job or job.owner != owner or not child or not metadata:
            raise _error('未找到当前账号的会议目录记录', 404)
        container = db.get(Container, child.scope_key)
        if not container or container.owner != owner:
            raise _error('未找到当前账号的会议目录记录', 404)
        try:
            snapshot = json.loads(metadata.snapshot)
            scope = json.loads(container.scope_json)
            original = json.loads(child.snapshot)
            if (snapshot.get('group_meeting_versions') is not True or scope.get('owner') != owner
                    or wiki._digest(scope) != container.scope_key
                    or original.get('scope_key') != container.scope_key or original.get('owner') != owner
                    or original.get('delivery_revision') != job.revision
                    or original.get('content_sha256') != hashlib.sha256(job.content.encode()).hexdigest()
                    or original.get('title_sha256') != hashlib.sha256(job.title.encode()).hexdigest()
                    or any(original.get(key) != scope.get(key) for key in ('canonical_task_id', 'source_sha256'))):
                raise ValueError()
            keys = {'kind', 'space_id', 'node_token', 'folder_token'}
            root = service.normalize_destination({key: value for key, value in snapshot['destination'].items() if key in keys})
            if root.get('kind') != 'wiki' or root != scope['destination']:
                raise ValueError()
            binding = dict(owner=owner, connection_id=snapshot.get('connection_id'),
                sender_open_id=snapshot.get('open_id'), app_id=snapshot.get('app_id'), tenant_key=snapshot.get('tenant_key'))
            if binding != scope['binding']:
                raise ValueError()
            result = {column.name: getattr(container, column.name) for column in Container.__table__.columns}
            revision = wiki._digest(dict(delivery_id=delivery_id, scope_key=child.scope_key,
                child=child.snapshot, lease_id=container.lease_id, lease_until=container.lease_until,
                state=container.state, title=container.title, node_token=container.node_token))
        except (ValueError, TypeError, KeyError, AttributeError):
            raise _error() from None
    # Binding-only association: a revoked automatic policy never authorizes a
    # resumed delivery, but it must not require new consent for this GET + CAS.
    wiki._binding(owner, {key: snapshot[key] for key in ('connection_id', 'open_id', 'app_id', 'tenant_key')}, service)
    return result, root, revision


def read_container(service, owner, delivery_id):
    receipt, root, revision = _bound(service, owner, delivery_id)
    expired = receipt['state'] == 'creating' and receipt['lease_until'] <= time.time()
    state = 'unknown' if expired else receipt['state']
    return dict(protocol=1, delivery_id=delivery_id, state=state,
        title=receipt['title'], root_destination=root, context_revision=revision,
        can_recover=state == 'unknown', document_url=receipt['document_url'] if state == 'confirmed' else '')


def _node_token(value):
    if not isinstance(value, str) or not value or len(value) > 2048:
        raise _error('请输入已有会议目录的 Wiki 链接或节点标识', 422)
    if re.fullmatch(r'[A-Za-z0-9_-]{1,200}', value):
        return value
    if any(ord(char) <= 32 or ord(char) == 127 or char == '\\' for char in value):
        raise _error('请输入有效的飞书 Wiki 目录链接', 422)
    try:
        parsed = urlsplit(value)
        host = re.fullmatch(r'(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+feishu\.cn', parsed.hostname or '')
        path = re.fullmatch(r'/wiki/([A-Za-z0-9_-]{1,200})', parsed.path)
        if (parsed.scheme != 'https' or not host or not path or parsed.username is not None
                or parsed.password is not None or parsed.port not in (None, 443)):
            raise ValueError()
        return path[1]
    except (ValueError, TypeError):
        raise _error('请输入有效的飞书 Wiki 目录链接', 422) from None


def recover_for_delivery(service, owner, delivery_id, *, expected_user_id, confirmed, context_revision, url):
    if expected_user_id != owner or confirmed is not True:
        raise _error('账号已变化或尚未明确确认，未关联会议目录')
    node = _node_token(url)
    receipt, _, revision = _bound(service, owner, delivery_id)
    if context_revision != revision:
        raise _error('原会议目录状态已变化，请重新读取')
    # Existing helper owns state/lease CAS and official GET identity/root/title
    # verification. The container may already have children; never require empty.
    wiki.recover_container(owner, receipt['scope_key'], node, service)
    return read_container(service, owner, delivery_id)
