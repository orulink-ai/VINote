"""Runs against isolated candidate; no provider calls, no root source writes."""
import copy
import importlib.util
import json
from pathlib import Path

import pytest
import httpx
from fastapi import HTTPException

HERE = Path(__file__).parents[1]
spec = importlib.util.spec_from_file_location('isolated_vilab_public_metadata', HERE/'app/services/vilab_cloud_service.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
Service = module.VILabCloudService


def catalog(monkeypatch, entries):
    service = Service()
    def request(owner, method, path):
        assert (owner, method, path) == ('owner-a', 'GET', '/v1/models')
        return {'data': entries, 'authorization': 'secret-envelope'}
    monkeypatch.setattr(service, 'request', request)
    return service.models('owner-a')


def test_only_bounded_public_metadata_is_added_without_credentials_or_unrelated_fields(monkeypatch):
    entry = {'id': 'asr:14:opaque', 'modelType': 'asr', 'runtimeStatus': 'not_available',
             'name': '  阿里云实时语音  ', 'providerId': 'aliyun', 'providerModel': 'paraformer-realtime-v2',
             'availability': {'status': 'service_error', 'retryAt': 123},
             'capabilities': {'audio': True, 'maxDurationSeconds': 123.5},
             'apiKey': 'secret-api-key', 'token': 'secret-token', 'credentials': {'accessToken': 'secret-credentials'},
             'baseUrl': 'https://private.invalid/key', 'providerConfig': {'secret': 'hidden'},
             'debug': {'raw': 'secret-provider-raw'}, 'providerName': 'unrequested-field'}
    untouched = copy.deepcopy(entry)
    result = catalog(monkeypatch, [entry])
    assert result == [{key: entry[key] for key in ('id', 'modelType', 'runtimeStatus', 'availability', 'capabilities')} | {
        'name': '阿里云实时语音', 'providerId': 'aliyun', 'providerModel': 'paraformer-realtime-v2'}]
    serialized = json.dumps(result)
    for private in ['secret', 'hidden', 'private.invalid', 'unrequested-field', 'providerConfig', 'baseUrl', 'credentials']:
        assert private not in serialized
    assert entry == untouched


@pytest.mark.parametrize('field', ['name', 'providerId', 'providerModel'])
@pytest.mark.parametrize('invalid', [None, True, 1, 1.5, [], {}, {'token': 'secret'}, '', '   ', 'x'*121,
                                     'text\nraw', 'text\rraw', 'text\x00raw', 'text\x7fraw', 'https://user:password@private.invalid'])
def test_invalid_public_fields_are_omitted_not_coerced(monkeypatch, field, invalid):
    value = catalog(monkeypatch, [{'id': 'opaque', 'modelType': 'asr', field: invalid}])[0]
    assert field not in value
    assert value['id'] == 'opaque'


@pytest.mark.parametrize('field', ['name', 'providerId', 'providerModel'])
def test_public_string_boundary_and_unicode(monkeypatch, field):
    assert catalog(monkeypatch, [{'id': 'opaque', 'modelType': 'llm', field: '模'*120}])[0][field] == '模'*120
    assert catalog(monkeypatch, [{'id': 'opaque', 'modelType': 'llm', field: ' 模型 '}])[0][field] == '模型'


def test_legacy_catalog_without_names_preserves_id_kind_and_safety_fields(monkeypatch):
    entries = [{'id': 'asr:14:opaque', 'modelType': 'asr', 'runtimeStatus': 'available', 'availability': {'status': 'disabled'}, 'capabilities': {'realtime': True}},
               {'id': 'llm:22:opaque', 'modelType': 'llm', 'runtimeStatus': 'not_available'}]
    assert catalog(monkeypatch, entries) == entries


def test_ids_are_neither_decoded_nor_rewritten_and_kind_is_not_inferred(monkeypatch):
    assert catalog(monkeypatch, [None, 'malformed', {'id': 'other', 'modelType': 'unknown'},
                                {'id': ' asr:14:opaque ', 'modelType': 'asr', 'name': 'Public name'}]) == [
        {'id': ' asr:14:opaque ', 'modelType': 'asr', 'runtimeStatus': '', 'name': 'Public name'}]


def test_public_name_cannot_make_blocked_or_wrong_type_model_eligible(monkeypatch):
    entries = catalog(monkeypatch, [{'id': 'original', 'modelType': 'asr', 'runtimeStatus': 'not_available',
                                    'name': 'Friendly name', 'availability': {'status': 'auth_failed'}}])
    for selected, kind in [('original', 'asr'), ('Friendly name', 'asr'), ('original', 'llm')]:
        with pytest.raises(HTTPException):
            Service._validate_selection(entries, selected, kind)


def test_models_reads_are_account_bound_and_do_not_mutate_snapshot_or_preferences(monkeypatch):
    service = Service()
    calls = []
    def request(owner, method, path):
        calls.append((owner, method, path))
        return {'data': [{'id': owner, 'modelType': 'asr', 'name': owner+' public'}]}
    monkeypatch.setattr(service, 'request', request)
    for owner in ('owner-a', 'owner-b', 'owner-a'):
        assert service.models(owner)[0]['id'] == owner
    assert calls == [(owner, 'GET', '/v1/models') for owner in ('owner-a', 'owner-b', 'owner-a')]


def test_mocked_gateway_auth_header_never_becomes_public_catalog_metadata(monkeypatch):
    service = Service()
    monkeypatch.setattr(module.settings, 'vilab_server_url', 'https://catalog.invalid')
    monkeypatch.setattr(module.settings, 'cloud_auth_url', '')
    monkeypatch.setattr(module.settings, 'vilab_api_key', 'synthetic-header-secret')
    monkeypatch.setattr(service, 'status', lambda owner: {'server_url': 'https://catalog.invalid'})
    def request(method, url, **kwargs):
        assert method == 'GET' and url == 'https://catalog.invalid/v1/models'
        assert kwargs['headers']['Authorization'] == 'Bearer synthetic-header-secret'
        return httpx.Response(200, json={'data': [{'id': 'opaque', 'modelType': 'asr', 'name': '公开名称', 'apiKey': 'synthetic-header-secret'}]})
    monkeypatch.setattr(module.httpx, 'request', request)
    result = service.models('owner-a')
    assert result[0]['name'] == '公开名称'
    assert 'synthetic-header-secret' not in json.dumps(result)


def test_rejected_gateway_identity_cannot_echo_token_or_provider_raw_error(monkeypatch):
    service = Service()
    monkeypatch.setattr(module.settings, 'vilab_server_url', 'https://catalog.invalid')
    monkeypatch.setattr(module.settings, 'cloud_auth_url', '')
    monkeypatch.setattr(service, 'status', lambda owner: {'server_url': 'https://catalog.invalid'})
    monkeypatch.setattr(module.httpx, 'request', lambda *a, **k: httpx.Response(401, text='synthetic-provider-secret'))
    with pytest.raises(HTTPException) as error:
        service.models('owner-a')
    assert error.value.status_code == 502
    assert 'synthetic-provider-secret' not in error.value.detail
