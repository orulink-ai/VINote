from contextlib import contextmanager

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from app.db import Base
from app.db_models import FeishuApplicationDB
from app.services import feishu_application_service as app_config
from app.services.feishu_service import FeishuService


@pytest.fixture
def application(monkeypatch):
    engine = create_engine('sqlite://')
    Base.metadata.create_all(engine)
    @contextmanager
    def sessions():
        with Session(engine) as db, db.begin():
            yield db
    monkeypatch.setattr(app_config, 'session_scope', sessions)
    monkeypatch.setattr(app_config.settings, 'model_profile_encryption_key', 'test-app-key')
    monkeypatch.setattr(app_config.settings, 'feishu_redirect_uri', 'https://notes.example/api/feishu/callback')
    monkeypatch.setattr(app_config.settings, 'feishu_app_id', 'cli_company')
    monkeypatch.setattr(FeishuService, 'request', lambda *a, **kw: {'tenant_access_token': 'probe'})
    yield sessions
    engine.dispose()


def test_credentials_are_encrypted_owner_isolated_and_not_returned(application):
    payload = dict(app_id='cli_personal', app_secret='private-secret', tenant_key='company', document_domain='https://company.feishu.cn')
    status = app_config.save_application('alice', payload)
    assert 'private-secret' not in str(status)
    with application() as db:
        assert 'private-secret' not in db.get(FeishuApplicationDB, 'alice').credentials
    assert app_config.application_config('alice').feishu_app_secret == 'private-secret'
    assert app_config.application_status('bob')['app_id'] == 'cli_company'
    app_config.clear_application('alice')
    assert app_config.application_status('alice')['custom'] is False


@pytest.mark.parametrize('domain', ['http://company.feishu.cn', 'https://company.feishu.cn.evil.test', 'https://company.feishu.cn/path', 'https://user:pass@company.feishu.cn'])
def test_invalid_document_domain_is_rejected_before_storing(application, domain):
    with pytest.raises(ValueError):
        app_config.save_application('alice', dict(app_id='cli_personal', app_secret='secret', tenant_key='company', document_domain=domain))
    assert app_config.application_status('alice')['custom'] is False
