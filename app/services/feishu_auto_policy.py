"""Server-owned, connection-bound automatic delivery consent. No network I/O."""
import hashlib
import importlib
import json
import math
import re
import time
import uuid
from contextvars import ContextVar

PROTOCOL = 1
active_delivery = ContextVar('feishu_automatic_delivery', default=None)
_FIELDS = ('binding', 'destination', 'notify_self', 'groups', 'permission_policy', 'contacts')


def runtime():
    try:
        return importlib.import_module('app.services.feishu_auto_runtime')
    except ModuleNotFoundError as exc:
        if exc.name != 'app.services.feishu_auto_runtime':
            raise
        return None


def background_ready():
    worker = runtime()
    return bool(worker and worker.background_ready())


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    separators=(',', ':')).encode()).hexdigest()


def binding(owner, account, preferences, config):
    if not account or not account.tokens or account.expired:
        return None
    result = dict(owner=owner, connection_id=preferences.get('connection_id'),
                  sender_open_id=account.open_id, app_id=config.feishu_app_id,
                  tenant_key=config.feishu_tenant_key)
    return result if all(isinstance(v, str) and v for v in result.values()) else None


def spec(current_binding, destination, notify_self, groups, permission_policy, contacts):
    return dict(binding=current_binding, destination=destination, notify_self=notify_self,
                groups=sorted(groups), permission_policy=permission_policy,
                contacts=sorted(contacts, key=lambda item: item['open_id']))


def saved(preferences, current_binding, *, enabled=False):
    """Only server-persisted, internally consistent consent may authorize work."""
    policy = preferences.get('auto_policy')
    if not current_binding or not isinstance(policy, dict):
        return None
    try:
        if (policy.get('protocol') != PROTOCOL or type(policy.get('protocol')) is not int or
                str(uuid.UUID(policy['id'])) != policy['id'] or
                type(policy.get('enabled')) is not bool or policy.get('binding') != current_binding or
                type(policy.get('enabled_at')) not in (int, float) or
                not math.isfinite(policy['enabled_at']) or policy['enabled_at'] <= 0 or
                not isinstance(policy.get('contacts'), list) or len(policy['contacts']) > 20 or
                type(policy.get('notify_self')) is not bool or
                not isinstance(policy.get('groups'), list) or len(policy['groups']) > 20 or
                any(not isinstance(g, str) or not re.fullmatch(r'oc_[A-Za-z0-9_-]{1,196}', g) for g in policy['groups']) or
                policy.get('permission_policy') not in ('private', 'inherit') or
                not isinstance(policy.get('destination'), dict)):
            return None
        for contact in policy['contacts']:
            if (not isinstance(contact, dict) or contact.get('purpose') != 'feishu_contact_selection_v1' or
                    any(contact.get(k) != v for k, v in current_binding.items()) or
                    not isinstance(contact.get('open_id'), str) or
                    not re.fullmatch(r'ou_[A-Za-z0-9_-]{1,196}', contact['open_id']) or
                    not isinstance(contact.get('name'), str) or not contact['name'].strip() or len(contact['name']) > 500):
                return None
        content = {key: policy[key] for key in _FIELDS}
        if fingerprint(content) != policy.get('fingerprint'):
            return None
        if enabled and (not policy['enabled'] or preferences.get('auto_publish') is not True):
            return None
    except (KeyError, TypeError, ValueError, AttributeError):
        return None
    return policy


def create(content, enabled):
    return dict(protocol=PROTOCOL, id=str(uuid.uuid4()), enabled=enabled,
                enabled_at=time.time(), fingerprint=fingerprint(content), **content)
