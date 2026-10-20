"""Destination shortcut scope comes from an existing verified connection only."""
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import re
import time
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db import Base
from app.db_models import FeishuConnectionDB
from app.routers import feishu as route
from app.services import feishu_cli as cli, feishu_cli_service as local, feishu_service as base
from app.services.cloud_account_service import _cipher


@pytest.fixture
def connection(tmp_path, monkeypatch):
    for key, value in dict(desktop_runtime=True, feishu_transport='cli',
                           workspace_cloud_runtime=False, content_cloud_runtime=False,
                           model_profile_encryption_key='location-test-key', data_dir=tmp_path).items():
        monkeypatch.setattr(base.settings, key, value)
    engine = create_engine(f"sqlite:///{tmp_path / 'connection.db'}")
    Base.metadata.create_all(engine)

    @contextmanager
    def sessions():
        with Session(engine) as db, db.begin():
            yield db

    monkeypatch.setattr(base, 'session_scope', sessions)
    monkeypatch.setattr(local, 'session_scope', sessions)
    monkeypatch.setattr(cli, 'executable', lambda: 'C:/synthetic/lark-cli.exe')
    monkeypatch.setattr(cli.subprocess, 'run', lambda *a, **k: pytest.fail('Real CLI forbidden'))
    monkeypatch.setattr(base.httpx, 'request', lambda *a, **k: pytest.fail('Real HTTP forbidden'))
    payload = dict(transport='cli', app_id='cli_location', tenant_key='tenant_location',
                   scope='docx:document drive:drive.metadata:readonly', expires_at=time.time() + 7200)
    with sessions() as db:
        db.add(FeishuConnectionDB(owner='alice', name='Synthetic account', open_id='ou_location',
            tokens=_cipher().encrypt(json.dumps(payload).encode()).decode(),
            preferences=json.dumps(dict(connection_id=str(uuid4()), notify_self=True))))
    ctx = SimpleNamespace(service=local.FeishuCLIService('alice'), sessions=sessions, reads=[])

    def stored():
        with sessions() as db:
            row = db.get(FeishuConnectionDB, 'alice')
            return row.open_id, row.tokens, row.preferences, row.expired

    ctx.stored = stored

    def auth_status(owner):
        open_id, encrypted, _, _ = stored()
        data = json.loads(_cipher().decrypt(encrypted.encode()))
        return dict(appId=data['app_id'], brand='feishu', identities=dict(user=dict(
            openId=open_id, tokenStatus='valid', scope=data['scope'],
            expiresAt=datetime.fromtimestamp(data['expires_at'], timezone.utc).isoformat())))

    def api(owner, method, path, **kwargs):
        assert (owner, method, path) == ('alice', 'GET', 'authen/v1/user_info')
        ctx.reads.append((method, path))
        return dict(open_id=stored()[0], name='Synthetic account', tenant_key=payload['tenant_key'])

    monkeypatch.setattr(cli, 'auth_status', auth_status)
    monkeypatch.setattr(cli, 'api', api)
    yield ctx
    engine.dispose()


def test_status_binding_is_stable_opaque_and_projection_does_not_write(connection):
    c = connection
    before = c.stored()
    first = c.service._connection_status('alice')
    assert first['connected'] and first['grant_state'] == 'verified'
    assert re.fullmatch('[a-f0-9]{64}', first['connection_binding_hash'])
    assert c.service._connection_status('alice')['connection_binding_hash'] == first['connection_binding_hash']
    assert c.stored() == before and c.reads == []
    assert not {'tokens', 'access_token', 'refresh_token', 'connection_id', 'open_id', 'app_id'} & first.keys()


@pytest.mark.parametrize('field', ['owner', 'connection_id', 'sender', 'app', 'tenant'])
def test_each_identity_dimension_has_a_separate_shortcut_scope(connection, field):
    c = connection
    old = c.service._connection_status('alice')['connection_binding_hash']
    with c.sessions() as db:
        row = db.get(FeishuConnectionDB, 'alice')
        if field == 'owner':
            db.add(FeishuConnectionDB(owner='bob', name=row.name, open_id=row.open_id,
                                     tokens=row.tokens, preferences=row.preferences))
        elif field == 'connection_id':
            preferences = json.loads(row.preferences)
            preferences['connection_id'] = str(uuid4())
            row.preferences = json.dumps(preferences)
        elif field == 'sender':
            row.open_id = 'ou_changed'
        else:
            payload = json.loads(_cipher().decrypt(row.tokens.encode()))
            payload['app_id' if field == 'app' else 'tenant_key'] += '_changed'
            row.tokens = _cipher().encrypt(json.dumps(payload).encode()).decode()
    service = local.FeishuCLIService('bob') if field == 'owner' else c.service
    assert service._connection_status('bob' if field == 'owner' else 'alice')['connection_binding_hash'] != old


def test_token_and_preference_changes_do_not_change_identity_scope(connection):
    c = connection
    old = c.service._connection_status('alice')['connection_binding_hash']
    with c.sessions() as db:
        row = db.get(FeishuConnectionDB, 'alice')
        preferences = json.loads(row.preferences)
        preferences.update(notify_self=False, groups=['oc_other'])
        row.preferences = json.dumps(preferences)
        payload = json.loads(_cipher().decrypt(row.tokens.encode()))
        payload.update(scope='docx:document', expires_at=time.time() + 9000)
        row.tokens = _cipher().encrypt(json.dumps(payload).encode()).decode()
    assert c.service._connection_status('alice')['connection_binding_hash'] == old


@pytest.mark.parametrize('identifier', [None, '', '   ', True, 1, [], {}])
def test_missing_or_untyped_id_never_gets_invented_by_projection(connection, identifier):
    c = connection
    with c.sessions() as db:
        row = db.get(FeishuConnectionDB, 'alice')
        preferences = json.loads(row.preferences)
        preferences['connection_id'] = identifier
        row.preferences = json.dumps(preferences)
    before = c.stored()
    result = c.service._connection_status('alice')
    assert 'connection_binding_hash' not in result
    assert c.stored() == before and c.reads == []


@pytest.mark.parametrize('missing', ['connection_id', 'sender', 'app', 'tenant', 'tokens', 'expired', 'unavailable'])
def test_incomplete_or_unverified_identity_has_no_shortcut_scope(connection, missing):
    c = connection
    with c.sessions() as db:
        row = db.get(FeishuConnectionDB, 'alice')
        if missing == 'connection_id':
            preferences = json.loads(row.preferences)
            preferences.pop('connection_id')
            row.preferences = json.dumps(preferences)
        elif missing == 'sender': row.open_id = ''
        elif missing == 'tokens': row.tokens = ''
        elif missing == 'expired': row.expired = True
        elif missing in ('app', 'tenant'):
            payload = json.loads(_cipher().decrypt(row.tokens.encode()))
            payload['app_id' if missing == 'app' else 'tenant_key'] = ''
            row.tokens = _cipher().encrypt(json.dumps(payload).encode()).decode()
    before = c.stored()
    result = c.service._connection_status('alice', refresh_unavailable=missing == 'unavailable')
    assert 'connection_binding_hash' not in result and c.stored() == before


def test_actual_cli_status_route_carries_the_same_binding_without_new_business_calls(connection):
    c = connection
    expected = c.service._connection_status('alice')['connection_binding_hash']
    preferences = c.stored()[2]
    app = FastAPI()
    app.include_router(route.router, prefix='/api')
    app.dependency_overrides[route.principal] = lambda: ('alice', 'alice')
    response = TestClient(app).get('/api/feishu/status')
    assert response.status_code == 200
    result = response.json()
    assert result['transport'] == 'cli' and result['connection_binding_hash'] == expected
    assert c.stored()[2] == preferences
    assert c.reads == [('GET', 'authen/v1/user_info')]
