import httpx
import pytest

from app.services import workspace_bootstrap as module


def test_table_permissions_follow_dedicated_schema_and_do_not_touch_public():
    from types import SimpleNamespace
    from sqlalchemy.dialects import postgresql

    statements = []

    class Connection:
        dialect = postgresql.dialect()

        def exec_driver_sql(self, sql):
            statements.append(sql)
            return SimpleNamespace(scalar_one=lambda: 'vinote_workspace')

    module.protect_api_tables(Connection(), [SimpleNamespace(schema=None, name='workspace_notes')])
    assert statements[1:] == [
        'ALTER TABLE vinote_workspace.workspace_notes ENABLE ROW LEVEL SECURITY',
        'REVOKE ALL ON TABLE vinote_workspace.workspace_notes FROM PUBLIC, anon, authenticated',
    ]


@pytest.fixture
def storage(monkeypatch):
    monkeypatch.setattr(module.settings, 'workspace_storage_url', 'https://storage.example')
    monkeypatch.setattr(module.settings, 'workspace_storage_key', 'server-only-fixture')
    monkeypatch.setattr(module.settings, 'workspace_storage_bucket', 'vinote-content')
    real_client = httpx.Client

    def connect(handler):
        monkeypatch.setattr(module.httpx, 'Client', lambda **kwargs: real_client(
            **kwargs, transport=httpx.MockTransport(handler)))
    return connect


def test_bootstrap_creates_private_bucket_and_repeated_start_does_not_recreate(storage):
    requests, bucket = [], {}

    def handle(request):
        requests.append((request.method, request.url.path))
        if request.method == 'POST':
            import json
            bucket.update(json.loads(request.content))
            return httpx.Response(200, json={'name': bucket['name']})
        return httpx.Response(200 if bucket else 404, json=bucket)

    storage(handle)
    module.initialize_private_storage()
    module.initialize_private_storage()
    assert bucket['public'] is False
    assert bucket['file_size_limit'] == 5242880
    assert bucket['allowed_mime_types'] == ['image/png', 'image/jpeg', 'image/webp']
    assert requests.count(('POST', '/storage/v1/bucket')) == 1


def test_bootstrap_refuses_existing_public_bucket_without_changing_it(storage):
    requests = []

    def handle(request):
        requests.append(request.method)
        return httpx.Response(200, json={'public': True})

    storage(handle)
    with pytest.raises(RuntimeError, match='必须为私有'):
        module.initialize_private_storage()
    assert requests == ['GET']


def test_failed_bootstrap_never_claims_ready_or_exposes_storage_key(storage):
    storage(lambda request: httpx.Response(503))
    with pytest.raises(RuntimeError) as unavailable:
        module.initialize_private_storage()
    assert 'server-only-fixture' not in str(unavailable.value)


def test_storage_legacy_not_found_payload_creates_bucket(storage):
    requests, bucket = [], {}

    def handle(request):
        import json
        requests.append(request.method)
        if request.method == 'POST':
            bucket.update(json.loads(request.content))
            return httpx.Response(200, json=bucket)
        if not bucket:
            return httpx.Response(400, json={'statusCode': '404', 'error': 'Bucket not found'})
        return httpx.Response(200, json=bucket)

    storage(handle)
    module.initialize_private_storage()
    assert requests == ['GET', 'POST', 'GET']
    assert bucket['public'] is False


def test_storage_legacy_unauthorized_payload_never_creates_bucket(storage):
    requests = []

    def handle(request):
        requests.append(request.method)
        return httpx.Response(400, json={'statusCode': '403', 'error': 'Unauthorized'})

    storage(handle)
    with pytest.raises(RuntimeError, match='无法核验'):
        module.initialize_private_storage()
    assert requests == ['GET']
